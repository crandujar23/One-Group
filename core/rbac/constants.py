from __future__ import annotations

from django.db import models


class RoleCode(models.TextChoices):
    PARTNER = "PARTNER", "Partner"
    ADMINISTRADOR = "ADMINISTRADOR", "Administrador"
    JR_PARTNER = "JR_PARTNER", "Jr Partner"
    BUSINESS_MANAGER = "BUSINESS_MANAGER", "Business Manager"
    ELITE_MANAGER = "ELITE_MANAGER", "Elite Manager"
    SENIOR_MANAGER = "SENIOR_MANAGER", "Senior Manager"
    MANAGER = "MANAGER", "Manager"
    SOLAR_ADVISOR = "SOLAR_ADVISOR", "Solar Advisor"
    SOLAR_CONSULTANT = "SOLAR_CONSULTANT", "Solar Consultant"


# Backward compatible aliases used in legacy modules.
RoleCode.ADMIN = RoleCode.PARTNER
RoleCode.ADMINISTRATOR = RoleCode.ADMINISTRADOR
RoleCode.SALES_REP = RoleCode.SOLAR_CONSULTANT

ROLE_PRIORITY_MAP: dict[str, int] = {
    RoleCode.PARTNER: 100,
    RoleCode.ADMINISTRADOR: 90,
    RoleCode.JR_PARTNER: 85,
    RoleCode.BUSINESS_MANAGER: 80,
    RoleCode.ELITE_MANAGER: 70,
    RoleCode.SENIOR_MANAGER: 60,
    RoleCode.MANAGER: 50,
    RoleCode.SOLAR_ADVISOR: 40,
    RoleCode.SOLAR_CONSULTANT: 30,
}

GLOBAL_SCOPE_ROLES = {
    RoleCode.PARTNER,
    RoleCode.ADMINISTRADOR,
}

MANAGER_SCOPE_ROLES = {
    RoleCode.BUSINESS_MANAGER,
    RoleCode.ELITE_MANAGER,
    RoleCode.SENIOR_MANAGER,
    RoleCode.MANAGER,
    RoleCode.SOLAR_ADVISOR,
}

CONSULTANT_SCOPE_ROLES = {RoleCode.SOLAR_CONSULTANT}

ROLES_REQUIRING_BUSINESS_UNITS = MANAGER_SCOPE_ROLES | CONSULTANT_SCOPE_ROLES


class ModuleCode(models.TextChoices):
    USERS = "users", "Usuarios"
    SALES = "sales", "Ventas"
    REPORTS = "reports", "Reportes"
    SETTINGS = "settings", "Configuracion"
    COMMISSIONS = "commissions", "Comisiones"


class PermissionAction(models.TextChoices):
    VIEW = "view", "Ver"
    MANAGE = "manage", "Gestionar"
    APPROVE = "approve", "Aprobar"


DEFAULT_ROLE_PERMISSIONS: dict[str, dict[str, set[str]]] = {
    RoleCode.PARTNER: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.REPORTS: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.SETTINGS: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
    },
    RoleCode.ADMINISTRADOR: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.REPORTS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SETTINGS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
    },
    RoleCode.JR_PARTNER: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.REPORTS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SETTINGS: {PermissionAction.VIEW},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW, PermissionAction.APPROVE},
    },
    RoleCode.BUSINESS_MANAGER: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.REPORTS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SETTINGS: {PermissionAction.VIEW},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW, PermissionAction.MANAGE},
    },
    RoleCode.ELITE_MANAGER: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE, PermissionAction.APPROVE},
        ModuleCode.REPORTS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SETTINGS: {PermissionAction.VIEW},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW, PermissionAction.MANAGE},
    },
    RoleCode.SENIOR_MANAGER: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.REPORTS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SETTINGS: {PermissionAction.VIEW},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW, PermissionAction.MANAGE},
    },
    RoleCode.MANAGER: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.REPORTS: {PermissionAction.VIEW},
        ModuleCode.SETTINGS: {PermissionAction.VIEW},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW},
    },
    RoleCode.SOLAR_ADVISOR: {
        ModuleCode.USERS: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.REPORTS: {PermissionAction.VIEW},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW},
    },
    RoleCode.SOLAR_CONSULTANT: {
        ModuleCode.USERS: {PermissionAction.VIEW},
        ModuleCode.SALES: {PermissionAction.VIEW, PermissionAction.MANAGE},
        ModuleCode.REPORTS: {PermissionAction.VIEW},
        ModuleCode.COMMISSIONS: {PermissionAction.VIEW},
    },
}


def role_priority(role_code: str | None) -> int:
    return ROLE_PRIORITY_MAP.get(role_code or "", 0)


def is_global_role(role_code: str | None) -> bool:
    return role_code in GLOBAL_SCOPE_ROLES


def is_manager_role(role_code: str | None) -> bool:
    return role_code in MANAGER_SCOPE_ROLES


def is_consultant_role(role_code: str | None) -> bool:
    return role_code in CONSULTANT_SCOPE_ROLES
