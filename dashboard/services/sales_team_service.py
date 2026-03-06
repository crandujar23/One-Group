from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from core.models import UserProfile
from core.rbac.constants import RoleCode
from core.rbac.constants import role_priority
from core.rbac.services import can_manage
from crm.models import SalesRep
from dashboard.models import OperationsAdminInviteRequest
from dashboard.services.team_personal_info_service import get_salesrep_profiles
from dashboard.services.team_personal_info_service import sanitize_team_payload_for_actor
from dashboard.services.team_personal_info_service import display_user_name
from dashboard.services.team_service import resolve_team_scope

User = get_user_model()
CACHE_TTL_SECONDS = 120
PROMOTION_ELIGIBLE_ROLES = {
    RoleCode.SENIOR_MANAGER,
    RoleCode.ELITE_MANAGER,
    RoleCode.BUSINESS_MANAGER,
    RoleCode.PARTNER,
}


@dataclass(frozen=True)
class SalesTeamAccessResult:
    allowed: bool
    scope_profile: UserProfile | None
    error_message: str = ""


def normalize_search_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


def can_access_team_section(user: User) -> bool:
    if not user.is_authenticated:
        return False
    scope = resolve_team_scope(user, all_requested=False)
    return scope.can_access


def _is_partner_sensitive_allowed(actor: User) -> bool:
    if actor.is_superuser:
        return True
    profile = getattr(actor, "profile", None)
    if not profile:
        return False
    return profile.role in {RoleCode.PARTNER, RoleCode.ADMINISTRADOR}


def can_manage_operations_admin_group(user: User) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == RoleCode.PARTNER)


def user_can_request_removal(user: User) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    if not profile:
        return False
    return profile.role in {
        RoleCode.PARTNER,
        RoleCode.ADMINISTRADOR,
        RoleCode.BUSINESS_MANAGER,
        RoleCode.ELITE_MANAGER,
        RoleCode.SENIOR_MANAGER,
        RoleCode.MANAGER,
        RoleCode.SOLAR_ADVISOR,
    }


def user_can_execute_removal(user: User) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role in {RoleCode.PARTNER, RoleCode.ADMINISTRADOR, RoleCode.BUSINESS_MANAGER})


def can_start_salesrep_promotions(user: User) -> bool:
    profile = getattr(user, "profile", None)
    if not profile and not user.is_superuser:
        return False

    if profile and profile.role == RoleCode.ADMINISTRADOR:
        return False

    return bool(
        user.is_superuser
        or user.has_perm("apps.can_start_promotion")
        or (profile and profile.role in PROMOTION_ELIGIBLE_ROLES)
    )


def resolve_sales_team_scope_profile_for_user(user: User) -> SalesTeamAccessResult:
    profile = getattr(user, "profile", None)
    if not profile:
        return SalesTeamAccessResult(False, None, "Tu perfil no está configurado aún.")

    if not can_access_team_section(user):
        return SalesTeamAccessResult(False, None, "No tienes permisos para acceder a Mi Equipo.")

    if profile.role == RoleCode.ADMINISTRADOR:
        approved_invite = (
            OperationsAdminInviteRequest.objects.select_related("inviter_partner", "inviter_partner__profile")
            .filter(invited_user=user, status=OperationsAdminInviteRequest.Status.APPROVED)
            .order_by("-updated_at")
            .first()
        )
        if approved_invite and hasattr(approved_invite.inviter_partner, "profile"):
            inviter_profile = approved_invite.inviter_partner.profile
            if inviter_profile.role == RoleCode.PARTNER:
                return SalesTeamAccessResult(True, inviter_profile)
        return SalesTeamAccessResult(
            False,
            None,
            "Tu acceso de Administrador aun no ha sido aprobado por el Partner.",
        )

    if SalesRep.objects.filter(user=user).exists():
        return SalesTeamAccessResult(True, profile)

    if user.is_superuser or profile.role in {
        RoleCode.PARTNER,
        RoleCode.JR_PARTNER,
        RoleCode.BUSINESS_MANAGER,
        RoleCode.ELITE_MANAGER,
        RoleCode.SENIOR_MANAGER,
        RoleCode.MANAGER,
        RoleCode.SOLAR_ADVISOR,
    }:
        return SalesTeamAccessResult(True, profile)

    return SalesTeamAccessResult(False, None, "Tu perfil no está configurado aún.")


def get_sales_team_rows(scope_profile_id: int, actor: User, *, all_requested: bool = False) -> list[dict[str, Any]]:
    cache_key = f"sales_team_rows:{scope_profile_id}:{actor.pk}:{int(all_requested)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    payload = get_salesrep_profiles(scope_profile_id, all_requested=all_requested)
    rows = sanitize_team_payload_for_actor(payload, actor)

    # Remove partner entities for non-authorized actors and clean partner references.
    if not _is_partner_sensitive_allowed(actor):
        partner_names = {r.get("full_name", "") for r in rows if r.get("level_name") == "Partner"}
        redacted: list[dict[str, Any]] = []
        for row in rows:
            row_copy = dict(row)
            if row_copy.get("level_name") == "Partner":
                continue
            for field in ("partner", "partner_name", "partner_rate"):
                if field == "partner_rate":
                    row_copy[field] = 0
                else:
                    row_copy[field] = ""
            if row_copy.get("parent_name") in partner_names:
                row_copy["parent_name"] = ""
            redacted.append(row_copy)
        rows = redacted

    cache.set(cache_key, rows, CACHE_TTL_SECONDS)
    return rows


def compute_sales_team_summary(rows: list[dict[str, Any]], scope_profile: UserProfile) -> dict[str, Any]:
    total = len(rows)
    with_phone = sum(1 for row in rows if (row.get("phone") or "").strip())
    with_email = sum(1 for row in rows if (row.get("username") or "").strip())
    contactable = sum(
        1 for row in rows if (row.get("phone") or "").strip() and (row.get("username") or "").strip()
    )
    contactable_pct = round((contactable / total) * 100, 1) if total else 0.0

    root_display_name = display_user_name(scope_profile.user) if scope_profile and scope_profile.user_id else ""
    direct_reports = sum(1 for row in rows if (row.get("parent_name") or "") == root_display_name)

    level_counter = Counter((row.get("level_name") or "Sin nivel") for row in rows)
    sort_map: dict[str, int] = {}
    for row in rows:
        level = row.get("level_name") or "Sin nivel"
        sort_map[level] = max(sort_map.get(level, 0), int(row.get("sort_value") or 0))

    levels_total = len(level_counter)
    level_breakdown = [
        {
            "name": level,
            "count": count,
            "percentage": round((count / total) * 100, 1) if total else 0.0,
            "sort": sort_map.get(level, 0),
        }
        for level, count in level_counter.items()
    ]
    level_breakdown.sort(key=lambda item: (-item["sort"], item["name"]))

    sponsors = sorted({(row.get("parent_name") or "").strip() for row in rows if (row.get("parent_name") or "").strip()})
    cities = sorted({(row.get("city") or "").strip() for row in rows if (row.get("city") or "").strip()})

    return {
        "team_totals": {
            "total": total,
            "with_phone": with_phone,
            "with_email": with_email,
            "contactable": contactable,
            "contactable_pct": contactable_pct,
            "direct_reports": direct_reports,
            "levels": levels_total,
        },
        "level_breakdown": level_breakdown,
        "sponsors": sponsors,
        "cities": cities,
    }


def apply_sales_team_filters(rows: list[dict[str, Any]], *, level: str = "", parent: str = "", search: str = "") -> list[dict[str, Any]]:
    filtered = rows
    if level:
        filtered = [row for row in filtered if (row.get("level_name") or "") == level]
    if parent:
        filtered = [row for row in filtered if (row.get("parent_name") or "") == parent]
    if search:
        token = normalize_search_term(search)
        if token:
            filtered = [
                row
                for row in filtered
                if token in normalize_search_term(row.get("full_name") or "")
                or token in normalize_search_term(row.get("phone") or "")
                or token in normalize_search_term(row.get("username") or "")
                or token in normalize_search_term(row.get("email") or "")
            ]
    return filtered


def actor_can_manage_salesrep(actor: User, salesrep: SalesRep) -> bool:
    if actor.pk == salesrep.user_id:
        return False
    target_profile = getattr(salesrep.user, "profile", None)
    if not target_profile:
        return False
    if target_profile.role == RoleCode.PARTNER:
        return False
    return can_manage(actor, salesrep.user)


def expire_pending_admin_invites() -> int:
    now = timezone.now()
    qs = OperationsAdminInviteRequest.objects.filter(
        status__in=[OperationsAdminInviteRequest.Status.INVITED, OperationsAdminInviteRequest.Status.PENDING],
        expires_at__lte=now,
    )
    return qs.update(status=OperationsAdminInviteRequest.Status.EXPIRED, reviewed_at=now)


def set_admin_invite_decision(*, invite: OperationsAdminInviteRequest, actor: User, approved: bool) -> None:
    status = OperationsAdminInviteRequest.Status.APPROVED if approved else OperationsAdminInviteRequest.Status.REJECTED
    invite.status = status
    invite.reviewed_at = timezone.now()
    invite.reviewed_by = actor
    invite.review_notes = "approved" if approved else "rejected"
    invite.save(update_fields=["status", "reviewed_at", "reviewed_by", "review_notes", "updated_at"])


def role_sort_value(role_code: str | None) -> int:
    return role_priority(role_code)
