from django.contrib import admin

from rewards.models import (
    Bundle,
    CompensationPlan,
    PlanTierRule,
    Prize,
    Redemption,
    RewardPoint,
    Tier,
)


@admin.register(Tier)
class TierAdmin(admin.ModelAdmin):
    list_display = ("name", "rank")
    search_fields = ("name",)


@admin.register(CompensationPlan)
class CompensationPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "product", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name", "product__name")


@admin.register(PlanTierRule)
class PlanTierRuleAdmin(admin.ModelAdmin):
    list_display = ("plan", "tier", "commission_percent", "bonus_percent", "points_per_dollar")
    list_filter = ("plan", "tier")


@admin.register(RewardPoint)
class RewardPointAdmin(admin.ModelAdmin):
    list_display = ("sales_rep", "sale", "points", "created_at")
    list_filter = ("sales_rep__business_unit",)
    search_fields = ("sales_rep__user__username",)


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "discount_percent", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name",)


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "points_cost", "stock", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name",)


@admin.register(Redemption)
class RedemptionAdmin(admin.ModelAdmin):
    list_display = ("sales_rep", "prize", "points_spent", "status", "requested_at")
    list_filter = ("status", "sales_rep__business_unit")
    search_fields = ("sales_rep__user__username", "prize__name")
