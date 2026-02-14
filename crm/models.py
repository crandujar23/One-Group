from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

US_STATE_CHOICES = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
    ("DC", "District of Columbia"),
    ("PR", "Puerto Rico"),
]

ZIP_CODE_VALIDATOR = RegexValidator(
    regex=r"^\d{5}(-\d{4})?$",
    message="Use ZIP en formato 12345 o 12345-6789.",
)
PHONE_VALIDATOR = RegexValidator(
    regex=r"^\(\d{3}\)\d{3}-\d{4}$",
    message="Use teléfono en formato (XXX)XXX-XXXX.",
)


class SalesRep(models.Model):
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="sales_rep_profile")
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="sales_reps")
    tier = models.ForeignKey("rewards.Tier", on_delete=models.SET_NULL, null=True, blank=True, related_name="sales_reps")
    phone = models.CharField(max_length=13, blank=True, validators=[PHONE_VALIDATOR])
    second_last_name = models.CharField(max_length=150, blank=True)
    postal_address_line_1 = models.CharField(max_length=120, blank=True)
    postal_address_line_2 = models.CharField(max_length=120, blank=True)
    postal_city = models.CharField(max_length=80, blank=True)
    postal_state = models.CharField(max_length=2, choices=US_STATE_CHOICES, blank=True)
    postal_zip_code = models.CharField(max_length=10, blank=True, validators=[ZIP_CODE_VALIDATOR])
    physical_same_as_postal = models.BooleanField(default=False)
    physical_address_line_1 = models.CharField(max_length=120, blank=True)
    physical_address_line_2 = models.CharField(max_length=120, blank=True)
    physical_city = models.CharField(max_length=80, blank=True)
    physical_state = models.CharField(max_length=2, choices=US_STATE_CHOICES, blank=True)
    physical_zip_code = models.CharField(max_length=10, blank=True, validators=[ZIP_CODE_VALIDATOR])
    hire_date = models.DateField(null=True, blank=True)
    avatar = models.ImageField(
        upload_to="associates/avatars/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return self.user.get_username()


class Lead(models.Model):
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="leads")
    sales_rep = models.ForeignKey(SalesRep, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads")
    full_name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    source = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.full_name


class Sale(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="sales")
    sales_rep = models.ForeignKey(SalesRep, on_delete=models.CASCADE, related_name="sales")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="sales")
    plan = models.ForeignKey("rewards.CompensationPlan", on_delete=models.PROTECT, related_name="sales")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    external_reference = models.CharField(max_length=80, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Sale #{self.pk} - {self.sales_rep}"

    def clean(self):
        if self.plan_id and self.product_id and self.plan.product_id != self.product_id:
            raise ValidationError("The selected compensation plan does not belong to this product.")

        if self.product_id and self.business_unit_id != self.product.business_unit_id:
            raise ValidationError("Product must belong to the same business unit as the sale.")

        if self.sales_rep_id and self.business_unit_id != self.sales_rep.business_unit_id:
            raise ValidationError("SalesRep must belong to the same business unit as the sale.")

    def save(self, *args, **kwargs):
        if self.status == self.Status.CONFIRMED and self.confirmed_at is None:
            self.confirmed_at = timezone.now()
        super().save(*args, **kwargs)


class CallLog(models.Model):
    class ContactType(models.TextChoices):
        CALL = "CALL", "Call"
        EMAIL = "EMAIL", "Email"

    sales_rep = models.ForeignKey(SalesRep, on_delete=models.CASCADE, related_name="call_logs")
    sale = models.ForeignKey(Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name="call_logs")
    contact_type = models.CharField(max_length=12, choices=ContactType.choices)
    subject = models.CharField(max_length=120)
    notes = models.TextField(blank=True)
    next_action_date = models.DateField(null=True, blank=True)
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-logged_at"]

    def __str__(self) -> str:
        return f"{self.contact_type} - {self.subject}"
