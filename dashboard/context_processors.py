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
        return "Superadministrador"
    if profile:
        if profile.role == UserProfile.Role.ADMIN:
            return "Socio"
        if profile.role == UserProfile.Role.MANAGER:
            return "Administrador"
        if profile.role == UserProfile.Role.SALES_REP:
            return "Asociado"
    return "Usuario"


def _is_platform_admin(user, profile):
    return bool(user.is_superuser or (profile and profile.role == UserProfile.Role.ADMIN))


def _is_associate(profile, sales_rep):
    return bool(profile and profile.role == UserProfile.Role.SALES_REP and sales_rep)


def _manager_business_unit_ids(profile):
    if not profile or profile.role != UserProfile.Role.MANAGER:
        return []
    ids = list(profile.business_units.values_list("id", flat=True))
    if not ids and profile.business_unit_id:
        ids = [profile.business_unit_id]
    return ids


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
        if not unit and not _is_platform_admin(user, profile):
            continue

        allowed = False
        if _is_platform_admin(user, profile):
            allowed = True
        elif profile and profile.role == UserProfile.Role.MANAGER:
            allowed = unit.id in _manager_business_unit_ids(profile)
        elif _is_associate(profile, sales_rep):
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
        {"label": "Registro de llamadas", "url_name": "dashboard:call_logs", "url_key": "call_logs"},
    ]
    if user.is_superuser:
        operations_nav_items.insert(0, {"label": "Gestión de Accesos", "url_name": "dashboard:access_management", "url_key": "access_management"})
    if _is_platform_admin(user, profile):
        operations_nav_items.insert(1, {"label": "Nuevo Asociado", "url_name": "dashboard:associate_create", "url_key": "associate_create"})
    if _is_associate(profile, sales_rep) or _is_platform_admin(user, profile):
        operations_nav_items.insert(1, {"label": "Puntos", "url_name": "dashboard:points_summary", "url_key": "points_summary"})
    workspace_nav_items = [
        {"label": "Gestión de Clientes", "url_name": "dashboard:client_management", "url_key": "client_management"},
        {"label": "Mi equipo", "url_name": "dashboard:my_team", "url_key": "my_team"},
        {"label": "Tareas", "url_name": "dashboard:tasks", "url_key": "tasks"},
        {"label": "Herramientas", "url_name": "dashboard:tools", "url_key": "tools"},
    ]
    nav_display_name = _display_name(user, sales_rep)
    nav_avatar_url = ""
    if profile and profile.avatar:
        nav_avatar_url = profile.avatar.url
    elif sales_rep and sales_rep.avatar:
        nav_avatar_url = sales_rep.avatar.url

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
        "is_admin_user": _is_platform_admin(user, profile),
        "is_manager_user": bool(profile and profile.role == UserProfile.Role.MANAGER),
        "is_sales_rep_user": _is_associate(profile, sales_rep),
    }
