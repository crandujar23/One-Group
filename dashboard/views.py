from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.models import BusinessUnit
from core.models import UserProfile
from crm.models import CallLog, Sale, SalesRep
from dashboard.business_units import BUSINESS_UNIT_PAGES_BY_KEY
from dashboard.forms import AssociateProfileForm
from dashboard.forms import CallLogForm
from dashboard.forms import LoginForm
from dashboard.forms import UserProfileForm
from finance.models import Commission
from rewards.models import Redemption, RewardPoint


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


def _can_manage(profile):
    return profile and profile.role in [UserProfile.Role.ADMIN, UserProfile.Role.MANAGER]


def _sales_queryset(profile, sales_rep):
    qs = Sale.objects.select_related("sales_rep__user", "product", "plan", "business_unit")
    if profile and profile.role == UserProfile.Role.ADMIN:
        return qs
    if profile and profile.role == UserProfile.Role.MANAGER:
        return qs.filter(business_unit=profile.business_unit)
    if sales_rep:
        return qs.filter(sales_rep=sales_rep)
    return qs.none()


def _can_access_business_unit(profile, sales_rep, business_unit):
    if profile and profile.role == UserProfile.Role.ADMIN:
        return True
    if profile and profile.role == UserProfile.Role.MANAGER:
        return profile.business_unit_id == business_unit.id
    if sales_rep:
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


@login_required
def home(request):
    profile = _profile(request.user)
    if _can_manage(profile):
        return redirect("dashboard:admin_overview")
    return redirect("dashboard:sales_overview")


@login_required
def admin_overview(request):
    profile = _profile(request.user)
    if not _can_manage(profile):
        return HttpResponseForbidden("Not allowed")

    sales = _sales_queryset(profile, _sales_rep(request.user))
    context = {
        "title": "Admin/Manager Overview",
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

    business_unit = get_object_or_404(BusinessUnit, code=page["code"])
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    if not _can_access_business_unit(profile, sales_rep, business_unit):
        return HttpResponseForbidden("Not allowed")

    sales = Sale.objects.filter(business_unit=business_unit).select_related(
        "sales_rep__user", "product", "plan", "business_unit"
    )
    # SalesRep users can access every unit page, but only with their own data.
    if sales_rep:
        sales = sales.filter(sales_rep=sales_rep)
    sales = sales.order_by("-created_at")

    context = {
        "title": f"Unidad de Negocio: {business_unit.name}",
        "unit_label": page["label"],
        "business_unit": business_unit,
        "total_sales": sales.count(),
        "confirmed_sales": sales.filter(status=Sale.Status.CONFIRMED).count(),
        "total_amount": sales.aggregate(value=Sum("amount"))["value"] or 0,
        "sales_status_chart": _status_chart_data(sales),
        "daily_sales_chart": _daily_sales_chart_data(sales),
        "recent_sales": sales[:10],
    }
    return render(request, "dashboard/business_unit_overview.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def associate_profile(request):
    sales_rep = _sales_rep(request.user)
    allowed_tabs = {"pane-personal", "pane-addresses", "pane-work"}
    active_tab = request.GET.get("tab", "pane-personal")
    if active_tab not in allowed_tabs:
        active_tab = "pane-personal"

    user_form = UserProfileForm(instance=request.user)
    associate_form = AssociateProfileForm(instance=sales_rep, active_tab=active_tab) if sales_rep else None

    if request.method == "POST":
        posted_tab = request.POST.get("active_tab", "pane-personal")
        if posted_tab in allowed_tabs:
            active_tab = posted_tab
        user_form = UserProfileForm(request.POST, instance=request.user)
        if sales_rep:
            associate_form = AssociateProfileForm(
                request.POST,
                request.FILES,
                instance=sales_rep,
                active_tab=active_tab,
            )
            forms_valid = user_form.is_valid() and associate_form.is_valid()
        else:
            forms_valid = user_form.is_valid()

        if forms_valid:
            with transaction.atomic():
                user_form.save()
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
            "associate_form": associate_form,
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
    sales = _sales_queryset(profile, sales_rep)

    points_qs = RewardPoint.objects.filter(sales_rep=sales_rep) if sales_rep else RewardPoint.objects.none()
    redemption_qs = Redemption.objects.filter(sales_rep=sales_rep) if sales_rep else Redemption.objects.none()

    context = {
        "title": "Sales Dashboard",
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
    sales_qs = _sales_queryset(profile, sales_rep)

    paginator = Paginator(sales_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "dashboard/sales_list.html", {"page_obj": page_obj, "sales": page_obj.object_list})


@login_required
def sales_detail(request, pk):
    profile = _profile(request.user)
    sales_rep = _sales_rep(request.user)
    sale = get_object_or_404(_sales_queryset(profile, sales_rep), pk=pk)
    commission = getattr(sale, "commission", None)
    reward_point = getattr(sale, "reward_point", None)
    return render(
        request,
        "dashboard/sales_detail.html",
        {"sale": sale, "commission": commission, "reward_point": reward_point},
    )


@login_required
def points_summary(request):
    sales_rep = _sales_rep(request.user)
    if sales_rep is None:
        return HttpResponseForbidden("Only SalesRep users can view points.")

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

    if _can_manage(profile):
        queryset = CallLog.objects.select_related("sales_rep__user", "sale")
        if profile.role == UserProfile.Role.MANAGER and profile.business_unit:
            queryset = queryset.filter(sales_rep__business_unit=profile.business_unit)
    elif sales_rep:
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
    if sales_rep is None:
        return HttpResponseForbidden("Only SalesRep users can register call logs.")

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
