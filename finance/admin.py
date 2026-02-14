from django.contrib import admin

from finance.models import Commission, FinancialReport, FinancingCalculatorLink


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = ("sale", "sales_rep", "business_unit", "commission_amount", "bonus_amount", "total_amount", "calculated_at")
    list_filter = ("business_unit",)
    search_fields = ("sales_rep__user__username", "sale__external_reference")


@admin.register(FinancingCalculatorLink)
class FinancingCalculatorLinkAdmin(admin.ModelAdmin):
    list_display = ("product", "label", "url", "is_active")
    list_filter = ("is_active", "product__business_unit")
    search_fields = ("product__name", "label")


@admin.register(FinancialReport)
class FinancialReportAdmin(admin.ModelAdmin):
    list_display = ("title", "business_unit", "period_start", "period_end", "generated_at")
    list_filter = ("business_unit",)
    search_fields = ("title", "notes")
