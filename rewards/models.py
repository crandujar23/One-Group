from django.db import models


class Tier(models.Model):
    name = models.CharField(max_length=80, unique=True)
    rank = models.PositiveIntegerField(unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["rank"]

    def __str__(self) -> str:
        return self.name


class CompensationPlan(models.Model):
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="compensation_plans")
    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE, related_name="compensation_plans")
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["business_unit__name", "product__name", "name"]
        unique_together = ("product", "name")

    def __str__(self) -> str:
        return f"{self.product.name} - {self.name}"


class PlanTierRule(models.Model):
    plan = models.ForeignKey(CompensationPlan, on_delete=models.CASCADE, related_name="tier_rules")
    tier = models.ForeignKey(Tier, on_delete=models.CASCADE, related_name="plan_rules")
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    bonus_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    points_per_dollar = models.DecimalField(max_digits=8, decimal_places=2, default=1)

    class Meta:
        unique_together = ("plan", "tier")
        ordering = ["plan", "tier__rank"]

    def __str__(self) -> str:
        return f"{self.plan} / {self.tier}"


class RewardPoint(models.Model):
    sales_rep = models.ForeignKey("crm.SalesRep", on_delete=models.CASCADE, related_name="reward_points")
    sale = models.OneToOneField("crm.Sale", on_delete=models.CASCADE, related_name="reward_point")
    points = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.sales_rep} - {self.points}"


class Bundle(models.Model):
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="bundles")
    name = models.CharField(max_length=120)
    products = models.ManyToManyField("inventory.Product", related_name="bundles", blank=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("business_unit", "name")

    def __str__(self) -> str:
        return self.name


class Prize(models.Model):
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="prizes")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    points_cost = models.DecimalField(max_digits=12, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("business_unit", "name")

    def __str__(self) -> str:
        return self.name


class Redemption(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        FULFILLED = "FULFILLED", "Fulfilled"

    sales_rep = models.ForeignKey("crm.SalesRep", on_delete=models.CASCADE, related_name="redemptions")
    prize = models.ForeignKey(Prize, on_delete=models.PROTECT, related_name="redemptions")
    points_spent = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-requested_at"]

    def save(self, *args, **kwargs):
        if self.points_spent is None:
            self.points_spent = self.prize.points_cost
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.sales_rep} - {self.prize}"
