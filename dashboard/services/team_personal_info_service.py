from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.core.cache import cache

from core.models import UserProfile
from core.rbac.constants import RoleCode
from crm.models import SalesRep
from dashboard.services.hierarchy_scope_service import get_downline_user_ids
from dashboard.services.team_service import resolve_team_scope

User = get_user_model()
CACHE_TTL_SECONDS = 120
MAX_COMMISSION_RATE = 0.19
ROLE_BASE_RATE = {
    RoleCode.PARTNER: 0.19,
    RoleCode.JR_PARTNER: 0.17,
    RoleCode.BUSINESS_MANAGER: 0.16,
    RoleCode.ELITE_MANAGER: 0.15,
    RoleCode.SENIOR_MANAGER: 0.14,
    RoleCode.MANAGER: 0.13,
    RoleCode.SOLAR_ADVISOR: 0.12,
    RoleCode.SOLAR_CONSULTANT: 0.06,
}


@dataclass(frozen=True)
class TeamPersonalAccessResult:
    allowed: bool
    scope_profile: UserProfile | None
    error_message: str = ""


def display_user_name(user: User | None) -> str:
    if not user:
        return ""
    full_name = user.get_full_name().strip()
    return full_name or user.get_username()


def _commission_distribution_for_profile(profile: UserProfile | None) -> tuple[dict[int, float], dict[int, str]]:
    if not profile or not profile.user_id:
        return {}, {}

    chain: list[UserProfile] = []
    current = profile
    visited: set[int] = set()
    while current and current.user_id and current.user_id not in visited:
        visited.add(current.user_id)
        chain.append(current)
        if not current.manager_id:
            break
        current = getattr(current.manager, "profile", None)

    if not chain:
        return {}, {}

    seller_rate = ROLE_BASE_RATE.get(chain[0].role, 0.0)
    if seller_rate <= 0:
        return {}, {}

    role_by_user = {item.user_id: item.role for item in chain}
    distribution: dict[int, float] = {chain[0].user_id: seller_rate}
    current_max = seller_rate

    for ancestor in chain[1:]:
        target_rate = ROLE_BASE_RATE.get(ancestor.role, 0.0)
        if target_rate <= current_max:
            continue
        share = round(target_rate - current_max, 6)
        if share > 0:
            distribution[ancestor.user_id] = share
            current_max = target_rate
        if current_max >= MAX_COMMISSION_RATE:
            break

    return distribution, role_by_user


def _can_view_partner_sensitive(actor: User) -> bool:
    if actor.is_superuser:
        return True
    profile = getattr(actor, "profile", None)
    if not profile:
        return False
    return profile.role in {RoleCode.PARTNER, RoleCode.ADMINISTRADOR}


def _ancestor_names(profile: UserProfile | None) -> dict[str, str]:
    names = {
        "consultant_name": "",
        "teamleader_name": "",
        "manager_name": "",
        "executive_manager_name": "",
        "promanager_name": "",
        "jr_partner_name": "",
        "partner_name": "",
    }
    current = profile
    visited: set[int] = set()
    while current and current.user_id and current.user_id not in visited:
        visited.add(current.user_id)
        role = current.role
        display_name = display_user_name(current.user)
        if role == RoleCode.SOLAR_CONSULTANT and not names["consultant_name"]:
            names["consultant_name"] = display_name
        elif role == RoleCode.SOLAR_ADVISOR and not names["teamleader_name"]:
            names["teamleader_name"] = display_name
        elif role == RoleCode.MANAGER and not names["manager_name"]:
            names["manager_name"] = display_name
        elif role in {RoleCode.SENIOR_MANAGER, RoleCode.ELITE_MANAGER} and not names["executive_manager_name"]:
            names["executive_manager_name"] = display_name
        elif role == RoleCode.BUSINESS_MANAGER and not names["promanager_name"]:
            names["promanager_name"] = display_name
        elif role == RoleCode.JR_PARTNER and not names["jr_partner_name"]:
            names["jr_partner_name"] = display_name
        elif role == RoleCode.PARTNER and not names["partner_name"]:
            names["partner_name"] = display_name
        if not current.manager_id:
            break
        manager_user = current.manager
        current = getattr(manager_user, "profile", None)
    return names


def can_access_team_personal_info(user: User) -> bool:
    if not user.is_authenticated:
        return False
    scope = resolve_team_scope(user, all_requested=False)
    return scope.can_access


def resolve_scope_profile_for_user(user: User) -> TeamPersonalAccessResult:
    profile = getattr(user, "profile", None)
    if not profile:
        return TeamPersonalAccessResult(False, None, "No se encontro perfil de usuario.")

    if not can_access_team_personal_info(user):
        return TeamPersonalAccessResult(False, None, "No tienes permisos para acceder a Mi Equipo.")

    salesrep_profile = SalesRep.objects.filter(user=user).first()

    # Admin de operaciones invitado/aprobado: hereda alcance del partner que lo invito.
    if profile.role == RoleCode.ADMINISTRADOR and profile.manager_id:
        inviter_profile = getattr(profile.manager, "profile", None)
        if inviter_profile and inviter_profile.role == RoleCode.PARTNER:
            return TeamPersonalAccessResult(True, inviter_profile)

    if salesrep_profile:
        return TeamPersonalAccessResult(True, profile)

    if user.is_superuser or profile.role in {
        RoleCode.PARTNER,
        RoleCode.ADMINISTRADOR,
        RoleCode.JR_PARTNER,
        RoleCode.BUSINESS_MANAGER,
        RoleCode.ELITE_MANAGER,
        RoleCode.SENIOR_MANAGER,
        RoleCode.MANAGER,
        RoleCode.SOLAR_ADVISOR,
    }:
        return TeamPersonalAccessResult(True, profile)

    return TeamPersonalAccessResult(False, None, "No hay perfil valido para mostrar equipo.")


def get_salesrep_profiles(scope_profile_id: int, all_requested: bool = False) -> list[dict[str, Any]]:
    cache_key = f"team_personal_info:{scope_profile_id}:{int(all_requested)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    scope_profile = UserProfile.objects.select_related("user").filter(id=scope_profile_id).first()
    if not scope_profile:
        return []

    scope = resolve_team_scope(scope_profile.user, all_requested=all_requested)
    reps = SalesRep.objects.select_related("user", "user__profile", "business_unit", "tier")
    if not scope.can_access:
        return []
    if not scope.global_scope:
        if scope.business_unit_ids:
            reps = reps.filter(business_unit_id__in=scope.business_unit_ids)
        elif scope.own_sales_rep_id:
            reps = reps.filter(id=scope.own_sales_rep_id)
        else:
            reps = reps.none()

    payload: list[dict[str, Any]] = []
    for rep in reps.order_by("user__first_name", "user__last_name", "user__username"):
        profile = getattr(rep.user, "profile", None)
        parent_name = display_user_name(profile.manager) if profile and profile.manager_id else ""
        ancestor = _ancestor_names(profile)
        level_name = profile.get_role_display() if profile else "Sin nivel"
        is_operations_admin = bool(profile and profile.role == RoleCode.ADMINISTRADOR)
        distribution, role_by_user = _commission_distribution_for_profile(profile)
        own_share = distribution.get(rep.user_id, 0.0)

        solar_consultant_rate = 0.0
        solar_advisor_rate = 0.0
        manager_rate = 0.0
        senior_manager_rate = 0.0
        elite_manager_rate = 0.0
        business_manager_rate = 0.0
        jr_partner_rate = 0.0
        partner_rate = 0.0

        for user_id, share in distribution.items():
            role_code = role_by_user.get(user_id, "")

            if role_code == RoleCode.SOLAR_CONSULTANT:
                solar_consultant_rate = share
            elif role_code == RoleCode.SOLAR_ADVISOR:
                solar_advisor_rate = share
            elif role_code == RoleCode.MANAGER:
                manager_rate = share
            elif role_code == RoleCode.SENIOR_MANAGER:
                senior_manager_rate = share
            elif role_code == RoleCode.ELITE_MANAGER:
                elite_manager_rate = share
            elif role_code == RoleCode.BUSINESS_MANAGER:
                business_manager_rate = share
            elif role_code == RoleCode.JR_PARTNER:
                jr_partner_rate = share
            elif role_code == RoleCode.PARTNER:
                partner_rate = share

        # Preserve legacy columns consumed by older templates.
        trainee_rate = solar_consultant_rate
        teamleader_rate = solar_advisor_rate
        promanager_rate = business_manager_rate
        executivemanager_rate = max(senior_manager_rate, elite_manager_rate)
        parent_rate = 0.0
        if profile and profile.manager_id:
            parent_rate = distribution.get(profile.manager_id, 0.0)

        payload.append(
            {
                "salesrep_id": rep.id,
                "user_id": rep.user_id,
                "full_name": " ".join(part for part in [rep.user.first_name, rep.user.last_name, rep.second_last_name] if part).strip()
                or rep.user.username,
                "phone": rep.phone or "",
                "username": rep.user.username,
                "email": rep.user.email or "",
                "level_name": level_name,
                "sort_value": profile.role_priority if profile else 0,
                "city": rep.postal_city or "",
                "parent_name": parent_name,
                "consultant_name": ancestor["consultant_name"],
                "teamleader_name": ancestor["teamleader_name"],
                "manager_name": ancestor["manager_name"],
                "executive_manager_name": ancestor["executive_manager_name"],
                "promanager_name": ancestor["promanager_name"],
                "jr_partner_name": ancestor["jr_partner_name"],
                "partner_name": ancestor["partner_name"],
                "solar_consultant_rate": solar_consultant_rate,
                "solar_advisor_rate": solar_advisor_rate,
                "manager_rate": manager_rate,
                "senior_manager_rate": senior_manager_rate,
                "elite_manager_rate": elite_manager_rate,
                "business_manager_rate": business_manager_rate,
                "jr_partner_rate": jr_partner_rate,
                "partner_rate": partner_rate,
                "own_share_rate": own_share,
                "trainee_rate": trainee_rate,
                "consultant_rate": own_share,
                "teamleader_rate": teamleader_rate,
                "promanager_rate": promanager_rate,
                "executivemanager_rate": executivemanager_rate,
                "parent_rate": parent_rate,
                "marketing_memo_acknowledged": False,
                "is_operations_admin": is_operations_admin,
            }
        )

    cache.set(cache_key, payload, CACHE_TTL_SECONDS)
    return payload


def sanitize_team_payload_for_actor(rows: list[dict[str, Any]], actor: User) -> list[dict[str, Any]]:
    partner_sensitive = _can_view_partner_sensitive(actor)
    visible_user_ids: set[int] | None = None
    if not actor.is_superuser:
        visible_user_ids = get_downline_user_ids(actor)

    partner_names = {row.get("partner_name", "") for row in rows if row.get("level_name") == "Partner" and row.get("partner_name")}

    sanitized: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        if row.get("is_operations_admin"):
            continue
        if visible_user_ids is not None and "user_id" in row:
            row_user_id = row.get("user_id")
            if not row_user_id or int(row_user_id) not in visible_user_ids:
                continue

        # Política de privacidad: nunca exponer el porcentaje del patrocinador.
        row["parent_rate"] = 0

        if not partner_sensitive:
            row["partner_rate"] = 0
            row["partner_name"] = ""
            row["partner"] = ""
            if row.get("level_name") == "Partner":
                continue
            if row.get("parent_name") in partner_names:
                row["parent_name"] = ""

        sanitized.append(row)

    return sanitized


def compute_team_personal_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    with_phone = sum(1 for row in rows if (row.get("phone") or "").strip())
    with_email = sum(1 for row in rows if (row.get("email") or "").strip())
    fully_contactable = sum(1 for row in rows if (row.get("phone") or "").strip() and (row.get("email") or "").strip())
    contactable_pct = round((fully_contactable / total) * 100, 1) if total else 0.0

    levels = Counter((row.get("level_name") or "Sin nivel") for row in rows)
    level_breakdown = [
        {
            "name": level,
            "count": count,
            "percentage": round((count / total) * 100, 1) if total else 0.0,
        }
        for level, count in levels.most_common()
    ]

    cities = sorted({(row.get("city") or "").strip() for row in rows if (row.get("city") or "").strip()})

    return {
        "team_totals": {
            "total": total,
            "with_phone": with_phone,
            "with_email": with_email,
            "fully_contactable": fully_contactable,
            "contactable_pct": contactable_pct,
        },
        "level_breakdown": level_breakdown,
        "cities": cities,
    }


def filter_team_personal_rows(rows: list[dict[str, Any]], *, level: str = "", city: str = "", search: str = "") -> list[dict[str, Any]]:
    filtered = rows
    if level:
        filtered = [row for row in filtered if (row.get("level_name") or "") == level]
    if city:
        filtered = [row for row in filtered if (row.get("city") or "") == city]
    if search:
        s = search.lower().strip()
        filtered = [
            row
            for row in filtered
            if s in (row.get("full_name") or "").lower()
            or s in (row.get("phone") or "").lower()
            or s in (row.get("email") or "").lower()
        ]
    return filtered
