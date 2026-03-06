from django.contrib import admin
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone

from crm.forms import SalesrepLevelAdminForm
from crm.forms import SalesRepAdminForm
from crm.models import CallLog, Lead, Sale, SalesRep
from crm.models import SalesrepLevel


@admin.register(SalesRep)
class SalesRepAdmin(admin.ModelAdmin):
    form = SalesRepAdminForm
    list_display = ("user", "level", "business_unit", "tier", "is_active", "modified_at")
    list_filter = ("level", "business_unit", "tier", "is_active")
    search_fields = ("user__username", "user__email", "zoho_id")
    autocomplete_fields = (
        "user",
        "business_unit",
        "tier",
        "level",
        "parent",
        "consultant",
        "teamleader",
        "manager",
        "promanager",
        "executivemanager",
        "jr_partner",
        "partner",
    )
    actions = ("recalculate_commission_structure",)
    fieldsets = (
        (
            "Base",
            {
                "fields": (
                    "user",
                    "sunrun_account_flag",
                    "level",
                    "zoho_id",
                    "business_unit",
                    "tier",
                    "is_active",
                )
            },
        ),
        ("Sponsor Chain", {"fields": ("parent", "parent_rate")}),
        ("Solar Consultant", {"fields": ("trainee_rate",)}),
        ("Solar Advisor", {"fields": ("consultant", "consultant_rate")}),
        ("Manager", {"fields": ("teamleader", "teamleader_rate")}),
        ("Senior Manager", {"fields": ("manager", "manager_rate")}),
        ("Elite Manager", {"fields": ("promanager", "promanager_rate")}),
        ("Business Manager", {"fields": ("executivemanager", "executivemanager_rate")}),
        ("Jr Partner", {"fields": ("jr_partner", "jr_partner_rate")}),
        ("Partner", {"fields": ("partner", "partner_rate")}),
        (
            "Metadatos",
            {
                "fields": (
                    "created_at",
                    "modified_at",
                )
            },
        ),
    )
    readonly_fields = ("created_at", "modified_at")

    @admin.action(description="Recalcular estructura de comisiones")
    def recalculate_commission_structure(self, request, queryset):
        # Hook administrativo separado: no se ejecuta durante save individual.
        updated = queryset.update(modified_at=timezone.now())
        self.message_user(
            request,
            f"Se ejecuto la accion de recalculo para {updated} perfil(es).",
            level=messages.SUCCESS,
        )

    def response_change(self, request, obj):
        response = super().response_change(request, obj)
        changelist_filters = request.GET.get("_changelist_filters")
        if "_save" in request.POST and changelist_filters:
            changelist_url = reverse("admin:crm_salesrep_changelist")
            return HttpResponseRedirect(f"{changelist_url}?{changelist_filters}")
        return response


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "business_unit", "sales_rep", "source", "created_at")
    list_filter = ("business_unit", "source")
    search_fields = ("full_name", "email", "phone")


@admin.register(SalesrepLevel)
class SalesrepLevelAdmin(admin.ModelAdmin):
    form = SalesrepLevelAdminForm
    list_display = ("name", "sales_goal", "indirect_sales_cap_percentage")
    search_fields = ("name",)
    ordering = ("id",)


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "business_unit", "sales_rep", "product", "plan", "amount", "status", "created_at")
    list_filter = ("business_unit", "status", "plan")
    search_fields = ("external_reference", "sales_rep__user__username", "product__name")


@admin.register(CallLog)
class CallLogAdmin(admin.ModelAdmin):
    list_display = ("sales_rep", "contact_type", "subject", "sale", "logged_at")
    list_filter = ("contact_type", "sales_rep__business_unit")
    search_fields = ("subject", "notes", "sales_rep__user__username")
