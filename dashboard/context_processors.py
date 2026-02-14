from dashboard.business_units import BUSINESS_UNIT_PAGES
from core.models import UserProfile
from core.models import BusinessUnit
from crm.models import SalesRep


def _display_name(user, sales_rep):
    first_name = (user.first_name or "").strip()
    last_name = (user.last_name or "").strip()
    second_last_name = (sales_rep.second_last_name or "").strip() if sales_rep else ""
    full_name = " ".join(part for part in [first_name, last_name, second_last_name] if part)
    return full_name or user.get_username()


def _initials(value):
    parts = [part for part in (value or "").split() if part]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return f"{parts[0][:1]}{parts[1][:1]}".upper()


def _role_label(user, profile):
    if user.is_superuser:
        return "Superadmin"
    if profile:
        if profile.role == UserProfile.Role.ADMIN:
            return "Admin"
        if profile.role == UserProfile.Role.MANAGER:
            return "Manager"
        if profile.role == UserProfile.Role.SALES_REP:
            return "Asociado"
    return "Usuario"


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

    operations_nav_items = [
        {"label": "Ventas", "url_name": "dashboard:sales_list", "url_key": "sales_list"},
        {"label": "Financiamiento", "url_name": "dashboard:financing", "url_key": "financing"},
        {"label": "Call Logs", "url_name": "dashboard:call_logs", "url_key": "call_logs"},
    ]
    if sales_rep:
        operations_nav_items.insert(1, {"label": "Puntos", "url_name": "dashboard:points_summary", "url_key": "points_summary"})
    workspace_nav_items = [
        {"label": "Gestión de Clientes", "url_name": "dashboard:client_management", "url_key": "client_management"},
        {"label": "Mi equipo", "url_name": "dashboard:my_team", "url_key": "my_team"},
        {"label": "Tareas", "url_name": "dashboard:tasks", "url_key": "tasks"},
        {"label": "Herramientas", "url_name": "dashboard:tools", "url_key": "tools"},
    ]
    nav_display_name = _display_name(user, sales_rep)
    nav_avatar_url = sales_rep.avatar.url if sales_rep and sales_rep.avatar else ""

    return {
        "nav_profile": profile,
        "nav_sales_rep": sales_rep,
        "nav_user": {
            "display_name": nav_display_name,
            "avatar_url": nav_avatar_url,
            "initials": _initials(nav_display_name),
            "role_label": _role_label(user, profile),
        },
        "unit_nav_items": unit_nav_items,
        "operations_nav_items": operations_nav_items,
        "workspace_nav_items": workspace_nav_items,
        "is_admin_user": bool(profile and profile.role == UserProfile.Role.ADMIN),
        "is_manager_user": bool(profile and profile.role == UserProfile.Role.MANAGER),
        "is_sales_rep_user": bool(sales_rep),
    }
