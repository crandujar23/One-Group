from __future__ import annotations

try:
    from rest_framework.permissions import BasePermission
except Exception:  # pragma: no cover
    BasePermission = object

from core.rbac.services import has_module_permission


class RBACModulePermission(BasePermission):
    required_module: str = ""
    required_action: str = "view"

    def has_permission(self, request, view):
        module = getattr(view, "required_module", self.required_module)
        action = getattr(view, "required_action", self.required_action)
        if not module:
            return False
        return has_module_permission(request.user, module=module, action=action)
