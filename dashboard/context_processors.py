from dashboard.business_units import BUSINESS_UNIT_PAGES
from core.models import UserProfile
from core.models import BusinessUnit
from crm.models import SalesRep


def navigation_context(request):
    user = request.user
    if not user.is_authenticated:
        return {}

    profile = getattr(user, "profile", None)
    sales_rep = SalesRep.objects.filter(user=user).select_related("tier", "business_unit").first()
    business_unit_by_code = {item.code: item for item in BusinessUnit.objects.filter(is_active=True)}

    unit_nav_items = []
    for item in BUSINESS_UNIT_PAGES:
        unit = business_unit_by_code.get(item["code"])
        if not unit:
            continue

        allowed = False
        if profile and profile.role == UserProfile.Role.ADMIN:
            allowed = True
        elif profile and profile.role == UserProfile.Role.MANAGER:
            allowed = profile.business_unit_id == unit.id
        elif sales_rep:
            allowed = True

        if allowed:
            unit_nav_items.append(
                {
                    "label": item["label"],
                    "url_name": f"dashboard:{item['route_name']}",
                    "code": item["code"],
                }
            )

    return {
        "nav_profile": profile,
        "nav_sales_rep": sales_rep,
        "unit_nav_items": unit_nav_items,
        "is_admin_user": bool(profile and profile.role == UserProfile.Role.ADMIN),
        "is_manager_user": bool(profile and profile.role == UserProfile.Role.MANAGER),
        "is_sales_rep_user": bool(sales_rep),
    }
