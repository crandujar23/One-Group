from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.models import ModulePermission
from core.models import Role
from core.models import RoleChangeAudit
from core.models import RoleModulePermission
from core.models import UserProfile
from core.rbac.constants import DEFAULT_ROLE_PERMISSIONS
from core.rbac.constants import GLOBAL_SCOPE_ROLES
from core.rbac.constants import PermissionAction
from core.rbac.constants import RoleCode
from core.rbac.constants import is_global_role
from core.rbac.constants import role_priority

User = get_user_model()


GLOBAL_ROLE_CODES = set(GLOBAL_SCOPE_ROLES)


def get_profile(user: User) -> UserProfile | None:
    return getattr(user, "profile", None)


def get_role_code(user: User) -> str | None:
    profile = get_profile(user)
    if not profile:
        return None
    return profile.role


def is_descendant_user(manager: User, target: User) -> bool:
    if manager.pk == target.pk:
        return False

    pending = [manager.pk]
    visited: set[int] = set()
    while pending:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        children = list(
            UserProfile.objects.filter(manager_id=current_id).values_list("user_id", flat=True)
        )
        if target.pk in children:
            return True
        pending.extend(children)
    return False


def has_module_permission(user: User, module: str, action: str) -> bool:
    if user.is_superuser:
        return True

    role_code = get_role_code(user)
    if not role_code:
        return False

    db_permission = (
        RoleModulePermission.objects.filter(
            role__code=role_code,
            permission__module=module,
            permission__action=action,
            allowed=True,
            role__is_active=True,
        )
        .select_related("permission", "role")
        .exists()
    )
    if db_permission:
        return True

    defaults = DEFAULT_ROLE_PERMISSIONS.get(role_code, {})
    return action in defaults.get(module, set())


def can_manage(actor: User, target: User) -> bool:
    if not actor.is_authenticated or not target.is_authenticated:
        return False
    if actor.is_superuser:
        return True
    if actor.pk == target.pk:
        return False

    actor_code = get_role_code(actor)
    target_code = get_role_code(target)
    if not actor_code or not target_code:
        return False

    if role_priority(actor_code) <= role_priority(target_code):
        return False

    if actor_code in GLOBAL_ROLE_CODES:
        return True

    return is_descendant_user(actor, target)


def can_view(actor: User, target: User | None = None, module: str | None = None) -> bool:
    if not actor.is_authenticated:
        return False
    if actor.is_superuser:
        return True

    if module and not has_module_permission(actor, module, PermissionAction.VIEW):
        return False

    if target is None or target.pk == actor.pk:
        return True

    actor_code = get_role_code(actor)
    if not actor_code:
        return False
    if actor_code in GLOBAL_ROLE_CODES:
        return True

    return is_descendant_user(actor, target)


def can_approve(actor: User, module: str, target: User | None = None) -> bool:
    if not actor.is_authenticated:
        return False
    if actor.is_superuser:
        return True

    if not has_module_permission(actor, module, PermissionAction.APPROVE):
        return False

    if target is None:
        return True

    return can_view(actor, target=target)


def assign_role(
    *,
    actor: User,
    target: User,
    new_role_code: str,
    reason: str = "",
    manager: User | None = None,
) -> UserProfile:
    if actor.pk == target.pk:
        raise PermissionDenied("No se permite autoescalacion de privilegios.")
    if not can_manage(actor, target):
        raise PermissionDenied("No autorizado para administrar este usuario.")

    actor_code = get_role_code(actor)
    if not actor.is_superuser and role_priority(actor_code) <= role_priority(new_role_code):
        raise PermissionDenied("No puedes asignar un rol igual o superior al tuyo.")

    role_obj = Role.objects.filter(code=new_role_code, is_active=True).first()
    if not role_obj:
        raise PermissionDenied("El rol objetivo no esta disponible.")

    with transaction.atomic():
        profile = target.profile
        previous_role = profile.role
        profile.role = role_obj.code
        profile.role_ref = role_obj
        if manager and manager.pk != target.pk:
            profile.manager = manager
        profile.save(update_fields=["role", "role_ref", "manager"])

        RoleChangeAudit.objects.create(
            actor=actor,
            target=target,
            previous_role=previous_role,
            new_role=role_obj.code,
            reason=reason.strip(),
        )

    return profile


def ensure_seeded_roles_and_permissions() -> None:
    role_by_code: dict[str, Role] = {}
    for code, label in RoleCode.choices:
        role, _ = Role.objects.get_or_create(
            code=code,
            defaults={
                "name": label,
                "priority": role_priority(code),
                "is_active": True,
            },
        )
        role_by_code[code] = role

    chain = [code for code, _ in RoleCode.choices]
    for index, code in enumerate(chain):
        role = role_by_code[code]
        expected_parent = role_by_code[chain[index - 1]] if index > 0 else None
        updates: list[str] = []
        if role.priority != role_priority(code):
            role.priority = role_priority(code)
            updates.append("priority")
        if role.parent_id != (expected_parent.id if expected_parent else None):
            role.parent = expected_parent
            updates.append("parent")
        if updates:
            role.save(update_fields=updates)

    permission_map: dict[tuple[str, str], ModulePermission] = {}
    for module, _ in ModulePermission.Module.choices:
        for action, _ in ModulePermission.Action.choices:
            permission, _ = ModulePermission.objects.get_or_create(module=module, action=action)
            permission_map[(module, action)] = permission

    for role_code, matrix in DEFAULT_ROLE_PERMISSIONS.items():
        role = role_by_code.get(role_code)
        if not role:
            continue
        for module, actions in matrix.items():
            for action in actions:
                permission = permission_map[(module, action)]
                RoleModulePermission.objects.get_or_create(
                    role=role,
                    permission=permission,
                    defaults={"allowed": True},
                )


def get_role_label(user: User) -> str:
    profile = get_profile(user)
    if user.is_superuser:
        return "Superadministrador"
    if not profile:
        return "Usuario"
    legacy_labels = {
        RoleCode.PARTNER: "Partner",
        RoleCode.ADMINISTRADOR: "Administrador",
        RoleCode.SOLAR_CONSULTANT: "Asociado",
    }
    if profile.role in legacy_labels:
        return legacy_labels[profile.role]
    role = Role.objects.filter(code=profile.role).only("name").first()
    return role.name if role else profile.get_role_display()


def is_platform_admin(user: User) -> bool:
    if user.is_superuser:
        return True
    role_code = get_role_code(user)
    return is_global_role(role_code)

