from django.db import models


class Product(models.Model):
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=60, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("business_unit", "name")

    def __str__(self) -> str:
        return self.name


class BaseInventoryItem(models.Model):
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=60, unique=True)
    quantity = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Supply(BaseInventoryItem):
    pass


class Equipment(BaseInventoryItem):
    pass


class SoftwareAsset(BaseInventoryItem):
    license_key = models.CharField(max_length=120, blank=True)


class MarketingMaterial(BaseInventoryItem):
    channel = models.CharField(max_length=80, blank=True)
