from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from core.rbac.constants import RoleCode
from core.rbac.constants import role_priority
from crm.models import SalesRep

User = get_user_model()
CACHE_TTL_SECONDS = 120

DEFAULT_AVATAR_URL = "https://ui-avatars.com/api/?background=0D8ABC&color=fff&name={name}"


@dataclass(frozen=True)
class GraphBuildResult:
    nodes: list[dict]
    generated_at: datetime


def _full_name(rep: SalesRep) -> str:
    return " ".join(part for part in [rep.user.first_name, rep.user.last_name, rep.second_last_name] if part).strip() or rep.user.username


def _position_name(rep: SalesRep) -> str:
    profile = getattr(rep.user, "profile", None)
    return profile.get_role_display() if profile else "Sin nivel"


def _image_url(rep: SalesRep, request) -> str:
    profile = getattr(rep.user, "profile", None)
    image = None
    if profile and profile.avatar:
        image = profile.avatar.url
    elif rep.avatar:
        image = rep.avatar.url
    if image:
        return request.build_absolute_uri(image)
    return DEFAULT_AVATAR_URL.format(name=quote_plus(_full_name(rep)))


def _area(rep: SalesRep) -> str:
    city = (rep.postal_city or "").strip()
    state = (rep.postal_state or "").strip()
    if city and state:
        return f"{city}, {state}"
    return city or state or "Sin area"


def _role_sort_from_label(position_name: str) -> int:
    for code, label in RoleCode.choices:
        if label == position_name:
            return role_priority(code)
    return 0


def fetch_hierarchy_iterative(root_salesrep_id: int, request) -> GraphBuildResult:
    cache_key = f"sales_team_graph:{request.user.id}:{root_salesrep_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return GraphBuildResult(nodes=cached["nodes"], generated_at=cached["generated_at"])

    reps = list(SalesRep.objects.select_related("user", "user__profile", "business_unit").filter(is_active=True))
    rep_by_id = {rep.id: rep for rep in reps}
    user_to_rep = {rep.user_id: rep for rep in reps}

    root_rep = rep_by_id.get(root_salesrep_id)
    if not root_rep:
        return GraphBuildResult(nodes=[], generated_at=timezone.now())

    children_by_parent_rep_id: dict[int, list[int]] = {}
    for rep in reps:
        profile = getattr(rep.user, "profile", None)
        parent_rep = None
        if profile and profile.manager_id:
            parent_rep = user_to_rep.get(profile.manager_id)
        if not parent_rep and rep.parent_id:
            parent_rep = rep_by_id.get(rep.parent_id)
        if not parent_rep:
            continue
        children_by_parent_rep_id.setdefault(parent_rep.id, []).append(rep.id)

    for parent_id in children_by_parent_rep_id:
        children_by_parent_rep_id[parent_id].sort(key=lambda rid: _full_name(rep_by_id[rid]).lower())

    nodes: list[dict] = []
    stack: list[tuple[int, int | None]] = [(root_rep.id, None)]
    visited: set[int] = set()

    while stack:
        rep_id, parent_rep_id = stack.pop()
        if rep_id in visited:
            continue
        visited.add(rep_id)

        rep = rep_by_id.get(rep_id)
        if not rep:
            continue

        profile = getattr(rep.user, "profile", None)
        role_code = profile.role if profile else ""
        node = {
            "id": str(rep.id),
            "parentId": str(parent_rep_id) if parent_rep_id else None,
            "name": _full_name(rep),
            "imageUrl": _image_url(rep, request),
            "area": _area(rep),
            "profileUrl": reverse("dashboard:associate_profile"),
            "office": rep.business_unit.name if rep.business_unit_id else "Sin oficina",
            "tags": role_code,
            "isLoggedUser": rep.user_id == request.user.id,
            "positionName": _position_name(rep),
            "size": 1,
        }
        nodes.append(node)

        child_ids = children_by_parent_rep_id.get(rep_id, [])
        for child_id in reversed(child_ids):
            stack.append((child_id, rep_id))

    generated_at = timezone.now()
    cache.set(cache_key, {"nodes": nodes, "generated_at": generated_at}, CACHE_TTL_SECONDS)
    return GraphBuildResult(nodes=nodes, generated_at=generated_at)


def compute_graph_summary(nodes: list[dict], root_id: str) -> dict:
    total = len(nodes)
    direct_reports = sum(1 for node in nodes if node.get("parentId") == root_id)

    level_counter = Counter((node.get("positionName") or "Sin nivel") for node in nodes)
    levels = len(level_counter)

    by_id = {node["id"]: node for node in nodes}
    depth_cache: dict[str, int] = {}

    def depth_for(node_id: str) -> int:
        if node_id in depth_cache:
            return depth_cache[node_id]
        node = by_id.get(node_id)
        if not node:
            return 0
        parent_id = node.get("parentId")
        if not parent_id:
            depth_cache[node_id] = 1
            return 1
        depth_cache[node_id] = depth_for(parent_id) + 1
        return depth_cache[node_id]

    max_depth = max((depth_for(node["id"]) for node in nodes), default=0)

    level_breakdown = [
        {
            "name": name,
            "count": count,
            "percentage": round((count / total) * 100, 1) if total else 0.0,
            "sort": _role_sort_from_label(name),
        }
        for name, count in level_counter.items()
    ]
    level_breakdown.sort(key=lambda item: (-item["sort"], item["name"]))

    return {
        "team_totals": {
            "total": total,
            "direct_reports": direct_reports,
            "levels": levels,
            "depth": max_depth,
        },
        "level_breakdown": level_breakdown,
    }
