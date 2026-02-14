from django.contrib import admin

from inventory.models import Equipment, MarketingMaterial, Product, SoftwareAsset, Supply


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "sku", "price", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name", "sku")


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "sku", "quantity", "unit_cost", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name", "sku")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "sku", "quantity", "unit_cost", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name", "sku")


@admin.register(SoftwareAsset)
class SoftwareAssetAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "sku", "quantity", "license_key", "is_active")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name", "sku", "license_key")


@admin.register(MarketingMaterial)
class MarketingMaterialAdmin(admin.ModelAdmin):
    list_display = ("name", "business_unit", "sku", "quantity", "channel", "is_active")
    list_filter = ("business_unit", "is_active", "channel")
    search_fields = ("name", "sku", "channel")
