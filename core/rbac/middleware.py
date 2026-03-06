from __future__ import annotations

from dataclasses import dataclass

from core.models import RoleModulePermission
from core.rbac.services import get_profile
from core.rbac.services import get_role_code
from core.rbac.constants import role_priority


@dataclass(frozen=True)
class RBACRequestContext:
    role_code: str | None
    role_priority: int
    permissions: tuple[tuple[str, str], ...]


class RBACContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            profile = get_profile(user)
            code = get_role_code(user)
            if user.is_superuser:
                permissions = tuple()
            else:
                permissions = tuple(
                    RoleModulePermission.objects.filter(role__code=code, allowed=True)
                    .values_list("permission__module", "permission__action")
                    .distinct()
                )
            request.rbac = RBACRequestContext(
                role_code=code,
                role_priority=999 if user.is_superuser else role_priority(code),
                permissions=permissions,
            )
        else:
            request.rbac = RBACRequestContext(role_code=None, role_priority=0, permissions=tuple())

        return self.get_response(request)
