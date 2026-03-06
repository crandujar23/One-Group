from __future__ import annotations

from functools import wraps

from django.http import HttpResponseForbidden

from core.rbac.services import can_approve
from core.rbac.services import can_manage
from core.rbac.services import can_view
from core.rbac.services import has_module_permission


def require_module_permission(module: str, action: str):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not has_module_permission(request.user, module=module, action=action):
                return HttpResponseForbidden("No autorizado")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def require_hierarchy_access(action: str = "view", user_kwarg: str = "user_id"):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            target_user = getattr(request, "target_user", None)
            if target_user is None:
                target_id = kwargs.get(user_kwarg)
                if target_id is None:
                    return HttpResponseForbidden("No autorizado")
                from django.contrib.auth import get_user_model

                target_user = get_user_model().objects.filter(pk=target_id).first()
            if target_user is None:
                return HttpResponseForbidden("No autorizado")

            allowed = False
            if action == "manage":
                allowed = can_manage(request.user, target_user)
            elif action == "approve":
                allowed = can_approve(request.user, module="users", target=target_user)
            else:
                allowed = can_view(request.user, target=target_user)

            if not allowed:
                return HttpResponseForbidden("No autorizado")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
