from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Sequence

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection

from core.models import UserProfile
from core.rbac.constants import RoleCode
from core.rbac.services import is_platform_admin
from crm.models import SalesRep

User = get_user_model()

CACHE_TTL_SECONDS = 120
ELEVATED_TEAM_SCOPE_ROLES = {
    RoleCode.PARTNER,
    RoleCode.JR_PARTNER,
    RoleCode.BUSINESS_MANAGER,
    RoleCode.ELITE_MANAGER,
    RoleCode.SENIOR_MANAGER,
    RoleCode.MANAGER,
    RoleCode.SOLAR_ADVISOR,
}


@dataclass(frozen=True)
class TeamScope:
    can_access: bool
    can_view_all: bool
    global_scope: bool
    business_unit_ids: tuple[int, ...]
    own_sales_rep_id: int | None


def _admin_business_unit_ids(profile: UserProfile | None) -> list[int]:
    if not profile or not is_platform_admin(profile.user):
        return []
    ids = list(profile.business_units.values_list("id", flat=True))
    if not ids and profile.business_unit_id:
        ids = [profile.business_unit_id]
    return ids


def _profile_business_unit_ids(profile: UserProfile | None) -> list[int]:
    if not profile:
        return []
    ids = list(profile.business_units.values_list("id", flat=True))
    if not ids and profile.business_unit_id:
        ids = [profile.business_unit_id]
    return ids


def _resolve_team_scope(user: User, *, all_requested: bool = False, include_elevated_team: bool = False) -> TeamScope:
    profile = getattr(user, "profile", None)
    sales_rep = SalesRep.objects.filter(user=user).only("id").first()

    is_platform_admin_user = is_platform_admin(user)
    can_view_all = is_platform_admin_user

    if is_platform_admin_user:
        if all_requested:
            return TeamScope(
                can_access=True,
                can_view_all=True,
                global_scope=True,
                business_unit_ids=(),
                own_sales_rep_id=sales_rep.id if sales_rep else None,
            )

        admin_units = _admin_business_unit_ids(profile)
        if admin_units:
            return TeamScope(
                can_access=True,
                can_view_all=True,
                global_scope=False,
                business_unit_ids=tuple(sorted(set(admin_units))),
                own_sales_rep_id=sales_rep.id if sales_rep else None,
            )

        return TeamScope(
            can_access=True,
            can_view_all=True,
            global_scope=True,
            business_unit_ids=(),
            own_sales_rep_id=sales_rep.id if sales_rep else None,
        )

    if profile and profile.role in ELEVATED_TEAM_SCOPE_ROLES:
        if include_elevated_team:
            scoped_units = _profile_business_unit_ids(profile)
            if scoped_units:
                return TeamScope(
                    can_access=True,
                    can_view_all=False,
                    global_scope=False,
                    business_unit_ids=tuple(sorted(set(scoped_units))),
                    own_sales_rep_id=sales_rep.id if sales_rep else None,
                )
        if sales_rep:
            return TeamScope(
                can_access=True,
                can_view_all=False,
                global_scope=False,
                business_unit_ids=(),
                own_sales_rep_id=sales_rep.id,
            )
        scoped_units = _profile_business_unit_ids(profile)
        if scoped_units:
            return TeamScope(
                can_access=True,
                can_view_all=False,
                global_scope=False,
                business_unit_ids=tuple(sorted(set(scoped_units))),
                own_sales_rep_id=None,
            )
        return TeamScope(
            can_access=False,
            can_view_all=can_view_all,
            global_scope=False,
            business_unit_ids=(),
            own_sales_rep_id=None,
        )

    # Regla de privacidad: el resto de roles queda limitado a su propio registro comercial.
    if profile and sales_rep:
        return TeamScope(
            can_access=True,
            can_view_all=False,
            global_scope=False,
            business_unit_ids=(),
            own_sales_rep_id=sales_rep.id,
        )

    return TeamScope(
        can_access=False,
        can_view_all=can_view_all,
        global_scope=False,
        business_unit_ids=(),
        own_sales_rep_id=None,
    )


def resolve_team_scope(user: User, *, all_requested: bool = False) -> TeamScope:
    return _resolve_team_scope(user, all_requested=all_requested, include_elevated_team=False)


def resolve_my_team_scope(user: User, *, all_requested: bool = False) -> TeamScope:
    return _resolve_team_scope(user, all_requested=all_requested, include_elevated_team=True)


def _build_filters_sql(
    *,
    scope: TeamScope,
    level: str,
    city: str,
    search: str,
) -> tuple[str, list[Any]]:
    where_parts = ["sr.is_active = 1"]
    params: list[Any] = []

    if not scope.global_scope:
        if scope.business_unit_ids:
            placeholders = ", ".join(["%s"] * len(scope.business_unit_ids))
            where_parts.append(f"sr.business_unit_id IN ({placeholders})")
            params.extend(scope.business_unit_ids)
        elif scope.own_sales_rep_id:
            where_parts.append("sr.id = %s")
            params.append(scope.own_sales_rep_id)

    if level:
        where_parts.append("COALESCE(t.name, 'Sin nivel') = %s")
        params.append(level)

    if city:
        where_parts.append("LOWER(COALESCE(sr.postal_city, '')) = LOWER(%s)")
        params.append(city)

    if search:
        search_term = f"%{search.lower()}%"
        where_parts.append(
            "(" 
            "LOWER(COALESCE(u.first_name, '')) LIKE %s OR "
            "LOWER(COALESCE(u.last_name, '')) LIKE %s OR "
            "LOWER(COALESCE(sr.second_last_name, '')) LIKE %s OR "
            "LOWER(COALESCE(u.username, '')) LIKE %s OR "
            "LOWER(COALESCE(u.email, '')) LIKE %s OR "
            "LOWER(COALESCE(sr.postal_city, '')) LIKE %s OR "
            "LOWER(COALESCE(t.name, 'Sin nivel')) LIKE %s OR "
            "LOWER(COALESCE(bu.name, '')) LIKE %s"
            ")"
        )
        params.extend([search_term] * 8)

    return " AND ".join(where_parts), params


def _normalize_order(column: str, direction: str) -> str:
    allowed = {
        "full_name": "full_name",
        "username": "username",
        "level": "level",
        "city": "city",
        "business_unit": "business_unit",
        "status": "status",
        "contactability": "contactability",
        "hire_date": "hire_date",
    }
    order_column = allowed.get(column, "full_name")
    order_direction = "DESC" if direction == "desc" else "ASC"
    return f"{order_column} {order_direction}"


def query_team_rows(
    *,
    user: User,
    all_requested: bool,
    scope: TeamScope | None = None,
    level: str = "",
    city: str = "",
    search: str = "",
    order_column: str = "full_name",
    order_dir: str = "asc",
    start: int = 0,
    length: int = 25,
) -> dict[str, Any]:
    scope = scope or resolve_team_scope(user, all_requested=all_requested)
    if not scope.can_access:
        return {"scope": scope, "records_total": 0, "records_filtered": 0, "rows": []}

    where_sql, where_params = _build_filters_sql(scope=scope, level=level, city=city, search=search)
    order_sql = _normalize_order(order_column, order_dir)

    # CTE defines a role hierarchy map and projects flattened display fields for the team table.
    cte_sql = f"""
        WITH RECURSIVE role_hierarchy(role_code, role_label, role_rank) AS (
            SELECT 'PARTNER', 'Partner', 100
            UNION ALL
            SELECT 'ADMINISTRADOR', 'Administrador', 90
            UNION ALL
            SELECT 'JR_PARTNER', 'Jr Partner', 85
            UNION ALL
            SELECT 'BUSINESS_MANAGER', 'Business Manager', 80
            UNION ALL
            SELECT 'ELITE_MANAGER', 'Elite Manager', 70
            UNION ALL
            SELECT 'SENIOR_MANAGER', 'Senior Manager', 60
            UNION ALL
            SELECT 'MANAGER', 'Manager', 50
            UNION ALL
            SELECT 'SOLAR_ADVISOR', 'Solar Advisor', 40
            UNION ALL
            SELECT 'SOLAR_CONSULTANT', 'Solar Consultant', 30
        ),
        team_source AS (
            SELECT
                sr.id AS sales_rep_id,
                TRIM(
                    COALESCE(u.first_name, '') || ' ' ||
                    COALESCE(u.last_name, '') || ' ' ||
                    COALESCE(sr.second_last_name, '')
                ) AS full_name,
                u.username AS username,
                u.email AS email,
                sr.phone AS phone,
                COALESCE(t.name, 'Sin nivel') AS level,
                COALESCE(t.rank, 999) AS level_rank,
                COALESCE(sr.postal_city, '') AS city,
                COALESCE(sr.postal_state, '') AS state,
                COALESCE(bu.name, '') AS business_unit,
                CASE WHEN sr.is_active = 1 THEN 'Activo' ELSE 'Inactivo' END AS status,
                CASE
                    WHEN COALESCE(sr.phone, '') <> '' OR COALESCE(u.email, '') <> '' THEN 'Contactable'
                    ELSE 'Sin contacto'
                END AS contactability,
                COALESCE(rh.role_label, 'Solar Consultant') AS role_label,
                up.role AS role_code,
                COALESCE(up.hire_date, sr.hire_date) AS hire_date
            FROM crm_salesrep sr
            JOIN auth_user u ON u.id = sr.user_id
            LEFT JOIN core_userprofile up ON up.user_id = u.id
            LEFT JOIN core_businessunit bu ON bu.id = sr.business_unit_id
            LEFT JOIN rewards_tier t ON t.id = sr.tier_id
            LEFT JOIN role_hierarchy rh ON rh.role_code = up.role
            WHERE {where_sql}
        )
    """

    total_where_sql, total_params = _build_filters_sql(scope=scope, level="", city="", search="")

    total_sql = f"""
        SELECT COUNT(*)
        FROM crm_salesrep sr
        JOIN auth_user u ON u.id = sr.user_id
        LEFT JOIN rewards_tier t ON t.id = sr.tier_id
        LEFT JOIN core_businessunit bu ON bu.id = sr.business_unit_id
        WHERE {total_where_sql}
    """

    filtered_sql = cte_sql + "SELECT COUNT(*) FROM team_source"
    data_sql = cte_sql + f"""
        SELECT *
        FROM team_source
        ORDER BY {order_sql}
        LIMIT %s OFFSET %s
    """

    with connection.cursor() as cursor:
        cursor.execute(total_sql, total_params)
        records_total = int(cursor.fetchone()[0])

        cursor.execute(filtered_sql, where_params)
        records_filtered = int(cursor.fetchone()[0])

        cursor.execute(data_sql, [*where_params, length, start])
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, item)) for item in cursor.fetchall()]

    return {
        "scope": scope,
        "records_total": records_total,
        "records_filtered": records_filtered,
        "rows": rows,
    }


def get_team_dashboard_context(*, user: User, all_requested: bool = False, scope: TeamScope | None = None) -> dict[str, Any]:
    scope = scope or resolve_team_scope(user, all_requested=all_requested)
    if not scope.can_access:
        return {
            "scope": scope,
            "kpis": {
                "total": 0,
                "contactables": 0,
                "contactabilidad": 0,
                "breakdown": [],
            },
            "cities": [],
        }

    cache_key = f"my_team:summary:{user.id}:{int(all_requested)}:{int(scope.global_scope)}:{'-'.join(map(str, scope.business_unit_ids))}:{scope.own_sales_rep_id or 0}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    payload = query_team_rows(
        user=user,
        all_requested=all_requested,
        scope=scope,
        start=0,
        length=5000,
    )
    rows = payload["rows"]

    total = len(rows)
    contactables = sum(1 for row in rows if row.get("contactability") == "Contactable")
    contactabilidad = round((contactables / total) * 100, 1) if total else 0

    level_counts: dict[str, int] = {}
    cities = set()
    for row in rows:
        level = row.get("level") or "Sin nivel"
        level_counts[level] = level_counts.get(level, 0) + 1
        city = (row.get("city") or "").strip()
        if city:
            cities.add(city)

    breakdown = [
        {"nivel": level, "total": count}
        for level, count in sorted(level_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    context = {
        "scope": scope,
        "kpis": {
            "total": total,
            "contactables": contactables,
            "contactabilidad": contactabilidad,
            "breakdown": breakdown,
        },
        "cities": sorted(cities),
    }

    cache.set(cache_key, context, CACHE_TTL_SECONDS)
    return context



