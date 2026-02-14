from django.contrib import admin

from core.models import BusinessUnit, UserProfile


@admin.register(BusinessUnit)
class BusinessUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "created_at")
    search_fields = ("name", "code")
    list_filter = ("is_active",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "business_unit")
    list_filter = ("role", "business_unit")
    search_fields = ("user__username", "user__email")
