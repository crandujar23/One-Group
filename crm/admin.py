from django.contrib import admin

from crm.models import CallLog, Lead, Sale, SalesRep


@admin.register(SalesRep)
class SalesRepAdmin(admin.ModelAdmin):
    list_display = ("user", "business_unit", "tier", "is_active")
    list_filter = ("business_unit", "tier", "is_active")
    search_fields = ("user__username", "user__email")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "business_unit", "sales_rep", "source", "created_at")
    list_filter = ("business_unit", "source")
    search_fields = ("full_name", "email", "phone")


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
