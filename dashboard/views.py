from datetime import timedelta
import csv
from types import SimpleNamespace
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import password_validation
from django.contrib.auth import get_user_model
from django.contrib.auth import logout
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import Group
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from allauth.account.views import SignupView
from django.contrib.messages import get_messages
from django.core import signing
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Sum
from django.db.models import Q
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import BusinessUnit
from core.models import Role
from core.models import RoleChangeAudit
from core.models import UserProfile
from core.rbac.constants import ModuleCode
from core.rbac.constants import PermissionAction
from core.rbac.constants import RoleCode
from core.rbac.constants import is_consultant_role
from core.rbac.constants import is_manager_role
from core.rbac.constants import ROLES_REQUIRING_BUSINESS_UNITS
from core.rbac.decorators import require_module_permission
from core.rbac.services import can_view
from core.rbac.services import can_manage as rbac_can_manage
from core.rbac.services import is_platform_admin
from crm.models import CallLog, Lead, Sale, SalesRep
from dashboard.business_units import BUSINESS_UNIT_PAGES_BY_KEY
from dashboard.forms import AssociateAccessCreateForm
from dashboard.forms import AccessManagementAssignForm
from dashboard.forms import AccessManagementCreateForm
from dashboard.forms import AnnouncementForm
from dashboard.forms import AppointmentForm
from dashboard.forms import AssociateProfileForm
from dashboard.forms import CallLogForm
from dashboard.forms import CalendarEventForm
from dashboard.forms import LoginForm
from dashboard.forms import InvitationSignupForm
from dashboard.forms import InvitedAllauthSignupForm
from dashboard.forms import OfferForm
from dashboard.forms import SharedResourceForm
from dashboard.forms import TaskForm
from dashboard.forms import UserWorkProfileForm
from dashboard.forms import UserProfileForm
from dashboard.models import Appointment
from dashboard.models import Announcement
from dashboard.models import CalendarEvent
from dashboard.models import OperationsAdminInviteRequest
from dashboard.models import AdminInviteRequest
from dashboard.models import Offer
from dashboard.models import ResourceTag
from dashboard.models import SharedResource
from dashboard.models import Task
from dashboard.serializers import TeamMemberSerializer
from dashboard.services.team_personal_info_service import compute_team_personal_metrics
from dashboard.services.team_personal_info_service import filter_team_personal_rows
from dashboard.services.team_personal_info_service import get_salesrep_profiles
from dashboard.services.team_personal_info_service import resolve_scope_profile_for_user
from dashboard.services.team_personal_info_service import sanitize_team_payload_for_actor
from dashboard.services.team_service import get_team_dashboard_context
from dashboard.services.team_service import query_team_rows
from dashboard.services.team_service import resolve_my_team_scope
from dashboard.services.team_service import resolve_team_scope
from dashboard.services.sales_team_service import apply_sales_team_filters
from dashboard.services.sales_team_service import can_access_team_section
from dashboard.services.sales_team_service import can_manage_operations_admin_group
from dashboard.services.sales_team_service import can_start_salesrep_promotions
from dashboard.services.sales_team_service import compute_sales_team_summary
from dashboard.services.sales_team_service import expire_pending_admin_invites
from dashboard.services.sales_team_service import get_sales_team_rows
from dashboard.services.sales_team_service import resolve_sales_team_scope_profile_for_user
from dashboard.services.sales_team_service import role_sort_value
from dashboard.services.sales_team_service import set_admin_invite_decision
from dashboard.services.sales_team_service import user_can_execute_removal
from dashboard.services.sales_team_service import user_can_request_removal
from dashboard.services.sales_team_graph_service import compute_graph_summary
from dashboard.services.sales_team_graph_service import fetch_hierarchy_iterative
from finance.models import Commission
from finance.models import CommissionAllocation
from finance.models import FinancingPartner
from rewards.models import Redemption, RewardPoint
from rewards.models import PlanTierRule
from rewards.models import Tier

User = get_user_model()
GROW_TEAM_SIGNER_SALT = "grow-team-invite"
GROW_TEAM_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24


class OneGroupLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        remember_me = form.cleaned_data.get("remember_me")
        if remember_me:
            # Keep the authenticated session for two weeks on trusted devices.
            self.request.session.set_expiry(60 * 60 * 24 * 14)
        else:
            # Session expires when the browser is closed.
            self.request.session.set_expiry(0)
        return response


def _profile(user):
    return getattr(user, "profile", None)


COMMISSION_COLUMN_ORDER = [
    RoleCode.SOLAR_CONSULTANT,
    RoleCode.SOLAR_ADVISOR,
    RoleCode.MANAGER,
    RoleCode.SENIOR_MANAGER,
    RoleCode.ELITE_MANAGER,
    RoleCode.BUSINESS_MANAGER,
    RoleCode.JR_PARTNER,
    RoleCode.PARTNER,
]


def _visible_commission_roles_for_user(user) -> set[str]:
    if user.is_superuser:
        return set(COMMISSION_COLUMN_ORDER)
    profile = _profile(user)
    if not profile or profile.role not in COMMISSION_COLUMN_ORDER:
        return {RoleCode.SOLAR_CONSULTANT}
    max_index = COMMISSION_COLUMN_ORDER.index(profile.role)
    return set(COMMISSION_COLUMN_ORDER[: max_index + 1])


def _sales_rep(user):
    return SalesRep.objects.filter(user=user).select_related("tier", "business_unit", "level").first()


def _resolve_business_units_for_inviter(inviter):
    profile = _profile(inviter)
    unit_ids = []
    if profile:
        unit_ids = list(profile.business_units.values_list("id", flat=True))
        if not unit_ids and profile.business_unit_id:
            unit_ids = [profile.business_unit_id]
    if not unit_ids:
        inviter_sales_rep = _sales_rep(inviter)
        if inviter_sales_rep and inviter_sales_rep.business_unit_id:
            unit_ids = [inviter_sales_rep.business_unit_id]
    if unit_ids:
        return list(BusinessUnit.objects.filter(id__in=unit_ids, is_active=True).order_by("id"))
    fallback_unit = BusinessUnit.objects.filter(is_active=True).order_by("id").first()
    return [fallback_unit] if fallback_unit else []


def _decode_grow_team_token(signed_token, *, max_age=GROW_TEAM_TOKEN_MAX_AGE_SECONDS):
    signer = signing.TimestampSigner(salt=GROW_TEAM_SIGNER_SALT)
    try:
        raw_payload = signer.unsign(signed_token, max_age=max_age)
    except signing.SignatureExpired:
        return None, None, "Este enlace de invitación expiró. Solicita uno nuevo."
    except signing.BadSignature:
        return None, None, "El enlace de invitación no es válido."

    inviter_part, separator, level_part = raw_payload.partition(":")
    if not separator:
        return None, None, "El enlace de invitación no es válido."

    try:
        inviter_id = int(inviter_part)
    except (TypeError, ValueError):
        return None, None, "El enlace de invitación no es válido."

    inviter = User.objects.filter(pk=inviter_id).first()
    valid_levels = {code for code, _ in UserProfile.Role.choices}
    if not inviter or level_part not in valid_levels:
        return None, None, "El enlace de invitación no es válido."
    return inviter, level_part, ""


class CustomSignupView(SignupView):
    template_name = "registration/signup_invited.html"
    form_class = InvitedAllauthSignupForm
    invitation_required_message = "You must be invited to register."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            # Keep this invitation flow publicly usable even from an active session.
            request.user = AnonymousUser()
        self._invitation_valid = False
        self._invitation_error = ""
        self._resolved_parent_id = None
        self._resolved_level_id = None
        self._resolved_parent_name = ""
        self._resolved_level_name = ""
        self._resolved_invite_role = ""
        self._resolve_invitation_state()
        return super().dispatch(request, *args, **kwargs)

    def _default_level(self):
        return Role.objects.order_by("priority", "id").first()

    def _clear_invite_session(self):
        keys = [
            "invite_role",
            "invite_admin_request_id",
            "parent_name",
            "level_name",
            "parent_id",
            "level_id",
        ]
        for key in keys:
            self.request.session.pop(key, None)
        for key in list(self.request.session.keys()):
            if key.startswith("preinscripcion_"):
                self.request.session.pop(key, None)

    def _resolve_invitation_state(self):
        parent_id = self.kwargs.get("parent_id")
        level_id = self.kwargs.get("level_id")
        invite_role = (self.request.GET.get("invite_role") or "").strip().lower()
        invite_token = (self.request.GET.get("invite_token") or "").strip()

        parent = User.objects.filter(pk=parent_id).first()
        level = Role.objects.filter(pk=level_id).first() if level_id else None
        if level is None:
            level = self._default_level()

        if not parent or not level:
            self._clear_invite_session()
            self._invitation_error = self.invitation_required_message
            return

        parent_profile = getattr(parent, "profile", None)
        parent_name = parent.get_full_name().strip() or parent.get_username()
        self.request.session["parent_name"] = parent_name
        self.request.session["level_name"] = level.name
        self.request.session["parent_id"] = parent.id
        self.request.session["level_id"] = level.id
        self.request.session["preinscripcion_parent_id"] = parent.id
        self.request.session["preinscripcion_level_id"] = level.id

        if invite_role == "admin" and invite_token:
            is_partner = bool(parent_profile and parent_profile.role == RoleCode.PARTNER)
            admin_request = (
                AdminInviteRequest.objects.filter(
                    token=invite_token,
                    inviter_id=parent.id,
                    level_id=level.id,
                    status=AdminInviteRequest.Status.INVITED,
                    used_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .order_by("-id")
                .first()
            )
            if not is_partner or not admin_request:
                self._clear_invite_session()
                self._invitation_error = self.invitation_required_message
                return
            self.request.session["invite_role"] = "admin"
            self.request.session["invite_admin_request_id"] = admin_request.id
        else:
            self.request.session.pop("invite_role", None)
            self.request.session.pop("invite_admin_request_id", None)

        self._resolved_parent_id = parent.id
        self._resolved_level_id = level.id
        self._resolved_parent_name = parent_name
        self._resolved_level_name = level.name
        self._resolved_invite_role = self.request.session.get("invite_role", "")
        self._invitation_valid = True

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial = kwargs.setdefault("initial", {})
        if self._resolved_parent_id:
            initial["parent_id"] = self._resolved_parent_id
        if self._resolved_level_id:
            initial["level_id"] = self._resolved_level_id
        if self._resolved_invite_role:
            initial["invite_role"] = self._resolved_invite_role
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "parent_id": self.request.session.get("parent_id"),
                "level_id": self.request.session.get("level_id"),
                "parent_name": self.request.session.get("parent_name", ""),
                "level_name": self.request.session.get("level_name", ""),
                "invite_role": self.request.session.get("invite_role", ""),
                "invitation_valid": self._invitation_valid,
                "invitation_error": self._invitation_error or self.invitation_required_message,
                "password_rules": password_validation.password_validators_help_texts(),
            }
        )
        return context

    def form_invalid(self, form):
        context = self.get_context_data(form=form)
        context["parent_id"] = self.request.session.get("parent_id")
        context["level_id"] = self.request.session.get("level_id")
        context["invite_role"] = self.request.session.get("invite_role", "")
        return self.render_to_response(context)

    def form_valid(self, form):
        if not self._invitation_valid:
            form.add_error(None, self._invitation_error or self.invitation_required_message)
            return self.form_invalid(form)
        super().form_valid(form)
        logout(self.request)
        return redirect("login")

    def get_success_url(self):
        return reverse("login")


def _is_superadmin(user):
    return bool(user and user.is_superuser)


def _is_platform_admin(user, profile):
    return is_platform_admin(user)


def _is_associate(profile, sales_rep):
    return bool(profile and is_consultant_role(profile.role) and sales_rep)


def _manager_business_unit_ids(profile):
    if not profile or not is_manager_role(profile.role):
        return []
    ids = list(profile.business_units.values_list("id", flat=True))
    if not ids and profile.business_unit_id:
        ids = [profile.business_unit_id]
    return ids


def _associate_business_unit_ids(profile, sales_rep):
    if not profile or not is_consultant_role(profile.role):
        return []
    ids = list(profile.business_units.values_list("id", flat=True))
    if not ids and profile.business_unit_id:
        ids = [profile.business_unit_id]
    if not ids and sales_rep and sales_rep.business_unit_id:
        ids = [sales_rep.business_unit_id]
    return ids


def _apply_role_access(user, role, business_units, tier):
    profile = _profile(user)
    if profile is None:
        profile = UserProfile.objects.create(user=user, role=role)

    selected_units = list(business_units or [])
    primary_business_unit = selected_units[0] if selected_units else None

    profile.role = role
    profile.business_unit = primary_business_unit if role in ROLES_REQUIRING_BUSINESS_UNITS else None
    profile.save(update_fields=["role", "role_ref", "business_unit"])
    profile.business_units.set(selected_units if role in ROLES_REQUIRING_BUSINESS_UNITS else [])

    if is_consultant_role(role):
        sales_rep, _ = SalesRep.objects.get_or_create(
            user=user,
            defaults={"business_unit": primary_business_unit, "tier": tier},
        )
        changed_fields = []
        if primary_business_unit and sales_rep.business_unit_id != primary_business_unit.id:
            sales_rep.business_unit = primary_business_unit
            changed_fields.append("business_unit")
        if sales_rep.tier_id != (tier.id if tier else None):
            sales_rep.tier = tier
            changed_fields.append("tier")
        if changed_fields:
            sales_rep.save(update_fields=changed_fields)


def _can_manage(user, profile):
    if _is_platform_admin(user, profile):
        return True
    return bool(profile and is_manager_role(profile.role))


def _sales_queryset(user, profile, sales_rep):
    qs = Sale.objects.select_related("sales_rep__user", "product", "plan", "business_unit")
    if _is_platform_admin(user, profile):
        return qs
    if profile and is_manager_role(profile.role):
        manager_unit_ids = _manager_business_unit_ids(profile)
        if not manager_unit_ids:
            return qs.none()
        return qs.filter(business_unit_id__in=manager_unit_ids)
    if _is_associate(profile, sales_rep):
        associate_unit_ids = _associate_business_unit_ids(profile, sales_rep)
        if not associate_unit_ids:
            return qs.none()
        return qs.filter(sales_rep=sales_rep, business_unit_id__in=associate_unit_ids)
    return qs.none()


def _can_access_business_unit(user, profile, sales_rep, business_unit):
    if _is_platform_admin(user, profile):
        return True
    if profile and is_manager_role(profile.role):
        return business_unit.id in _manager_business_unit_ids(profile)
    if _is_associate(profile, sales_rep):
        # Associates can open any business unit page, but their data remains scoped
        # to their own SalesRep profile in `business_unit_overview`.
        return True
    return False


def _status_chart_data(sales_qs):
    return [
        {"label": "Confirmadas", "value": sales_qs.filter(status=Sale.Status.CONFIRMED).count(), "color": "#2fb66f"},
        {"label": "Pendientes", "value": sales_qs.filter(status=Sale.Status.PENDING).count(), "color": "#a57cff"},
        {"label": "Borrador", "value": sales_qs.filter(status=Sale.Status.DRAFT).count(), "color": "#7b8da6"},
        {"label": "Canceladas", "value": sales_qs.filter(status=Sale.Status.CANCELLED).count(), "color": "#df5a71"},
    ]


def _daily_sales_chart_data(sales_qs):
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=6)

    raw_rows = (
        sales_qs.filter(created_at__date__gte=start_date)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    totals_by_day = {row["day"]: row["total"] for row in raw_rows}

    labels = []
    values = []
    for offset in range(7):
        day = start_date + timedelta(days=offset)
        labels.append(day.strftime("%b %d"))
        values.append(totals_by_day.get(day, 0))

    return {"labels": labels, "values": values, "color": "#6f42c1"}


def _lead_source_chart_data(leads_qs):
    palette = ["#2fb66f", "#6f42c1", "#0ea5e9", "#f59e0b", "#df5a71", "#64748b"]
    rows = (
        leads_qs.values("source")
        .annotate(total=Count("id"))
        .order_by("-total", "source")[:6]
    )
    data = []
    for idx, row in enumerate(rows):
        data.append(
            {
                "label": row["source"] or "Sin fuente",
                "value": row["total"],
                "color": palette[idx % len(palette)],
            }
        )
    if not data:
        data.append({"label": "Sin datos", "value": 0, "color": "#cbd5e1"})
    return data


def _daily_leads_chart_data(leads_qs):
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=6)

    raw_rows = (
        leads_qs.filter(created_at__date__gte=start_date)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    totals_by_day = {row["day"]: row["total"] for row in raw_rows}

    labels = []
    values = []
    for offset in range(7):
        day = start_date + timedelta(days=offset)
        labels.append(day.strftime("%b %d"))
        values.append(totals_by_day.get(day, 0))

    return {"labels": labels, "values": values, "color": "#0ea5e9"}


def _segment_lead_filter(segment: str) -> Q:
    if segment == "commercial":
        keywords = ["comercial", "commercial", "business", "empresa"]
    else:
        keywords = ["residencial", "residential", "home", "casa"]
    query = Q()
    for keyword in keywords:
        query |= Q(source__icontains=keyword)
    return query


def _segment_sale_filter(segment: str) -> Q:
    if segment == "commercial":
        keywords = ["comercial", "commercial", "business", "empresa"]
    else:
        keywords = ["residencial", "residential", "home", "casa"]
    query = Q()
    for keyword in keywords:
        query |= Q(product__name__icontains=keyword)
        query |= Q(plan__name__icontains=keyword)
        query |= Q(external_reference__icontains=keyword)
    return query


def _sales_quick_links():
    return [
        {"label": "Propuesta Solar", "url": settings.ENERGY_ADVISOR_URL, "external": True},
        {"label": "Cotizador", "url": reverse("dashboard:quoter_iframe"), "external": False},
        {"label": "Accede SUNRUN", "url": reverse("dashboard:sunrun_iframe"), "external": False},
    ]


def _solar_segment_quick_links():
    return [
        {"label": "Cliente Residencial", "url": reverse("dashboard:solar_client_residential"), "external": False},
        {"label": "Venta Residencial", "url": reverse("dashboard:solar_sale_residential"), "external": False},
        {"label": "Cliente Comercial", "url": reverse("dashboard:solar_client_commercial"), "external": False},
        {"label": "Venta Comercial", "url": reverse("dashboard:solar_sale_commercial"), "external": False},
    ]


class SalesTeamActionForm(forms.Form):
    reason = forms.CharField(
        label="Motivo",
        max_length=255,
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Detalle la razón de esta acción."}),
    )


class SalesTeamAdminRoleForm(forms.Form):
    make_admin = forms.ChoiceField(
        label="Rol de Administrador",
        choices=(("1", "Activar rol Administrador"), ("0", "Remover rol Administrador")),
        widget=forms.Select(attrs={"class": "form-select"}),
    )


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _render_entity_modal_form(request, *, form, action_url, modal_kind, title, description):
    return render_to_string(
        "dashboard/_entity_modal_form.html",
        {
            "form": form,
            "action_url": action_url,
            "modal_kind": modal_kind,
            "modal_title": title,
            "modal_description": description,
            "non_field_errors": form.non_field_errors(),
        },
        request=request,
    )


@login_required
def home(request):
    return redirect("dashboard:admin_overview")


@login_required
def admin_overview(request):
    profile = _profile(request.user)

    sales = _sales_queryset(request.user, profile, _sales_rep(request.user))
    today = timezone.localdate()
    active_announcements = Announcement.objects.filter(is_active=True, start_date__lte=today, end_date__gte=today).order_by(
        "-start_date", "-created_at"
    )
    announcement_slides = []
    for announcement in active_announcements:
        announcement_slides.append(
            {
                "announcement": announcement,
                "video_embed_url": announcement.get_video_embed_url(request)
                if announcement.media_type == Announcement.MediaType.VIDEO
                else None,
            }
        )

    context = {
        "title": "Resumen para Socio/Administrador",
        "active_announcements": active_announcements,
        "announcement_slides": announcement_slides,
        "total_sales": sales.count(),
        "confirmed_sales": sales.filter(status=Sale.Status.CONFIRMED).count(),
        "total_amount": sales.aggregate(value=Sum("amount"))["value"] or 0,
        "sales_status_chart": _status_chart_data(sales),
        "daily_sales_chart": _daily_sales_chart_data(sales),
        "recent_sales": sales[:10],
    }
    return render(request, "dashboard/admin_overview.html", context)


@login_required
def business_unit_overview(request, unit_key):
    page = BUSINESS_UNIT_PAGES_BY_KEY.get(unit_key)
    if page is None:
        return HttpResponseForbidden("Business unit page is not configured.")

    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    business_unit = BusinessUnit.objects.filter(code=page["code"]).first()

    if _is_platform_admin(request.user, profile):
        sales = Sale.objects.filter(business_unit=business_unit) if business_unit else Sale.objects.none()
    else:
        if business_unit is None:
            return HttpResponseForbidden("La unidad de negocio no esta disponible.")
        if not _can_access_business_unit(request.user, profile, sales_rep, business_unit):
            return HttpResponseForbidden("No autorizado")
        sales = Sale.objects.filter(business_unit=business_unit)
        # SalesRep users can access every unit page, but only with their own data.
        if _is_associate(profile, sales_rep):
            sales = sales.filter(sales_rep=sales_rep)

    sales = sales.select_related("sales_rep__user", "product", "plan", "business_unit")
    sales = sales.order_by("-created_at")

    business_unit_display = business_unit or SimpleNamespace(name=page["label"], code=page["code"])

    context = {
        "title": f"Unidad de Negocio: {business_unit_display.name}",
        "unit_label": page["label"],
        "business_unit": business_unit_display,
        "sales_quick_links": _sales_quick_links(),
        "total_sales": sales.count(),
        "confirmed_sales": sales.filter(status=Sale.Status.CONFIRMED).count(),
        "total_amount": sales.aggregate(value=Sum("amount"))["value"] or 0,
        "sales_status_chart": _status_chart_data(sales),
        "daily_sales_chart": _daily_sales_chart_data(sales),
        "recent_sales": sales[:10],
    }
    if page["code"] == "solar-home-power":
        context["solar_segment_links"] = _solar_segment_quick_links()
    if business_unit:
        today = timezone.localdate()
        active_offers = Offer.objects.filter(
            is_active=True,
            start_date__lte=today,
            end_date__gte=today,
            business_units=business_unit,
        ).distinct().order_by("-start_date", "-created_at")
        offer_slides = []
        for offer in active_offers:
            offer_slides.append(
                {
                    "offer": offer,
                    "video_embed_url": offer.get_video_embed_url(request) if offer.media_type == Offer.MediaType.VIDEO else None,
                }
            )
        context["offer_slides"] = offer_slides
    return render(request, "dashboard/business_unit_overview.html", context)


@login_required
def quoter_iframe(request):
    quoter_url = settings.QUOTER_URL if settings.QUOTER_URL != "#" else "https://cotizador1.hpowerco.com/"
    return render(
        request,
        "dashboard/quoter_iframe.html",
        {
            "title": "Cotizador",
            "quoter_url": quoter_url,
        },
    )


@login_required
def sunrun_iframe(request):
    sunrun_url = settings.SUNRUN_ACCESS_URL if settings.SUNRUN_ACCESS_URL != "#" else "https://s.tiled.co/2t8ayD5/landing-affiliate"
    return render(
        request,
        "dashboard/sunrun_iframe.html",
        {
            "title": "Accede SUNRUN",
            "sunrun_url": sunrun_url,
        },
    )


@login_required
def email_iframe(request):
    email_url = (
        settings.EMAIL_ACCESS_URL
        if settings.EMAIL_ACCESS_URL != "#"
        else "https://accounts.zoho.com/signin?servicename=ZohoHome&signupurl=https://www.zoho.com/signup.html"
    )
    # Zoho blocks iframe embedding; redirect directly so access works.
    return redirect(email_url)


def _solar_embed_fallback_url():
    return (
        settings.ENERGY_ADVISOR_URL
        if settings.ENERGY_ADVISOR_URL != "#"
        else "https://cotizador1.hpowerco.com/"
    )


@login_required
def solar_residential_iframe(request):
    residential_url = getattr(settings, "SOLAR_RESIDENTIAL_URL", "") or _solar_embed_fallback_url()
    return render(
        request,
        "dashboard/solar_residential_iframe.html",
        {
            "title": "Solar Residencial",
            "residential_url": residential_url,
        },
    )


@login_required
def solar_commercial_iframe(request):
    commercial_url = getattr(settings, "SOLAR_COMMERCIAL_URL", "") or _solar_embed_fallback_url()
    return render(
        request,
        "dashboard/solar_commercial_iframe.html",
        {
            "title": "Solar Comercial",
            "commercial_url": commercial_url,
        },
    )


@login_required
def solar_client_residential_iframe(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    solar_unit = BusinessUnit.objects.filter(code="solar-home-power").first()

    if not solar_unit:
        return HttpResponseForbidden("La unidad de negocio no esta disponible.")
    if not _can_access_business_unit(request.user, profile, sales_rep, solar_unit):
        return HttpResponseForbidden("No autorizado")

    leads = Lead.objects.filter(business_unit=solar_unit).select_related("sales_rep__user").order_by("-created_at")
    if _is_associate(profile, sales_rep):
        leads = leads.filter(sales_rep=sales_rep)

    total_clients = leads.count()
    with_phone = leads.exclude(phone="").count()
    with_email = leads.exclude(email="").count()
    with_contact = leads.exclude(phone="").exclude(email="").count()
    contactable_pct = round((with_contact / total_clients) * 100, 1) if total_clients else 0.0

    return render(
        request,
        "dashboard/solar_client_residential_dashboard.html",
        {
            "title": "Cliente Residencial",
            "total_clients": total_clients,
            "with_phone": with_phone,
            "with_email": with_email,
            "contactable_pct": contactable_pct,
            "lead_source_chart": _lead_source_chart_data(leads),
            "daily_leads_chart": _daily_leads_chart_data(leads),
            "recent_leads": leads[:10],
        },
    )


@login_required
def solar_sale_residential_iframe(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    solar_unit = BusinessUnit.objects.filter(code="solar-home-power").first()

    if not solar_unit:
        return HttpResponseForbidden("La unidad de negocio no esta disponible.")
    if not _can_access_business_unit(request.user, profile, sales_rep, solar_unit):
        return HttpResponseForbidden("No autorizado")

    sales = Sale.objects.filter(business_unit=solar_unit).filter(_segment_sale_filter("residential"))
    if _is_associate(profile, sales_rep):
        sales = sales.filter(sales_rep=sales_rep)
    sales = sales.select_related("sales_rep__user", "product", "plan").order_by("-created_at")

    return render(
        request,
        "dashboard/solar_sale_residential_dashboard.html",
        {
            "title": "Venta Residencial",
            "total_sales": sales.count(),
            "confirmed_sales": sales.filter(status=Sale.Status.CONFIRMED).count(),
            "total_amount": sales.aggregate(value=Sum("amount"))["value"] or 0,
            "sales_status_chart": _status_chart_data(sales),
            "daily_sales_chart": _daily_sales_chart_data(sales),
            "recent_sales": sales[:10],
        },
    )


@login_required
def solar_client_commercial_iframe(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    solar_unit = BusinessUnit.objects.filter(code="solar-home-power").first()

    if not solar_unit:
        return HttpResponseForbidden("La unidad de negocio no esta disponible.")
    if not _can_access_business_unit(request.user, profile, sales_rep, solar_unit):
        return HttpResponseForbidden("No autorizado")

    leads = Lead.objects.filter(business_unit=solar_unit).filter(_segment_lead_filter("commercial"))
    if _is_associate(profile, sales_rep):
        leads = leads.filter(sales_rep=sales_rep)
    leads = leads.select_related("sales_rep__user").order_by("-created_at")

    total_clients = leads.count()
    with_phone = leads.exclude(phone="").count()
    with_email = leads.exclude(email="").count()
    with_contact = leads.exclude(phone="").exclude(email="").count()
    contactable_pct = round((with_contact / total_clients) * 100, 1) if total_clients else 0.0

    return render(
        request,
        "dashboard/solar_client_commercial_dashboard.html",
        {
            "title": "Cliente Comercial",
            "total_clients": total_clients,
            "with_phone": with_phone,
            "with_email": with_email,
            "contactable_pct": contactable_pct,
            "lead_source_chart": _lead_source_chart_data(leads),
            "daily_leads_chart": _daily_leads_chart_data(leads),
            "recent_leads": leads[:10],
        },
    )


@login_required
def solar_sale_commercial_iframe(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    solar_unit = BusinessUnit.objects.filter(code="solar-home-power").first()

    if not solar_unit:
        return HttpResponseForbidden("La unidad de negocio no esta disponible.")
    if not _can_access_business_unit(request.user, profile, sales_rep, solar_unit):
        return HttpResponseForbidden("No autorizado")

    sales = Sale.objects.filter(business_unit=solar_unit).filter(_segment_sale_filter("commercial"))
    if _is_associate(profile, sales_rep):
        sales = sales.filter(sales_rep=sales_rep)
    sales = sales.select_related("sales_rep__user", "product", "plan").order_by("-created_at")

    return render(
        request,
        "dashboard/solar_sale_commercial_dashboard.html",
        {
            "title": "Venta Comercial",
            "total_sales": sales.count(),
            "confirmed_sales": sales.filter(status=Sale.Status.CONFIRMED).count(),
            "total_amount": sales.aggregate(value=Sum("amount"))["value"] or 0,
            "sales_status_chart": _status_chart_data(sales),
            "daily_sales_chart": _daily_sales_chart_data(sales),
            "recent_sales": sales[:10],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def associate_profile(request):
    profile = _profile(request.user)
    if profile is None:
        profile = UserProfile.objects.create(
            user=request.user,
            role=UserProfile.Role.PARTNER if request.user.is_superuser else UserProfile.Role.SOLAR_CONSULTANT,
        )
    sales_rep = _sales_rep(request.user)
    allowed_tabs = {"pane-personal", "pane-addresses", "pane-work"}
    active_tab = request.GET.get("tab", "pane-personal")
    if active_tab not in allowed_tabs:
        active_tab = "pane-personal"

    user_form = UserProfileForm(instance=request.user)
    work_form = UserWorkProfileForm(instance=profile)
    associate_form = AssociateProfileForm(instance=sales_rep, active_tab=active_tab) if sales_rep else None

    if request.method == "POST":
        posted_tab = request.POST.get("active_tab", "pane-personal")
        if posted_tab in allowed_tabs:
            active_tab = posted_tab
        user_form = UserProfileForm(request.POST, instance=request.user)
        work_form = UserWorkProfileForm(request.POST, request.FILES, instance=profile)
        if sales_rep:
            associate_form = AssociateProfileForm(
                request.POST,
                request.FILES,
                instance=sales_rep,
                active_tab=active_tab,
            )
            forms_valid = user_form.is_valid() and work_form.is_valid() and associate_form.is_valid()
        else:
            forms_valid = user_form.is_valid() and work_form.is_valid()

        if forms_valid:
            with transaction.atomic():
                user_form.save()
                work_profile = work_form.save(commit=False)
                if not work_profile.user_id:
                    work_profile.user = request.user
                work_profile.save()
                if associate_form:
                    associate_form.save()
            messages.success(request, "Perfil actualizado correctamente.")
            profile_url = reverse("dashboard:associate_profile")
            return redirect(f"{profile_url}?tab={active_tab}")

    sales = Sale.objects.filter(sales_rep=sales_rep) if sales_rep else Sale.objects.none()
    commissions = Commission.objects.filter(sales_rep=sales_rep) if sales_rep else Commission.objects.none()
    commission_allocations = CommissionAllocation.objects.filter(sales_rep=sales_rep) if sales_rep else CommissionAllocation.objects.none()
    points = RewardPoint.objects.filter(sales_rep=sales_rep) if sales_rep else RewardPoint.objects.none()
    redemptions = Redemption.objects.filter(sales_rep=sales_rep) if sales_rep else Redemption.objects.none()

    total_sales = sales.count()
    confirmed_sales = sales.filter(status=Sale.Status.CONFIRMED).count()
    total_revenue = sales.aggregate(value=Sum("amount"))["value"] or 0
    if sales_rep and commission_allocations.exists():
        total_commission = commission_allocations.aggregate(value=Sum("amount"))["value"] or 0
    else:
        total_commission = commissions.aggregate(value=Sum("commission_amount"))["value"] or 0
    total_bonus = commissions.aggregate(value=Sum("bonus_amount"))["value"] or 0
    total_points = points.aggregate(value=Sum("points"))["value"] or 0
    points_spent = redemptions.aggregate(value=Sum("points_spent"))["value"] or 0

    return render(
        request,
        "dashboard/associate_profile.html",
        {
            "sales_rep": sales_rep,
            "user_form": user_form,
            "work_form": work_form,
            "associate_form": associate_form,
            "profile_avatar_url": (
                work_form.instance.avatar.url if work_form.instance and work_form.instance.avatar else ""
            ),
            "total_sales": total_sales,
            "confirmed_sales": confirmed_sales,
            "total_revenue": total_revenue,
            "total_commission": total_commission,
            "total_bonus": total_bonus,
            "total_points": total_points,
            "points_spent": points_spent,
            "points_balance": total_points - points_spent,
            "recent_sales": sales.select_related("product", "plan").order_by("-created_at")[:8],
            "active_tab": active_tab,
        },
    )


def sales_overview(request):
    invite_token = (request.GET.get("invite") or "").strip()
    if invite_token and not request.user.is_authenticated:
        return redirect("dashboard:invitation_register", signed_token=invite_token)
    if not request.user.is_authenticated:
        login_url = reverse("login")
        return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")
    if _can_manage(request.user, _profile(request.user)):
        return redirect("dashboard:admin_overview")

    root_rep = SalesRep.objects.select_related("user", "user__profile").filter(user=request.user).first()
    if can_access_team_section(request.user) and root_rep:
        return apps_crm_salesteam_graph(request)

    storage = get_messages(request)
    swal_messages = [{"message": message.message, "tags": message.tags} for message in storage]
    graph_error_message = "No tienes permisos para acceder a Mi Equipo."
    if can_access_team_section(request.user) and not root_rep:
        graph_error_message = "Tu perfil no está configurado aún."

    context = {
        "title": "Mapa de Jerarquía",
        "subtitle": "Explora tu estructura en detalle, expande niveles y descarga el dataset para hacer análisis adicionales.",
        "last_generated": timezone.now(),
        "chart_source_url": "",
        "team_totals": {"total": 0, "direct_reports": 0, "levels": 0, "depth": 0},
        "level_breakdown": [],
        "graph_error_message": graph_error_message,
        "swal_messages": swal_messages,
    }
    return render(request, "dashboard/sales_overview.html", context)


@login_required
def sales_list(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    sales_qs = _sales_queryset(request.user, profile, sales_rep)

    paginator = Paginator(sales_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "dashboard/sales_list.html", {"page_obj": page_obj, "sales": page_obj.object_list})


@login_required
def sales_detail(request, pk):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    sale = get_object_or_404(_sales_queryset(request.user, profile, sales_rep), pk=pk)
    commission = getattr(sale, "commission", None)
    reward_point = getattr(sale, "reward_point", None)
    return render(
        request,
        "dashboard/sales_detail.html",
        {"sale": sale, "commission": commission, "reward_point": reward_point},
    )


@login_required
def points_summary(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)

    if _is_platform_admin(request.user, profile):
        points = RewardPoint.objects.select_related("sale", "sales_rep__user")
        redemptions = Redemption.objects.select_related("sales_rep__user", "prize")
    elif sales_rep:
        points = RewardPoint.objects.filter(sales_rep=sales_rep)
        redemptions = Redemption.objects.filter(sales_rep=sales_rep)
    else:
        points = RewardPoint.objects.none()
        redemptions = Redemption.objects.none()
    total_points = points.aggregate(value=Sum("points"))["value"] or 0
    points_spent = redemptions.aggregate(value=Sum("points_spent"))["value"] or 0

    return render(
        request,
        "dashboard/points_summary.html",
        {
            "points": points,
            "redemptions": redemptions,
            "total_points": total_points,
            "points_spent": points_spent,
            "balance": total_points - points_spent,
        },
    )


@login_required
def call_logs(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    is_associate = _is_associate(profile, sales_rep)

    if _can_manage(request.user, profile):
        queryset = CallLog.objects.select_related("sales_rep__user", "sale")
        if profile and is_manager_role(profile.role):
            manager_unit_ids = _manager_business_unit_ids(profile)
            if manager_unit_ids:
                queryset = queryset.filter(sales_rep__business_unit_id__in=manager_unit_ids)
            else:
                queryset = queryset.none()
    elif is_associate:
        queryset = CallLog.objects.filter(sales_rep=sales_rep).select_related("sale")
    else:
        queryset = CallLog.objects.none()

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "dashboard/call_logs.html", {"page_obj": page_obj, "call_logs": page_obj.object_list})


@login_required
@require_http_methods(["GET", "POST"])
def call_log_create(request):
    sales_rep = _sales_rep(request.user)
    if not sales_rep:
        return HttpResponseForbidden("Tu usuario no tiene perfil comercial para registrar llamadas.")

    sale_queryset = Sale.objects.filter(sales_rep=sales_rep)

    if request.method == "POST":
        form = CallLogForm(request.POST)
        form.fields["sale"].queryset = sale_queryset
        if form.is_valid():
            call_log = form.save(commit=False)
            call_log.sales_rep = sales_rep
            call_log.save()
            return redirect("dashboard:call_logs")
    else:
        form = CallLogForm()
        form.fields["sale"].queryset = sale_queryset

    return render(request, "dashboard/call_log_form.html", {"form": form})


@login_required
def financing(request):
    partner_type = request.GET.get("type", "").upper().strip()
    active_only = request.GET.get("active", "1") == "1"

    partners = FinancingPartner.objects.prefetch_related("business_units").order_by("priority", "name")
    if partner_type in FinancingPartner.PartnerType.values:
        partners = partners.filter(partner_type=partner_type)
    if active_only:
        partners = partners.filter(is_active=True)

    context = {
        "title": "Financiamiento",
        "partners": partners,
        "selected_type": partner_type,
        "active_only": active_only,
        "partner_types": FinancingPartner.PartnerType.choices,
    }
    return render(request, "dashboard/financing_list.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def associate_create(request):
    profile = _profile(request.user)
    if not _is_platform_admin(request.user, profile):
        return HttpResponseForbidden("No autorizado")

    if request.method == "POST":
        form = AssociateAccessCreateForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                selected_units = list(form.cleaned_data["business_units"])
                primary_unit = selected_units[0]
                user = User.objects.create_user(
                    username=form.cleaned_data["username"],
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                )
                user_profile = user.profile
                user_profile.role = UserProfile.Role.SOLAR_CONSULTANT
                user_profile.business_unit = primary_unit
                user_profile.save(update_fields=["role", "role_ref", "business_unit"])
                user_profile.business_units.set(selected_units)
                SalesRep.objects.create(
                    user=user,
                    business_unit=primary_unit,
                    tier=form.cleaned_data["tier"],
                )
            messages.success(request, f"Asociado creado: {user.username}")
            return redirect("dashboard:associate_create")
    else:
        form = AssociateAccessCreateForm()

    return render(request, "dashboard/associate_create.html", {"title": "Crear Asociado", "form": form})


@login_required
@require_http_methods(["GET", "POST"])
def access_management(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("No autorizado")

    create_form = AccessManagementCreateForm()
    assign_form = AccessManagementAssignForm()

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            create_form = AccessManagementCreateForm(request.POST)
            if create_form.is_valid():
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=create_form.cleaned_data["username"],
                        email=create_form.cleaned_data["email"],
                        password=create_form.cleaned_data["password"],
                        first_name=create_form.cleaned_data["first_name"],
                        last_name=create_form.cleaned_data["last_name"],
                    )
                    _apply_role_access(
                        user=user,
                        role=create_form.cleaned_data["role"],
                        business_units=create_form.cleaned_data["business_units"],
                        tier=create_form.cleaned_data["tier"],
                    )
                messages.success(request, f"Usuario creado y permisos asignados: {user.username}")
                return redirect("dashboard:access_management")
        elif action == "assign":
            assign_form = AccessManagementAssignForm(request.POST)
            if assign_form.is_valid():
                with transaction.atomic():
                    selected_user = assign_form.cleaned_data["user"]
                    _apply_role_access(
                        user=selected_user,
                        role=assign_form.cleaned_data["role"],
                        business_units=assign_form.cleaned_data["business_units"],
                        tier=assign_form.cleaned_data["tier"],
                    )
                messages.success(request, f"Permisos actualizados: {selected_user.username}")
                return redirect("dashboard:access_management")
        elif action == "delete":
            user_id = request.POST.get("user_id")
            user_to_delete = User.objects.filter(pk=user_id).first()
            if not user_to_delete:
                messages.error(request, "Usuario no encontrado.")
                return redirect("dashboard:access_management")
            if user_to_delete.pk == request.user.pk:
                messages.error(request, "No puedes eliminar tu propio usuario.")
                return redirect("dashboard:access_management")
            with transaction.atomic():
                username = user_to_delete.username
                user_to_delete.delete()
            messages.success(request, f"Usuario eliminado: {username}")
            return redirect("dashboard:access_management")

    users = User.objects.select_related("profile").order_by("username")
    return render(
        request,
        "dashboard/access_management.html",
        {"title": "Gestión de Accesos", "create_form": create_form, "assign_form": assign_form, "users": users},
    )


def _workspace_page_context(section_key):
    pages = {
        "client_management": {
            "title": "Gestión de Clientes",
            "subtitle": "Centraliza prospectos, contactos y seguimiento comercial en una sola vista.",
            "highlights": [
                "Pipeline de clientes por etapa comercial.",
                "Historial de interacción y recordatorios.",
                "Segmentación por unidad de negocio y estado.",
            ],
        },
        "my_team": {
            "title": "Mi equipo",
            "subtitle": "Visualiza desempeño, responsabilidades y carga operativa del equipo.",
            "highlights": [
                "Vista de miembros por rol y unidad.",
                "Indicadores de productividad y cumplimiento.",
                "Canal para coordinación interna.",
            ],
        },
        "associates_info": {
            "title": "Informacion de Asociados",
            "subtitle": "Consulta estatus, datos clave y seguimiento de cada asociado.",
            "highlights": [
                "Ficha operativa por asociado.",
                "Estado de actividad y contacto.",
                "Vista consolidada para seguimiento.",
            ],
        },
        "sales_hierarchy": {
            "title": "Jerarquia de Ventas",
            "subtitle": "Visualiza la estructura organizacional comercial y sus niveles.",
            "highlights": [
                "Arbol de dependencias por rol.",
                "Segmentacion por nivel y equipo.",
                "Supervision de estructura activa.",
            ],
        },
        "commission_structure": {
            "title": "Estructura de Comisiones",
            "subtitle": "Referencia central de reglas, porcentajes y criterios de pago.",
            "highlights": [
                "Politicas por nivel y producto.",
                "Condiciones de aprobacion y liquidacion.",
                "Transparencia en reglas vigentes.",
            ],
        },
        "grow_team": {
            "title": "Crece tu Equipo",
            "subtitle": "Gestiona expansion comercial con enfoque en reclutamiento y desarrollo.",
            "highlights": [
                "Lineamientos para incorporacion.",
                "Plan de crecimiento por objetivos.",
                "Seguimiento de progreso del equipo.",
            ],
        },
        "level_changes": {
            "title": "Cambios de Nivel",
            "subtitle": "Monitorea promociones y transiciones de rol dentro del equipo.",
            "highlights": [
                "Historial de cambios de nivel.",
                "Razon y fecha de actualizacion.",
                "Control y trazabilidad organizacional.",
            ],
        },
        "tasks": {
            "title": "Tareas",
            "subtitle": "Organiza pendientes críticos con enfoque en cumplimiento diario.",
            "highlights": [
                "Priorización por urgencia e impacto.",
                "Asignación de responsables y fechas objetivo.",
                "Seguimiento de tareas abiertas, en progreso y completadas.",
            ],
        },
        "tools": {
            "title": "Herramientas",
            "subtitle": "Accede rápidamente a utilidades operativas del negocio.",
            "highlights": [
                "Atajos a reportes y módulos frecuentes.",
                "Recursos internos para ventas y soporte.",
                "Utilidades para análisis y productividad.",
            ],
        },
        "legal": {
            "title": "Legales",
            "subtitle": "Consulta políticas, términos y lineamientos vigentes de la plataforma.",
            "highlights": [
                "Políticas de privacidad y manejo de datos.",
                "Términos y condiciones de uso interno.",
                "Cumplimiento y documentación regulatoria.",
            ],
        },
        "help": {
            "title": "Ayuda",
            "subtitle": "Soporte y recursos para resolver dudas operativas.",
            "highlights": [
                "Guías rápidas por módulo.",
                "Preguntas frecuentes y buenas prácticas.",
                "Canales de soporte para incidencias.",
            ],
        },
    }
    return pages[section_key]


def _scoped_sales_rep_queryset(user):
    scope = resolve_team_scope(user, all_requested=False)
    qs = SalesRep.objects.select_related("user", "business_unit", "tier")
    if not scope.can_access:
        return qs.none()
    if scope.global_scope:
        return qs
    if scope.business_unit_ids:
        return qs.filter(business_unit_id__in=scope.business_unit_ids)
    if scope.own_sales_rep_id:
        return qs.filter(id=scope.own_sales_rep_id)
    return qs.none()


def _graph_root_salesrep_for_user(user):
    own = SalesRep.objects.select_related("user", "user__profile").filter(user=user, is_active=True).first()
    if own:
        return own
    return _scoped_sales_rep_queryset(user).filter(is_active=True).order_by("id").first()


@login_required
def client_management(request):
    return render(request, "dashboard/workspace_page.html", _workspace_page_context("client_management"))


@login_required
@require_module_permission(ModuleCode.USERS, PermissionAction.VIEW)
def associates_info(request):
    scope_result = resolve_scope_profile_for_user(request.user)
    if not scope_result.allowed:
        messages.error(request, scope_result.error_message or "No tienes permisos para acceder a Mi Equipo.")
        return redirect("dashboard:home")

    team_payload = get_salesrep_profiles(scope_result.scope_profile.id, all_requested=False)
    sanitized_rows = sanitize_team_payload_for_actor(team_payload, request.user)
    summary = compute_team_personal_metrics(sanitized_rows)
    storage = get_messages(request)
    swal_messages = [{"message": message.message, "tags": message.tags} for message in storage]

    context = {
        "title": "Mi Equipo Comercial",
        "subtitle": "Informacion operativa de tu red con filtros y exportacion.",
        "team_totals": summary["team_totals"],
        "level_breakdown": summary["level_breakdown"],
        "cities": summary["cities"],
        "api_url": reverse("dashboard:salesrep_profile_api"),
        "swal_messages": swal_messages,
    }
    return render(request, "dashboard/associates_info.html", context)


@login_required
def apps_crm_sales_team_personal_info_view(request):
    return associates_info(request)


@login_required
@require_http_methods(["GET"])
def salesrep_profile_api(request):
    view_mode = (request.GET.get("view") or "").strip().lower()
    if view_mode == "salesteam":
        scope_result = resolve_sales_team_scope_profile_for_user(request.user)
        if not scope_result.allowed:
            return JsonResponse({"detail": scope_result.error_message or "No tienes permisos para acceder a Mi Equipo."}, status=403)

        level = (request.GET.get("level") or "").strip()
        parent = (request.GET.get("parent") or "").strip()
        search = (request.GET.get("search[value]") or request.GET.get("search") or "").strip()

        rows = get_sales_team_rows(scope_result.scope_profile.id, request.user, all_requested=False)
        rows = apply_sales_team_filters(rows, level=level, parent=parent, search=search)

        can_promote = can_start_salesrep_promotions(request.user)
        can_manage_admin = can_manage_operations_admin_group(request.user)
        can_request_removal = user_can_request_removal(request.user)
        visible_roles = _visible_commission_roles_for_user(request.user)
        can_view_solar_advisor = RoleCode.SOLAR_ADVISOR in visible_roles
        can_view_manager = RoleCode.MANAGER in visible_roles
        can_view_senior_manager = RoleCode.SENIOR_MANAGER in visible_roles
        can_view_elite_manager = RoleCode.ELITE_MANAGER in visible_roles
        can_view_business_manager = RoleCode.BUSINESS_MANAGER in visible_roles
        can_view_jr_partner = RoleCode.JR_PARTNER in visible_roles
        can_view_partner = RoleCode.PARTNER in visible_roles

        data = []
        viewer_profile = getattr(request.user, "profile", None)
        viewer_is_partner = bool(request.user.is_superuser or (viewer_profile and viewer_profile.role == RoleCode.PARTNER))
        viewer_username = request.user.get_username()
        viewer_display_name = request.user.get_full_name().strip() or viewer_username
        for row in rows:
            salesrep_id = row.get("salesrep_id")
            promotion_url = reverse("dashboard:salesrep_promotion_modal", args=[salesrep_id]) if can_promote else ""
            admin_role_url = reverse("dashboard:apps_crm_salesteam_admin_role", args=[salesrep_id]) if can_manage_admin else ""
            removal_url = reverse("dashboard:salesrep_removal_modal", args=[salesrep_id]) if can_request_removal else ""
            row_username = row.get("username") or ""
            visible_partner_rate = 0
            row_partner_name = (row.get("partner_name") or "").strip()
            if request.user.is_superuser:
                visible_partner_rate = row.get("partner_rate") or 0
            elif viewer_is_partner and row_partner_name and row_partner_name == viewer_display_name:
                visible_partner_rate = row.get("partner_rate") or 0
            data.append(
                {
                    "salesrep_id": salesrep_id,
                    "full_name": row.get("full_name") or "Sin dato",
                    "phone": row.get("phone") or "",
                    "username": row.get("username") or "",
                    "email": row.get("email") or "",
                    "level_name": row.get("level_name") or "Sin nivel",
                    "sort_value": row.get("sort_value") or role_sort_value(getattr(getattr(request.user, "profile", None), "role", None)),
                    "city": row.get("city") or "",
                    "parent_name": row.get("parent_name") or "",
                    "consultant_name": row.get("consultant_name") or "",
                    "teamleader_name": (row.get("teamleader_name") or "") if can_view_solar_advisor else "",
                    "manager_name": (row.get("manager_name") or "") if can_view_manager else "",
                    "executive_manager_name": (row.get("executive_manager_name") or "") if (can_view_senior_manager or can_view_elite_manager) else "",
                    "promanager_name": (row.get("promanager_name") or "") if can_view_business_manager else "",
                    "jr_partner_name": (row.get("jr_partner_name") or "") if can_view_jr_partner else "",
                    "partner_name": (row.get("partner_name") or "") if can_view_partner else "",
                    "solar_consultant_rate": row.get("solar_consultant_rate") or 0,
                    "solar_advisor_rate": (row.get("solar_advisor_rate") or 0) if can_view_solar_advisor else 0,
                    "manager_rate": (row.get("manager_rate") or 0) if can_view_manager else 0,
                    "senior_manager_rate": (row.get("senior_manager_rate") or 0) if can_view_senior_manager else 0,
                    "elite_manager_rate": (row.get("elite_manager_rate") or 0) if can_view_elite_manager else 0,
                    "business_manager_rate": (row.get("business_manager_rate") or 0) if can_view_business_manager else 0,
                    "jr_partner_rate": (row.get("jr_partner_rate") or 0) if can_view_jr_partner else 0,
                    # Política de privacidad: solo el propio Partner puede ver su porcentaje.
                    "partner_rate": visible_partner_rate if can_view_partner else 0,
                    # Política de privacidad: nadie puede ver el porcentaje del patrocinador.
                    "parent_rate": 0,
                    "promotion_url": promotion_url,
                    "admin_role_url": admin_role_url,
                    "removal_url": removal_url,
                }
            )

        return JsonResponse(
            {
                "draw": int(request.GET.get("draw", "1")),
                "recordsTotal": len(data),
                "recordsFiltered": len(data),
                "data": data,
            }
        )

    scope_result = resolve_scope_profile_for_user(request.user)
    if not scope_result.allowed:
        return JsonResponse({"detail": "No tienes permisos para acceder a Mi Equipo."}, status=403)

    draw = int(request.GET.get("draw", "1"))
    start = max(int(request.GET.get("start", "0")), 0)
    length = int(request.GET.get("length", "25"))
    if length < 0:
        length = 100000
    if length == 0:
        length = 25

    payload = get_salesrep_profiles(scope_result.scope_profile.id, all_requested=False)
    rows = sanitize_team_payload_for_actor(payload, request.user)
    records_total = len(rows)

    level = (request.GET.get("level") or "").strip()
    city = (request.GET.get("city") or "").strip()
    search = (request.GET.get("search[value]") or "").strip()
    filtered = filter_team_personal_rows(rows, level=level, city=city, search=search)
    records_filtered = len(filtered)

    page = filtered[start : start + length]
    data = [
        {
            "full_name": row.get("full_name") or "Sin dato",
            "phone": row.get("phone") or "Sin dato",
            "corporate_email": row.get("username") or "Sin dato",
            "personal_email": row.get("email") or "Sin dato",
            "level_name": row.get("level_name") or "Sin nivel",
            "city": row.get("city") or "Sin ciudad",
            "sponsor": row.get("parent_name") or "Sin patrocinador",
        }
        for row in page
    ]

    return JsonResponse(
        {
            "draw": draw,
            "recordsTotal": records_total,
            "recordsFiltered": records_filtered,
            "data": data,
        }
    )


@login_required
def sales_hierarchy(request):
    if not can_access_team_section(request.user):
        messages.error(request, "No tienes permisos para acceder a Mi Equipo.")
        return redirect("dashboard:home")

    root_rep = _graph_root_salesrep_for_user(request.user)
    if not root_rep:
        messages.error(request, "Tu perfil no está configurado aún.")
        return redirect("dashboard:home")

    graph = fetch_hierarchy_iterative(root_rep.id, request)
    summary = compute_graph_summary(graph.nodes, str(root_rep.id))
    storage = get_messages(request)
    swal_messages = [{"message": message.message, "tags": message.tags} for message in storage]
    context = {
        "title": "Mapa de Jerarquía",
        "subtitle": "Visualiza tu estructura comercial en tiempo real.",
        "team_totals": summary["team_totals"],
        "level_breakdown": summary["level_breakdown"],
        "chart_source_url": reverse("dashboard:apps_crm_salesteam_graph_source"),
        "last_generated": graph.generated_at,
        "swal_messages": swal_messages,
    }
    return render(request, "dashboard/sales_hierarchy.html", context)


@login_required
def apps_crm_salesteam_graph(request):
    return sales_hierarchy(request)


@login_required
@require_http_methods(["GET"])
def apps_crm_salesteam_graph_source(request):
    if not can_access_team_section(request.user):
        return JsonResponse({"detail": "No tienes permisos para acceder a Mi Equipo."}, status=403)

    root_rep = _graph_root_salesrep_for_user(request.user)
    if not root_rep:
        return JsonResponse({"detail": "Tu perfil no está configurado aún."}, status=403)

    graph = fetch_hierarchy_iterative(root_rep.id, request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="hierarchy.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "name",
            "imageUrl",
            "area",
            "profileUrl",
            "office",
            "tags",
            "isLoggedUser",
            "positionName",
            "id",
            "parentId",
            "size",
        ]
    )
    for node in graph.nodes:
        writer.writerow(
            [
                node["name"],
                node["imageUrl"],
                node["area"],
                node["profileUrl"],
                node["office"],
                node["tags"],
                str(node["isLoggedUser"]).lower(),
                node["positionName"],
                node["id"],
                node["parentId"] or "",
                node["size"],
            ]
        )
    return response


@login_required
def commission_structure(request):
    profile = _profile(request.user)
    if profile and profile.role == RoleCode.ADMINISTRADOR:
        messages.error(request, "No tienes permisos para acceder a Estructura de Comisiones.")
        return redirect("dashboard:sales_overview")

    scope_result = resolve_sales_team_scope_profile_for_user(request.user)
    if not scope_result.allowed or not can_access_team_section(request.user):
        messages.error(request, scope_result.error_message or "No tienes permisos para acceder a Mi Equipo.")
        return redirect("dashboard:sales_overview")

    rows = get_sales_team_rows(scope_result.scope_profile.id, request.user, all_requested=False)
    summary = compute_sales_team_summary(rows, scope_result.scope_profile)
    can_manage_admin = can_manage_operations_admin_group(request.user)
    can_promote = can_start_salesrep_promotions(request.user)
    can_request_removal = user_can_request_removal(request.user)
    can_execute_removal = user_can_execute_removal(request.user)
    visible_roles = _visible_commission_roles_for_user(request.user)

    pending_admin_invites = []
    if can_manage_admin:
        expire_pending_admin_invites()
        pending_admin_invites = list(
            OperationsAdminInviteRequest.objects.select_related("invited_user", "inviter_partner")
            .filter(inviter_partner=request.user, status=OperationsAdminInviteRequest.Status.PENDING)
            .order_by("-created_at")[:10]
        )

    storage = get_messages(request)
    swal_messages = [{"message": message.message, "tags": message.tags} for message in storage]
    commission_ladder = []
    if RoleCode.SOLAR_CONSULTANT in visible_roles:
        commission_ladder.append({"role": "Solar Consultant", "percent": 6})
    if RoleCode.SOLAR_ADVISOR in visible_roles:
        commission_ladder.append({"role": "Solar Advisor", "percent": 12})
    if RoleCode.MANAGER in visible_roles:
        commission_ladder.append({"role": "Manager", "percent": 13})
    if RoleCode.SENIOR_MANAGER in visible_roles:
        commission_ladder.append({"role": "Senior Manager", "percent": 14})
    if RoleCode.ELITE_MANAGER in visible_roles:
        commission_ladder.append({"role": "Elite Manager", "percent": 15})
    if RoleCode.BUSINESS_MANAGER in visible_roles:
        commission_ladder.append({"role": "Business Manager", "percent": 16})
    if RoleCode.JR_PARTNER in visible_roles:
        commission_ladder.append({"role": "Jr Partner", "percent": 17})
    if RoleCode.PARTNER in visible_roles:
        commission_ladder.append({"role": "Partner", "percent": 19})
    context = {
        "title": "Sales Team Management",
        "team_totals": summary["team_totals"],
        "level_breakdown": summary["level_breakdown"],
        "sponsors": summary["sponsors"],
        "cities": summary["cities"],
        "api_url": reverse("dashboard:salesrep_profile_api"),
        "can_start_salesrep_promotions": can_promote,
        "can_request_salesrep_removal": can_request_removal,
        "can_execute_salesrep_removal": can_execute_removal,
        "can_manage_admin_role": can_manage_admin,
        "show_solar_advisor": RoleCode.SOLAR_ADVISOR in visible_roles,
        "show_manager": RoleCode.MANAGER in visible_roles,
        "show_senior_manager": RoleCode.SENIOR_MANAGER in visible_roles,
        "show_elite_manager": RoleCode.ELITE_MANAGER in visible_roles,
        "show_business_manager": RoleCode.BUSINESS_MANAGER in visible_roles,
        "show_jr_partner": RoleCode.JR_PARTNER in visible_roles,
        "show_partner": RoleCode.PARTNER in visible_roles,
        "pending_admin_invites": pending_admin_invites,
        "commission_ladder": commission_ladder,
        "swal_messages": swal_messages,
    }
    return render(request, "dashboard/commission_structure.html", context)


@login_required
def apps_crm_sales_team_view(request):
    return commission_structure(request)


@login_required
@require_http_methods(["GET", "POST"])
def salesrep_promotion_modal(request, salesrep_id):
    target_rep = get_object_or_404(SalesRep.objects.select_related("user", "user__profile"), pk=salesrep_id)
    if not can_start_salesrep_promotions(request.user) or not rbac_can_manage(request.user, target_rep.user):
        return JsonResponse({"success": False, "message": "No autorizado."}, status=403)
    if request.user.pk == target_rep.user_id:
        return JsonResponse({"success": False, "message": "No puedes ejecutar acciones sobre tu propio usuario."}, status=400)

    form = SalesTeamActionForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            return JsonResponse({"success": True, "message": "Solicitud de promoción registrada correctamente."})
        html = _render_entity_modal_form(
            request,
            form=form,
            action_url=reverse("dashboard:salesrep_promotion_modal", args=[salesrep_id]),
            modal_kind="promotion",
            title="Promover asociado",
            description="Registra la razón de la promoción y confirma.",
        )
        return JsonResponse({"success": False, "html": html, "message": "Formulario inválido."}, status=400)

    html = _render_entity_modal_form(
        request,
        form=form,
        action_url=reverse("dashboard:salesrep_promotion_modal", args=[salesrep_id]),
        modal_kind="promotion",
        title="Promover asociado",
        description="Registra la razón de la promoción y confirma.",
    )
    if _is_ajax(request):
        return JsonResponse({"success": False, "message": "Método inválido."}, status=405) if request.method != "GET" else render(
            request,
            "dashboard/_entity_modal_form.html",
            {
                "form": form,
                "action_url": reverse("dashboard:salesrep_promotion_modal", args=[salesrep_id]),
                "modal_kind": "promotion",
                "modal_title": "Promover asociado",
                "modal_description": "Registra la razón de la promoción y confirma.",
            },
        )
    return redirect("dashboard:commission_structure")


@login_required
@require_http_methods(["GET", "POST"])
def salesrep_removal_modal(request, salesrep_id):
    target_rep = get_object_or_404(SalesRep.objects.select_related("user", "user__profile"), pk=salesrep_id)
    if not user_can_request_removal(request.user) or not rbac_can_manage(request.user, target_rep.user):
        return JsonResponse({"success": False, "message": "No autorizado."}, status=403)
    if request.user.pk == target_rep.user_id:
        return JsonResponse({"success": False, "message": "No puedes ejecutar acciones sobre tu propio usuario."}, status=400)

    form = SalesTeamActionForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            return JsonResponse({"success": True, "message": "Solicitud de eliminación registrada correctamente."})
        html = _render_entity_modal_form(
            request,
            form=form,
            action_url=reverse("dashboard:salesrep_removal_modal", args=[salesrep_id]),
            modal_kind="removal",
            title="Solicitar eliminación",
            description="Indica el motivo de la solicitud de eliminación.",
        )
        return JsonResponse({"success": False, "html": html, "message": "Formulario inválido."}, status=400)

    html = _render_entity_modal_form(
        request,
        form=form,
        action_url=reverse("dashboard:salesrep_removal_modal", args=[salesrep_id]),
        modal_kind="removal",
        title="Solicitar eliminación",
        description="Indica el motivo de la solicitud de eliminación.",
    )
    if _is_ajax(request):
        return JsonResponse({"success": False, "message": "Método inválido."}, status=405) if request.method != "GET" else render(
            request,
            "dashboard/_entity_modal_form.html",
            {
                "form": form,
                "action_url": reverse("dashboard:salesrep_removal_modal", args=[salesrep_id]),
                "modal_kind": "removal",
                "modal_title": "Solicitar eliminación",
                "modal_description": "Indica el motivo de la solicitud de eliminación.",
            },
        )
    return redirect("dashboard:commission_structure")


@login_required
@require_http_methods(["GET", "POST"])
def apps_crm_salesteam_admin_role(request, salesrep_id):
    if not can_manage_operations_admin_group(request.user):
        return JsonResponse({"success": False, "message": "No autorizado."}, status=403)

    target_rep = get_object_or_404(SalesRep.objects.select_related("user", "user__profile"), pk=salesrep_id)
    if request.user.pk == target_rep.user_id:
        return JsonResponse({"success": False, "message": "No puedes gestionarte a ti mismo."}, status=400)
    if not rbac_can_manage(request.user, target_rep.user):
        return JsonResponse({"success": False, "message": "El usuario no está dentro de tu árbol gestionable."}, status=403)

    form = SalesTeamAdminRoleForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            make_admin = form.cleaned_data["make_admin"] == "1"
            group, _ = Group.objects.get_or_create(name="Administrador")
            target_user = target_rep.user
            target_profile = target_user.profile
            if make_admin:
                target_user.groups.add(group)
                target_profile.role = RoleCode.ADMINISTRADOR
                target_profile.manager = request.user
                target_profile.save(update_fields=["role", "role_ref", "manager"])
                message = "Rol Administrador asignado correctamente."
            else:
                target_user.groups.remove(group)
                if target_profile.role == RoleCode.ADMINISTRADOR:
                    target_profile.role = RoleCode.SOLAR_CONSULTANT
                    target_profile.save(update_fields=["role", "role_ref"])
                message = "Rol Administrador removido correctamente."

            if _is_ajax(request):
                return JsonResponse({"success": True, "message": message})
            messages.success(request, message)
            return redirect("dashboard:commission_structure")

        html = _render_entity_modal_form(
            request,
            form=form,
            action_url=reverse("dashboard:apps_crm_salesteam_admin_role", args=[salesrep_id]),
            modal_kind="admin-role",
            title="Gestionar Rol Administrador",
            description="Activa o remueve el rol operativo de administrador para este asociado.",
        )
        return JsonResponse({"success": False, "html": html, "message": "Formulario inválido."}, status=400)

    html = _render_entity_modal_form(
        request,
        form=form,
        action_url=reverse("dashboard:apps_crm_salesteam_admin_role", args=[salesrep_id]),
        modal_kind="admin-role",
        title="Gestionar Rol Administrador",
        description="Activa o remueve el rol operativo de administrador para este asociado.",
    )
    if _is_ajax(request):
        return render(request, "dashboard/_entity_modal_form.html", {"form": form, "action_url": reverse("dashboard:apps_crm_salesteam_admin_role", args=[salesrep_id]), "modal_kind": "admin-role", "modal_title": "Gestionar Rol Administrador", "modal_description": "Activa o remueve el rol operativo de administrador para este asociado."})
    return redirect("dashboard:commission_structure")


@login_required
@require_http_methods(["POST"])
def apps_crm_salesteam_admin_invite_action(request, request_id):
    if not can_manage_operations_admin_group(request.user):
        return JsonResponse({"success": False, "message": "No autorizado."}, status=403)

    invite = get_object_or_404(
        OperationsAdminInviteRequest.objects.select_related("invited_user", "inviter_partner", "invited_user__profile"),
        pk=request_id,
    )
    if not (request.user.is_superuser or invite.inviter_partner_id == request.user.id):
        return JsonResponse({"success": False, "message": "No puedes gestionar esta solicitud."}, status=403)
    if invite.status != OperationsAdminInviteRequest.Status.PENDING:
        return JsonResponse({"success": False, "message": "Solo se pueden procesar solicitudes pendientes."}, status=400)

    action = (request.POST.get("action") or "").strip().lower()
    if action not in {"approve", "reject"}:
        return JsonResponse({"success": False, "message": "Acción inválida."}, status=400)

    approved = action == "approve"
    set_admin_invite_decision(invite=invite, actor=request.user, approved=approved)

    group, _ = Group.objects.get_or_create(name="Administrador")
    invited_user = invite.invited_user
    invited_profile = invited_user.profile
    if approved:
        invited_user.groups.add(group)
        invited_profile.role = RoleCode.ADMINISTRADOR
        invited_profile.manager = invite.inviter_partner
        invited_profile.save(update_fields=["role", "role_ref", "manager"])
        message = "Solicitud aprobada y rol Administrador asignado."
    else:
        invited_user.groups.remove(group)
        if invited_profile.role == RoleCode.ADMINISTRADOR:
            invited_profile.role = RoleCode.SOLAR_CONSULTANT
            invited_profile.save(update_fields=["role", "role_ref"])
        message = "Solicitud rechazada."

    return JsonResponse({"success": True, "message": message})


@login_required
@require_module_permission(ModuleCode.USERS, PermissionAction.VIEW)
def grow_team(request):
    profile = _profile(request.user)
    level = (request.GET.get("level") or UserProfile.Role.SOLAR_CONSULTANT).strip()
    valid_levels = [code for code, _ in UserProfile.Role.choices]
    if level not in valid_levels:
        level = UserProfile.Role.SOLAR_CONSULTANT

    level_obj = Role.objects.filter(code=level).order_by("id").first() or Role.objects.order_by("priority", "id").first()
    signer = signing.TimestampSigner(salt=GROW_TEAM_SIGNER_SALT)
    token_payload = f"{request.user.id}:{level}"
    signed_token = signer.sign(token_payload)
    if level_obj:
        invite_link = request.build_absolute_uri(reverse("dashboard:signup_invited", args=[request.user.id, level_obj.id]))
    else:
        invite_link = request.build_absolute_uri(reverse("dashboard:invitation_register", args=[signed_token]))
    qr_query = urlencode({"text": invite_link, "size": "360"})
    qr_image_url = f"https://quickchart.io/qr?{qr_query}"

    inviter_role_label = "Modo Superadmin" if request.user.is_superuser else (profile.get_role_display() if profile else "Usuario")
    context = {
        "title": "Crece tu Equipo",
        "subtitle": "Invitacion de consultores",
        "level_choices": UserProfile.Role.choices,
        "selected_level": level,
        "invite_link": invite_link,
        "signed_token": signed_token,
        "qr_image_url": qr_image_url,
        "inviter_role_label": inviter_role_label,
        "now": timezone.now(),
    }
    return render(request, "dashboard/grow_team.html", context)


@require_http_methods(["GET", "POST"])
def invitation_register(request, signed_token):
    if request.user.is_authenticated:
        messages.info(request, "Ya tienes una sesión activa. Cierra sesión para registrar otra cuenta.")
        return redirect("dashboard:home")

    inviter, invited_level, token_error = _decode_grow_team_token(signed_token)
    invited_level_label = dict(UserProfile.Role.choices).get(invited_level, "Asociado")
    inviter_name = inviter.get_full_name().strip() if inviter else ""
    if inviter and not inviter_name:
        inviter_name = inviter.get_username()

    form = InvitationSignupForm(request.POST or None)
    if request.method == "POST" and not token_error and form.is_valid():
        invited_units = _resolve_business_units_for_inviter(inviter)
        if invited_level in ROLES_REQUIRING_BUSINESS_UNITS and not invited_units:
            form.add_error(None, "No se pudo determinar una unidad de negocio para esta invitación.")
        else:
            email = form.cleaned_data["email"].strip().lower()
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=form.cleaned_data["password1"],
                    first_name=form.cleaned_data["first_name"].strip(),
                    last_name=form.cleaned_data["last_name"].strip(),
                )

                _apply_role_access(
                    user=user,
                    role=invited_level,
                    business_units=invited_units,
                    tier=Tier.objects.order_by("rank", "name").first(),
                )

                profile = user.profile
                profile.manager = inviter
                profile.save(update_fields=["manager"])

                if is_consultant_role(invited_level):
                    sales_rep = _sales_rep(user)
                    if sales_rep:
                        sales_rep.second_last_name = form.cleaned_data["second_last_name"].strip()
                        inviter_sales_rep = _sales_rep(inviter)
                        if inviter_sales_rep and not sales_rep.parent_id:
                            sales_rep.parent = inviter_sales_rep
                        sales_rep.save(update_fields=["second_last_name", "parent"] if sales_rep.parent_id else ["second_last_name"])

            messages.success(request, "Cuenta creada correctamente. Ya puedes iniciar sesión.")
            return redirect("login")

    context = {
        "title": "Crear nueva cuenta",
        "form": form,
        "inviter_name": inviter_name,
        "invited_level_label": invited_level_label,
        "token_error": token_error,
        "password_rules": password_validation.password_validators_help_texts(),
    }
    return render(request, "registration/invitation_register.html", context)


@login_required
@require_module_permission(ModuleCode.USERS, PermissionAction.VIEW)
def level_changes(request):
    profile = _profile(request.user)
    can_view_level_changes = bool(request.user.is_superuser or (profile and profile.role == RoleCode.PARTNER))
    if not can_view_level_changes:
        return HttpResponseForbidden("No autorizado")

    audits = RoleChangeAudit.objects.select_related("actor", "target")
    reps = _scoped_sales_rep_queryset(request.user)
    scoped_user_ids = set(reps.values_list("user_id", flat=True))
    if not (request.user.is_superuser or is_platform_admin(request.user)):
        if scoped_user_ids:
            audits = audits.filter(target_id__in=scoped_user_ids)
        else:
            audits = audits.none()

    context = {
        "title": "Cambios de Nivel",
        "subtitle": "Historial auditado de cambios de rol en la estructura comercial.",
        "changes": audits.order_by("-created_at")[:200],
        "total_changes": audits.count(),
    }
    return render(request, "dashboard/level_changes.html", context)


@login_required
def my_team(request):
    profile = _profile(request.user)
    all_requested = (request.GET.get("all") or "").lower() in {"1", "true", "yes"}
    scope = resolve_my_team_scope(request.user, all_requested=all_requested)
    if not scope.can_access:
        return HttpResponseForbidden("No autorizado")

    summary = get_team_dashboard_context(user=request.user, all_requested=all_requested, scope=scope)
    storage = get_messages(request)
    swal_messages = [
        {
            "message": message.message,
            "tags": message.tags,
        }
        for message in storage
    ]

    context = {
        "title": "Equipo Personal",
        "subtitle": "Seguimiento operativo del equipo con filtros, exportación y métricas en tiempo real.",
        "kpis": summary["kpis"],
        "cities": summary["cities"],
        "api_url": reverse("dashboard:my_team_data_api"),
        "swal_messages": swal_messages,
        "can_view_commission_structure": not (profile and profile.role == RoleCode.ADMINISTRADOR),
        "can_view_level_changes": bool(request.user.is_superuser or (profile and profile.role == RoleCode.PARTNER)),
    }
    return render(request, "dashboard/my_team.html", context)


@login_required
@require_http_methods(["GET"])
def my_team_data_api(request):
    draw = int(request.GET.get("draw", "1"))
    start = max(int(request.GET.get("start", "0")), 0)
    length = int(request.GET.get("length", "10"))
    if length <= 0:
        length = 10
    if length > 200:
        length = 200

    all_requested = (request.GET.get("all") or "").lower() in {"1", "true", "yes"}
    scope = resolve_my_team_scope(request.user, all_requested=all_requested)
    if all_requested and not scope.can_view_all:
        return JsonResponse({"detail": "No autorizado para all=True."}, status=403)
    if not scope.can_access:
        return JsonResponse({"detail": "No autorizado."}, status=403)

    level = (request.GET.get("level") or "").strip()
    city = (request.GET.get("city") or "").strip()
    search = (request.GET.get("search[value]") or "").strip()
    order_idx = request.GET.get("order[0][column]", "0")
    order_dir = (request.GET.get("order[0][dir]") or "asc").lower()

    columns = {
        "0": "full_name",
        "1": "username",
        "2": "level",
        "3": "city",
        "4": "business_unit",
        "5": "contactability",
        "6": "status",
        "7": "phone",
        "8": "email",
        "9": "hire_date",
    }
    order_column = columns.get(order_idx, "full_name")

    payload = query_team_rows(
        user=request.user,
        all_requested=all_requested,
        scope=scope,
        level=level,
        city=city,
        search=search,
        order_column=order_column,
        order_dir=order_dir,
        start=start,
        length=length,
    )

    rows = [
        TeamMemberSerializer.serialize(
            row,
            scope=payload["scope"],
            viewer_sales_rep_id=payload["scope"].own_sales_rep_id,
        )
        for row in payload["rows"]
    ]

    return JsonResponse(
        {
            "draw": draw,
            "recordsTotal": payload["records_total"],
            "recordsFiltered": payload["records_filtered"],
            "data": rows,
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def tasks(request):
    event_form = CalendarEventForm(prefix="event")
    task_form = TaskForm(prefix="task")
    appointment_form = AppointmentForm(prefix="appointment")
    selected_panel = request.GET.get("panel", "event")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_event":
            selected_panel = "event"
            event_form = CalendarEventForm(request.POST, prefix="event")
            if event_form.is_valid():
                item = event_form.save(commit=False)
                item.owner = request.user
                item.kind = CalendarEvent.EventKind.EVENT
                item.save()
                messages.success(request, "Evento creado correctamente.")
                return redirect("dashboard:tasks")
        elif action == "create_task":
            selected_panel = "task"
            task_form = TaskForm(request.POST, prefix="task")
            if task_form.is_valid():
                item = task_form.save(commit=False)
                item.owner = request.user
                item.save()
                messages.success(request, "Tarea creada correctamente.")
                return redirect("dashboard:tasks")
        elif action == "create_appointment":
            selected_panel = "appointment"
            appointment_form = AppointmentForm(request.POST, prefix="appointment")
            if appointment_form.is_valid():
                item = appointment_form.save(commit=False)
                item.owner = request.user
                item.save()
                CalendarEvent.objects.create(
                    owner=request.user,
                    title=f"Cita: {item.subject}",
                    description=item.notes,
                    start_at=item.start_at,
                    end_at=item.end_at,
                    all_day=False,
                    color="#0b8043",
                    kind=CalendarEvent.EventKind.APPOINTMENT,
                )
                messages.success(request, "Cita agendada correctamente.")
                return redirect("dashboard:tasks")

    task_items = Task.objects.filter(owner=request.user).order_by("due_at")[:12]
    appointments = Appointment.objects.filter(owner=request.user).order_by("start_at")[:8]

    context = {
        "title": "Calendario de Trabajo",
        "subtitle": "Vista de calendario profesional para eventos, tareas y agendas de citas.",
        "event_form": event_form,
        "task_form": task_form,
        "appointment_form": appointment_form,
        "selected_panel": selected_panel,
        "task_items": task_items,
        "appointments": appointments,
    }
    return render(request, "dashboard/tasks_calendar.html", context)


@login_required
def tasks_calendar_feed(request):
    events = []
    user = request.user

    calendar_events = CalendarEvent.objects.filter(owner=user).only(
        "id", "title", "start_at", "end_at", "all_day", "color", "kind"
    )
    task_items = Task.objects.filter(owner=user).exclude(status=Task.Status.DONE).only("id", "title", "due_at", "priority")

    for event in calendar_events:
        events.append(
            {
                "id": f"event-{event.id}",
                "title": event.title,
                "start": timezone.localtime(event.start_at).isoformat(),
                "end": timezone.localtime(event.end_at).isoformat(),
                "allDay": event.all_day,
                "backgroundColor": event.color,
                "borderColor": event.color,
                "extendedProps": {"kind": event.kind},
            }
        )

    for item in task_items:
        priority_color = {
            Task.Priority.HIGH: "#d93025",
            Task.Priority.MEDIUM: "#f9ab00",
            Task.Priority.LOW: "#1e8e3e",
        }.get(item.priority, "#5f6368")
        due = timezone.localtime(item.due_at)
        events.append(
            {
                "id": f"task-{item.id}",
                "title": f"Tarea: {item.title}",
                "start": due.isoformat(),
                "end": (due + timedelta(minutes=30)).isoformat(),
                "allDay": False,
                "backgroundColor": priority_color,
                "borderColor": priority_color,
                "extendedProps": {"kind": "task", "priority": item.priority},
            }
        )

    return JsonResponse(events, safe=False)


@login_required
@require_http_methods(["POST"])
def task_update_status(request, pk):
    item = get_object_or_404(Task, pk=pk, owner=request.user)
    next_status = request.POST.get("status", Task.Status.TODO)
    if next_status not in Task.Status.values:
        next_status = Task.Status.TODO
    item.set_status(next_status)
    item.save(update_fields=["status", "completed_at"])
    messages.success(request, "Estado de tarea actualizado.")
    return redirect("dashboard:tasks")


@login_required
@require_http_methods(["POST"])
def appointment_update_status(request, pk):
    item = get_object_or_404(Appointment, pk=pk, owner=request.user)
    next_status = request.POST.get("status", Appointment.Status.SCHEDULED)
    if next_status not in Appointment.Status.values:
        next_status = Appointment.Status.SCHEDULED
    item.status = next_status
    item.save(update_fields=["status"])
    messages.success(request, "Estado de cita actualizado.")
    return redirect("dashboard:tasks")


@login_required
def tools(request):
    form = SharedResourceForm(prefix="resource")
    announcement_form = AnnouncementForm(prefix="announcement")
    offer_form = OfferForm(prefix="offer")
    can_manage_announcements = _can_manage(request.user, _profile(request.user))

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_resource":
            form = SharedResourceForm(request.POST, request.FILES, prefix="resource")
            if form.is_valid():
                resource = form.save(commit=False)
                resource.created_by = request.user
                resource.save()
                tags = form.get_tags()
                resource.tags.set(tags)
                messages.success(request, "Recurso publicado correctamente.")
                return redirect("dashboard:tools")
        elif action == "create_announcement":
            if not can_manage_announcements:
                return HttpResponseForbidden("No autorizado para crear anuncios.")
            announcement_form = AnnouncementForm(request.POST, request.FILES, prefix="announcement")
            if announcement_form.is_valid():
                announcement = announcement_form.save(commit=False)
                announcement.created_by = request.user
                announcement.save()
                messages.success(request, "Anuncio publicado correctamente.")
                return redirect("dashboard:tools")
        elif action == "update_announcement":
            if not can_manage_announcements:
                return HttpResponseForbidden("No autorizado para editar anuncios.")
            announcement_id = request.POST.get("announcement_id")
            announcement = get_object_or_404(Announcement, pk=announcement_id)
            edit_form = AnnouncementForm(request.POST, request.FILES, prefix="announcement", instance=announcement)
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, "Anuncio actualizado correctamente.")
            else:
                messages.error(request, f"No se pudo actualizar el anuncio: {edit_form.errors.as_text()}")
            return redirect("dashboard:tools")
        elif action == "delete_announcement":
            if not can_manage_announcements:
                return HttpResponseForbidden("No autorizado para eliminar anuncios.")
            announcement_id = request.POST.get("announcement_id")
            announcement = Announcement.objects.filter(pk=announcement_id).first()
            if not announcement:
                messages.error(request, "El anuncio no existe o ya fue eliminado.")
            else:
                announcement.delete()
                messages.success(request, "Anuncio eliminado correctamente.")
            return redirect("dashboard:tools")
        elif action == "create_offer":
            if not can_manage_announcements:
                return HttpResponseForbidden("No autorizado para crear ofertas.")
            offer_form = OfferForm(request.POST, request.FILES, prefix="offer")
            if offer_form.is_valid():
                offer = offer_form.save(commit=False)
                offer.created_by = request.user
                offer.save()
                offer_form.save_m2m()
                messages.success(request, "Oferta publicada correctamente.")
                return redirect("dashboard:tools")
        elif action == "update_offer":
            if not can_manage_announcements:
                return HttpResponseForbidden("No autorizado para editar ofertas.")
            offer_id = request.POST.get("offer_id")
            offer = get_object_or_404(Offer, pk=offer_id)
            edit_form = OfferForm(request.POST, request.FILES, prefix="offer", instance=offer)
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, "Oferta actualizada correctamente.")
            else:
                messages.error(request, f"No se pudo actualizar la oferta: {edit_form.errors.as_text()}")
            return redirect("dashboard:tools")
        elif action == "delete_offer":
            if not can_manage_announcements:
                return HttpResponseForbidden("No autorizado para eliminar ofertas.")
            offer_id = request.POST.get("offer_id")
            offer = Offer.objects.filter(pk=offer_id).first()
            if not offer:
                messages.error(request, "La oferta no existe o ya fue eliminada.")
            else:
                offer.delete()
                messages.success(request, "Oferta eliminada correctamente.")
            return redirect("dashboard:tools")

    query = (request.GET.get("q") or "").strip()
    selected_tag = (request.GET.get("tag") or "").strip().lower()
    sort = request.GET.get("sort") or "-created_at"
    valid_sorts = {
        "title": "title",
        "-title": "-title",
        "provider": "provider",
        "-provider": "-provider",
        "resource_type": "resource_type",
        "-resource_type": "-resource_type",
        "created_at": "created_at",
        "-created_at": "-created_at",
    }
    sort_by = valid_sorts.get(sort, "-created_at")

    resources_qs = SharedResource.objects.select_related("created_by").prefetch_related("tags").all()
    if query:
        resources_qs = resources_qs.filter(
            Q(title__icontains=query) | Q(provider__icontains=query) | Q(description__icontains=query) | Q(tags__name__icontains=query)
        ).distinct()
    if selected_tag:
        resources_qs = resources_qs.filter(tags__name=selected_tag)

    resources_qs = resources_qs.order_by(sort_by)
    paginator = Paginator(resources_qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = _workspace_page_context("tools")
    context.update(
        {
            "resource_form": form,
            "announcement_form": announcement_form,
            "offer_form": offer_form,
            "can_manage_announcements": can_manage_announcements,
            "announcements": Announcement.objects.select_related("created_by").order_by("-start_date", "-created_at")[:10],
            "offers": Offer.objects.select_related("created_by").prefetch_related("business_units").order_by("-start_date", "-created_at")[:10],
            "active_business_units": BusinessUnit.objects.filter(is_active=True).order_by("name"),
            "resources": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "selected_tag": selected_tag,
            "available_tags": ResourceTag.objects.filter(resources__isnull=False).distinct(),
            "sort": sort_by,
            "total_resources": SharedResource.objects.count(),
            "file_resources": SharedResource.objects.filter(resource_type=SharedResource.ResourceType.FILE).count(),
            "active_resources": SharedResource.objects.filter(is_active=True).count(),
            "total_tags_used": ResourceTag.objects.filter(resources__isnull=False).distinct().count(),
        }
    )
    return render(request, "dashboard/tools.html", context)


@login_required
def tools_resource_present(request, pk):
    host = request.get_host().split(":")[0].lower()
    if host in {"127.0.0.1", "0.0.0.0"}:
        port = request.get_port()
        target = f"{request.scheme}://localhost:{port}{request.path}"
        if request.GET:
            target = f"{target}?{urlencode(request.GET, doseq=True)}"
        return redirect(target)

    resource = get_object_or_404(SharedResource.objects.select_related("created_by").prefetch_related("tags"), pk=pk)
    previous_resource = SharedResource.objects.filter(pk__lt=resource.pk).order_by("-pk").only("pk", "title").first()
    next_resource = SharedResource.objects.filter(pk__gt=resource.pk).order_by("pk").only("pk", "title").first()
    embed_url = resource.get_embed_url(request)
    original_url = resource.file.url if resource.file else resource.video_url

    return render(
        request,
        "dashboard/tools_present.html",
        {
            "title": "Presentacion de recurso",
            "resource": resource,
            "embed_url": embed_url,
            "original_url": original_url,
            "previous_resource": previous_resource,
            "next_resource": next_resource,
        },
    )


@login_required
def legal(request):
    return render(request, "dashboard/workspace_page.html", _workspace_page_context("legal"))


@login_required
def help_center(request):
    return render(request, "dashboard/workspace_page.html", _workspace_page_context("help"))

