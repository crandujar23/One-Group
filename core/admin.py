from django.contrib import admin

from core.models import BusinessUnit
from core.models import ModulePermission
from core.models import Role
from core.models import RoleChangeAudit
from core.models import RoleModulePermission
from core.models import UserProfile


@admin.register(BusinessUnit)
class BusinessUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    search_fields = ("name", "code")
    list_filter = ("is_active",)


class RoleModulePermissionInline(admin.TabularInline):
    model = RoleModulePermission
    extra = 0
    autocomplete_fields = ("permission",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "priority", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    ordering = ("priority",)
    inlines = (RoleModulePermissionInline,)


@admin.register(ModulePermission)
class ModulePermissionAdmin(admin.ModelAdmin):
    list_display = ("module", "action", "created_at")
    list_filter = ("module", "action")
    search_fields = ("module", "action")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "role_ref", "manager", "business_unit")
    list_filter = ("role", "role_ref", "business_unit")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user", "role_ref", "manager", "business_unit")
    filter_horizontal = ("business_units",)


@admin.register(RoleChangeAudit)
class RoleChangeAuditAdmin(admin.ModelAdmin):
    list_display = ("target", "previous_role", "new_role", "actor", "created_at")
    list_filter = ("previous_role", "new_role", "created_at")
    search_fields = ("target__username", "actor__username", "reason")
    readonly_fields = ("actor", "target", "previous_role", "new_role", "reason", "created_at")
