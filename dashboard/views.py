from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.db.models import Q
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import BusinessUnit
from core.models import UserProfile
from crm.models import CallLog, Sale, SalesRep
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
from dashboard.forms import OfferForm
from dashboard.forms import SharedResourceForm
from dashboard.forms import TaskForm
from dashboard.forms import UserWorkProfileForm
from dashboard.forms import UserProfileForm
from dashboard.models import Appointment
from dashboard.models import Announcement
from dashboard.models import CalendarEvent
from dashboard.models import Offer
from dashboard.models import ResourceTag
from dashboard.models import SharedResource
from dashboard.models import Task
from finance.models import Commission
from finance.models import FinancingPartner
from rewards.models import Redemption, RewardPoint

User = get_user_model()


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


def _sales_rep(user):
    return SalesRep.objects.filter(user=user).select_related("tier", "business_unit").first()


def _is_superadmin(user):
    return bool(user and user.is_superuser)


def _is_platform_admin(user, profile):
    return bool(_is_superadmin(user) or (profile and profile.role == UserProfile.Role.ADMIN))


def _is_associate(profile, sales_rep):
    return bool(profile and profile.role == UserProfile.Role.SALES_REP and sales_rep)


def _manager_business_unit_ids(profile):
    if not profile or profile.role != UserProfile.Role.MANAGER:
        return []
    ids = list(profile.business_units.values_list("id", flat=True))
    if not ids and profile.business_unit_id:
        ids = [profile.business_unit_id]
    return ids


def _associate_business_unit_ids(profile, sales_rep):
    if not profile or profile.role != UserProfile.Role.SALES_REP:
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
    profile.business_unit = (
        primary_business_unit if role in {UserProfile.Role.ADMIN, UserProfile.Role.MANAGER, UserProfile.Role.SALES_REP} else None
    )
    profile.save(update_fields=["role", "business_unit"])
    profile.business_units.set(
        selected_units if role in {UserProfile.Role.ADMIN, UserProfile.Role.MANAGER, UserProfile.Role.SALES_REP} else []
    )

    if role == UserProfile.Role.SALES_REP:
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
    return bool(profile and profile.role == UserProfile.Role.MANAGER)


def _sales_queryset(user, profile, sales_rep):
    qs = Sale.objects.select_related("sales_rep__user", "product", "plan", "business_unit")
    if _is_platform_admin(user, profile):
        return qs
    if profile and profile.role == UserProfile.Role.MANAGER:
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
    if profile and profile.role == UserProfile.Role.MANAGER:
        return business_unit.id in _manager_business_unit_ids(profile)
    if _is_associate(profile, sales_rep):
        return business_unit.id in _associate_business_unit_ids(profile, sales_rep)
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


def _sales_quick_links():
    email_url = (
        settings.EMAIL_ACCESS_URL
        if settings.EMAIL_ACCESS_URL != "#"
        else "https://accounts.zoho.com/signin?servicename=ZohoHome&signupurl=https://www.zoho.com/signup.html"
    )
    return [
        {"label": "Asesor Energetico", "url": settings.ENERGY_ADVISOR_URL, "external": True},
        {"label": "Cotizador", "url": reverse("dashboard:quoter_iframe"), "external": False},
        {"label": "Accede SUNRUN", "url": reverse("dashboard:sunrun_iframe"), "external": False},
        {"label": "Accede a tu Correo", "url": email_url, "external": True},
    ]


@login_required
def home(request):
    profile = _profile(request.user)
    if _can_manage(request.user, profile):
        return redirect("dashboard:admin_overview")
    return redirect("dashboard:sales_overview")


@login_required
def admin_overview(request):
    profile = _profile(request.user)
    if not _can_manage(request.user, profile):
        return HttpResponseForbidden("No autorizado")

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


@login_required
@require_http_methods(["GET", "POST"])
def associate_profile(request):
    profile = _profile(request.user)
    if profile is None:
        profile = UserProfile.objects.create(
            user=request.user,
            role=UserProfile.Role.ADMIN if request.user.is_superuser else UserProfile.Role.SALES_REP,
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
    points = RewardPoint.objects.filter(sales_rep=sales_rep) if sales_rep else RewardPoint.objects.none()
    redemptions = Redemption.objects.filter(sales_rep=sales_rep) if sales_rep else Redemption.objects.none()

    total_sales = sales.count()
    confirmed_sales = sales.filter(status=Sale.Status.CONFIRMED).count()
    total_revenue = sales.aggregate(value=Sum("amount"))["value"] or 0
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


@login_required
def sales_overview(request):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    is_associate = _is_associate(profile, sales_rep)
    sales = _sales_queryset(request.user, profile, sales_rep)

    points_qs = RewardPoint.objects.filter(sales_rep=sales_rep) if is_associate else RewardPoint.objects.none()
    redemption_qs = Redemption.objects.filter(sales_rep=sales_rep) if is_associate else Redemption.objects.none()

    context = {
        "title": "Panel de Ventas",
        "sales_rep": sales_rep,
        "total_sales": sales.count(),
        "confirmed_sales": sales.filter(status=Sale.Status.CONFIRMED).count(),
        "total_amount": sales.aggregate(value=Sum("amount"))["value"] or 0,
        "total_points": points_qs.aggregate(value=Sum("points"))["value"] or 0,
        "points_spent": redemption_qs.aggregate(value=Sum("points_spent"))["value"] or 0,
        "sales_status_chart": _status_chart_data(sales),
        "daily_sales_chart": _daily_sales_chart_data(sales),
        "recent_sales": sales[:10],
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
    is_associate = _is_associate(profile, sales_rep)
    if not _is_platform_admin(request.user, profile) and not is_associate:
        return HttpResponseForbidden("Solo los asociados pueden ver puntos.")

    if _is_platform_admin(request.user, profile):
        points = RewardPoint.objects.select_related("sale", "sales_rep__user")
        redemptions = Redemption.objects.select_related("sales_rep__user", "prize")
    else:
        points = RewardPoint.objects.filter(sales_rep=sales_rep)
        redemptions = Redemption.objects.filter(sales_rep=sales_rep)
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
        if profile and profile.role == UserProfile.Role.MANAGER:
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
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    if not _is_associate(profile, sales_rep):
        return HttpResponseForbidden("Solo los asociados pueden registrar llamadas.")

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
                user_profile.role = UserProfile.Role.SALES_REP
                user_profile.business_unit = primary_unit
                user_profile.save(update_fields=["role", "business_unit"])
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


@login_required
def client_management(request):
    return render(request, "dashboard/workspace_page.html", _workspace_page_context("client_management"))


@login_required
def my_team(request):
    return render(request, "dashboard/workspace_page.html", _workspace_page_context("my_team"))


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
    item.save(update_fields=["status", "completed_at", "updated_at"])
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
    item.save(update_fields=["status", "updated_at"])
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
