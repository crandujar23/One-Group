from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from core.rbac.constants import ModuleCode
from core.rbac.constants import PermissionAction
from core.rbac.decorators import require_hierarchy_access
from core.rbac.decorators import require_module_permission
from core.rbac.services import can_approve

User = get_user_model()


@login_required
def notifications_unread_count(request):
    # Placeholder endpoint used by navbar polling.
    # Keep stable contract even if notifications module is not enabled yet.
    return JsonResponse({"count": 0})


@login_required
@require_module_permission(ModuleCode.REPORTS, PermissionAction.VIEW)
def rbac_reports_health(request):
    return JsonResponse({"ok": True, "module": ModuleCode.REPORTS})


@login_required
@require_hierarchy_access(action="manage", user_kwarg="user_id")
def rbac_manage_user_example(request, user_id: int):
    target = User.objects.filter(pk=user_id).only("id", "username").first()
    return JsonResponse(
        {
            "allowed": True,
            "target": target.username if target else None,
            "action": PermissionAction.MANAGE,
        }
    )


@login_required
@require_module_permission(ModuleCode.COMMISSIONS, PermissionAction.APPROVE)
def rbac_approve_commission_example(request, user_id: int):
    target = User.objects.filter(pk=user_id).first()
    return JsonResponse(
        {
            "allowed": bool(target and can_approve(request.user, ModuleCode.COMMISSIONS, target=target)),
            "target_user_id": user_id,
        }
    )
