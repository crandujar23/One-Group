from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from core.rbac.constants import RoleCode

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


def get_default_salesrep_level_id() -> int | None:
    from core.models import Role

    role = Role.objects.filter(code=RoleCode.SOLAR_CONSULTANT).only("id").first()
    return role.id if role else None


class SalesRep(models.Model):
    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="sales_rep_profile")
    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="sales_reps")
    tier = models.ForeignKey("rewards.Tier", on_delete=models.SET_NULL, null=True, blank=True, related_name="sales_reps")
    sunrun_account_flag = models.BooleanField(default=False)
    zoho_id = models.CharField(max_length=80, blank=True)
    level = models.ForeignKey(
        "core.Role",
        on_delete=models.PROTECT,
        related_name="sales_reps",
        default=get_default_salesrep_level_id,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children_profiles",
    )
    consultant = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advisor_profiles",
    )
    teamleader = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manager_profiles",
    )
    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="senior_manager_profiles",
    )
    promanager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="elite_manager_profiles",
    )
    executivemanager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_manager_profiles",
    )
    jr_partner = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jr_partner_profiles",
    )
    partner = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_profiles",
    )
    parent_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    trainee_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    consultant_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    teamleader_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    manager_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    promanager_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    executivemanager_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    jr_partner_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    partner_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
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
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        level_name = self.level.name if self.level_id else "Sin nivel"
        return f"{self.user.get_username()} ({level_name})"

    def update_commission(self):
        # Placeholder hook for commission recalculation after hierarchy/level updates.
        # The current project computes compensation at sale-confirmation time.
        return None


class SalesrepLevel(models.Model):
    name = models.CharField(max_length=120, unique=True)
    sales_goal = models.PositiveIntegerField(default=0)
    indirect_sales_cap_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    sort_value = models.IntegerField(default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class LeadSource(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Lead(models.Model):
    class LeadKind(models.TextChoices):
        RESIDENTIAL = "residential", "Residencial"
        COMMERCIAL = "commercial", "Comercial"

    class Status(models.TextChoices):
        NUEVO = "Nuevo", "Nuevo"
        CONTACTADO = "Contactado", "Contactado"
        CALIFICADO = "Calificado", "Calificado"
        DESCALIFICADO = "Descalificado", "Descalificado"
        PROPUESTA_ENVIADA = "Propuesta Enviada", "Propuesta Enviada"
        EN_NEGOCIACION = "En Negociación", "En Negociación"
        VENDIDO = "Vendido", "Vendido"
        PERDIDO = "Perdido", "Perdido"
        # Compatibilidad con valores legacy existentes
        NEW = "NEW", "Nuevo (legacy)"
        PENDING = "PENDING", "Pendiente (legacy)"
        CONTACTED = "CONTACTED", "Contactado (legacy)"
        QUALIFIED = "QUALIFIED", "Calificado (legacy)"
        CLOSED = "CLOSED", "Cerrado (legacy)"

    business_unit = models.ForeignKey("core.BusinessUnit", on_delete=models.CASCADE, related_name="leads")
    sales_rep = models.ForeignKey(SalesRep, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads")
    full_name = models.CharField(max_length=120)
    customer_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    customer_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    customer_phone2 = models.CharField(max_length=30, blank=True)
    message = models.TextField(blank=True)
    source = models.CharField(max_length=80, blank=True)
    lead_source = models.CharField(max_length=80, blank=True)
    lead_kind = models.CharField(max_length=20, choices=LeadKind.choices, default=LeadKind.RESIDENTIAL, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NUEVO, db_index=True)
    city = models.CharField(max_length=80, blank=True)
    customer_city = models.CharField(max_length=80, blank=True)
    address = models.CharField(max_length=200, blank=True)
    customer_address = models.CharField(max_length=200, blank=True)
    customer_postal_code = models.CharField(max_length=20, blank=True)
    customer_country = models.CharField(max_length=80, blank=True)
    roof_type = models.CharField(max_length=80, blank=True)
    owner_name = models.CharField(max_length=120, blank=True)
    owns_property = models.CharField(max_length=5, choices=[("SI", "SI"), ("NO", "NO")], blank=True)
    electricity_bill = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    system_size = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    consumo_promedio_kwh = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    system_size_kw = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monthly_consumption_history = models.TextField(blank=True, default="[]")
    electricity_invoice_language = models.CharField(max_length=40, blank=True)
    id_consumo_historial = models.TextField(blank=True, default="[]")
    hsp = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    eff = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    offset = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    last_4_ssn_luma = models.CharField(max_length=4, blank=True)
    account_occupation_luma = models.CharField(max_length=120, blank=True)
    marital_status = models.CharField(max_length=40, blank=True)
    username_luma = models.CharField(max_length=120, blank=True)
    password_luma = models.CharField(max_length=120, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    customer_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    customer_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    invoice_pdf = models.FileField(upload_to="leads/invoices/", blank=True, null=True)
    electricity_invoice_pdf = models.FileField(upload_to="leads/invoices/", blank=True, null=True)
    electricity_invoice_page1_img = models.ImageField(upload_to="leads/invoices/", blank=True, null=True)
    electricity_invoice_page2_img = models.ImageField(upload_to="leads/invoices/", blank=True, null=True)
    electricity_invoice_page3_img = models.ImageField(upload_to="leads/invoices/", blank=True, null=True)
    electricity_invoice_page4_img = models.ImageField(upload_to="leads/invoices/", blank=True, null=True)
    use_invoice_images = models.BooleanField(default=False)
    electricity_invoice_hash = models.CharField(max_length=64, blank=True, db_index=True)
    invoice_hash = models.CharField(max_length=64, blank=True, db_index=True)
    invoice_name = models.CharField(max_length=160, blank=True)
    account_number = models.CharField(max_length=80, blank=True, db_index=True)
    meter_number = models.CharField(max_length=80, blank=True, db_index=True)
    location_id = models.CharField(max_length=80, blank=True, db_index=True)
    sunrun_contract_signed = models.BooleanField(default=False)
    sunrun_call_completed = models.BooleanField(default=False)
    loan_reference_number = models.CharField(max_length=120, blank=True)
    financing = models.CharField(max_length=120, blank=True)
    battery_option = models.CharField(max_length=120, blank=True)
    total_project_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    proof_title = models.FileField(upload_to="leads/documents/", blank=True, null=True)
    other_documents = models.FileField(upload_to="leads/documents/", blank=True, null=True)
    assigned_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    acceptance_deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    work_deadline = models.DateTimeField(null=True, blank=True)
    is_accepted = models.BooleanField(default=True, db_index=True)
    duplicate_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.full_name

    @property
    def create_date(self):
        return self.created_at

    @property
    def status_display(self) -> str:
        return self.get_status_display()

    def acceptance_time_left(self) -> int:
        if not self.acceptance_deadline:
            return -1
        delta = self.acceptance_deadline - timezone.now()
        return max(int(delta.total_seconds()), 0)


class LeadNote(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, related_name="lead_notes")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "crm_lead_note_v2"


class LeadActivityLog(models.Model):
    class ActivityType(models.TextChoices):
        VIEW = "VIEW", "Ver detalle"
        PHONE = "PHONE", "Llamada"
        EMAIL = "EMAIL", "Correo"
        SMS = "SMS", "SMS"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        ASSIGN = "ASSIGN", "Asignacion"
        ACCEPT = "ACCEPT", "Aceptacion"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activity_logs")
    actor = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, related_name="lead_activity_logs")
    activity_type = models.CharField(max_length=24, choices=ActivityType.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "crm_lead_activity_log_v2"


class InvoiceDuplicateReviewRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        APPROVED = "APPROVED", "Aprobada"
        REJECTED = "REJECTED", "Rechazada"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="duplicate_review_requests")
    requester = models.ForeignKey(SalesRep, on_delete=models.CASCADE, related_name="duplicate_review_requests")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    reason = models.TextField(blank=True)
    resolver = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_duplicate_reviews",
    )
    resolver_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "crm_invoice_duplicate_review_request_v2"


class InvoiceDuplicateOverride(models.Model):
    requester = models.ForeignKey(SalesRep, on_delete=models.CASCADE, related_name="invoice_duplicate_overrides")
    account_number = models.CharField(max_length=80, blank=True, db_index=True)
    meter_number = models.CharField(max_length=80, blank=True, db_index=True)
    location_id = models.CharField(max_length=80, blank=True, db_index=True)
    invoice_hash = models.CharField(max_length=64, blank=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    used_on_lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="consumed_overrides")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "crm_invoice_duplicate_override_v2"


class CrmDeal(models.Model):
    class DealKind(models.TextChoices):
        RESIDENTIAL = "residential", "Residencial"
        COMMERCIAL = "commercial", "Comercial"
        PORTABLE_BATTERY = "portable_battery", "Portable Battery"
        AUTOS = "autos", "Autos"

    class Stage(models.TextChoices):
        PLANNED = "planned", "Planificado"
        APPROVED = "approved", "Aprobado"
        SIGNED = "signed", "Firmado"
        INSTALLED = "installed", "Instalado"
        CLOSED = "closed", "Cerrado"

    deal_kind = models.CharField(max_length=40, choices=DealKind.choices, default=DealKind.RESIDENTIAL, db_index=True)
    salesrep = models.ForeignKey(SalesRep, on_delete=models.SET_NULL, null=True, blank=True, related_name="crm_deals")
    imported_salesrep_name = models.CharField(max_length=180, blank=True)
    imported_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="imported_crm_deals")
    imported_at = models.DateTimeField(null=True, blank=True)

    customer_name = models.CharField(max_length=160, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_city = models.CharField(max_length=80, blank=True)
    customer_address = models.CharField(max_length=200, blank=True)

    proposal_id = models.CharField(max_length=120, blank=True, db_index=True)
    sunrun_service_contract_id = models.CharField(max_length=120, blank=True, db_index=True)
    system_size = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    epc_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    epc_base = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    epc_table = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    epc_adjustment = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    stage = models.CharField(max_length=40, choices=Stage.choices, default=Stage.PLANNED, db_index=True)

    closing_date = models.DateField(null=True, blank=True, db_index=True)
    sr_signoff_date = models.DateField(null=True, blank=True)
    customer_sign_off_date = models.DateField(null=True, blank=True)
    final_completion_date = models.DateField(null=True, blank=True)

    consultant_name = models.CharField(max_length=160, blank=True)
    advisor_name = models.CharField(max_length=160, blank=True)
    manager_name = models.CharField(max_length=160, blank=True)
    senior_manager_name = models.CharField(max_length=160, blank=True)
    elite_manager_name = models.CharField(max_length=160, blank=True)
    business_manager_name = models.CharField(max_length=160, blank=True)
    jr_partner_name = models.CharField(max_length=160, blank=True)
    partner_name = models.CharField(max_length=160, blank=True)

    consultant_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    advisor_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    manager_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    senior_manager_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    elite_manager_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    business_manager_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    jr_partner_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    partner_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-closing_date", "-id"]
        permissions = (
            ("can_reassign_deal", "Can reassign deals"),
        )

    def __str__(self) -> str:
        return self.customer_name or self.proposal_id or f"Deal {self.pk}"


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
