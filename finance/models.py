from django.db import models


class Commission(models.Model):
    sale = models.OneToOneField("crm.Sale", on_delete=models.CASCADE, related_name="commission")
    sales_rep = models.ForeignKey("crm.SalesRep", on_delete=models.CASCADE, related_name="commissions")
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="commissions")
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    bonus_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-calculated_at"]

    def __str__(self) -> str:
        return f"Commission Sale #{self.sale_id}"


class FinancingCalculatorLink(models.Model):
    product = models.OneToOneField("inventory.Product", on_delete=models.CASCADE, related_name="financing_calculator")
    label = models.CharField(max_length=80, default="Calculator")
    url = models.URLField()
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.product} - {self.label}"


class FinancialReport(models.Model):
    business_unit = models.ForeignKey(
        "core.BusinessUnit",
        on_delete=models.CASCADE,
        related_name="financial_reports",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=120)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self) -> str:
        return self.title


class FinancingPartner(models.Model):
    class PartnerType(models.TextChoices):
        BANK = "BANK", "Banco"
        COOPERATIVE = "COOPERATIVE", "Cooperativa"
        OTHER = "OTHER", "Otro"

    name = models.CharField(max_length=120, unique=True)
    partner_type = models.CharField(max_length=16, choices=PartnerType.choices, default=PartnerType.BANK)
    business_units = models.ManyToManyField("core.BusinessUnit", related_name="financing_partners", blank=True)
    contact_name = models.CharField(max_length=120, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    services = models.TextField(
        blank=True,
        help_text="Describe los servicios financieros disponibles: préstamos personales, comerciales, líneas verdes, etc.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self) -> str:
        return self.name
