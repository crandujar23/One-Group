from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from decimal import InvalidOperation
import re
from pathlib import Path

from crm.models import CrmDeal
from crm.models import Lead
from crm.models import LeadNote
from crm.models import SalesrepLevel
from crm.models import SalesRep


class SalesRepAdminForm(forms.ModelForm):
    class Meta:
        model = SalesRep
        fields = "__all__"
        labels = {
            "user": "Usuario",
            "sunrun_account_flag": "Indicador de cuenta Sunrun",
            "level": "Nivel",
            "zoho_id": "ID de integración (Zoho)",
            "parent": "Sponsor (Parent)",
            "parent_rate": "Sponsor rate",
            "trainee_rate": "Solar Consultant rate",
            "consultant": "Solar Advisor",
            "consultant_rate": "Solar Advisor rate",
            "teamleader": "Manager",
            "teamleader_rate": "Manager rate",
            "manager": "Senior Manager",
            "manager_rate": "Senior Manager rate",
            "promanager": "Elite Manager",
            "promanager_rate": "Elite Manager rate",
            "executivemanager": "Business Manager",
            "executivemanager_rate": "Business Manager rate",
            "jr_partner": "Jr Partner",
            "jr_partner_rate": "Jr Partner rate",
            "partner": "Partner",
            "partner_rate": "Partner rate",
        }


class SalesrepLevelAdminForm(forms.ModelForm):
    class Meta:
        model = SalesrepLevel
        fields = "__all__"

    def clean_sales_goal(self):
        value = self.cleaned_data["sales_goal"]
        if value < 0:
            raise forms.ValidationError("La meta de ventas debe ser un entero mayor o igual a 0.")
        return value

    def clean_indirect_sales_cap_percentage(self):
        value = self.cleaned_data["indirect_sales_cap_percentage"]
        if value < 0 or value > 100:
            raise forms.ValidationError("El porcentaje debe estar entre 0 y 100.")
        return value


class LeadForm(forms.ModelForm):
    PR_MUNICIPALITIES = [
        "Adjuntas", "Aguada", "Aguadilla", "Aguas Buenas", "Aibonito", "Anasco", "Arecibo", "Arroyo",
        "Barceloneta", "Barranquitas", "Bayamon", "Cabo Rojo", "Caguas", "Camuy", "Canovanas", "Carolina",
        "Catano", "Cayey", "Ceiba", "Ciales", "Cidra", "Coamo", "Comerio", "Corozal", "Culebra",
        "Dorado", "Fajardo", "Florida", "Guanica", "Guayama", "Guayanilla", "Guaynabo", "Gurabo",
        "Hatillo", "Hormigueros", "Humacao", "Isabela", "Jayuya", "Juana Diaz", "Juncos",
        "Lajas", "Lares", "Las Marias", "Las Piedras", "Loiza", "Luquillo",
        "Manati", "Maricao", "Maunabo", "Mayaguez", "Moca", "Morovis",
        "Naguabo", "Naranjito",
        "Orocovis",
        "Patillas", "Penuelas", "Ponce",
        "Quebradillas",
        "Rincon", "Rio Grande",
        "Sabana Grande", "Salinas", "San German", "San Juan", "San Lorenzo", "San Sebastian",
        "Santa Isabel", "Toa Alta", "Toa Baja", "Trujillo Alto",
        "Utuado",
        "Vega Alta", "Vega Baja", "Vieques", "Villalba",
        "Yabucoa", "Yauco",
    ]
    CUSTOMER_CITY_CHOICES = [("", "Selecciona un pueblo")] + [(city, city) for city in PR_MUNICIPALITIES]
    COUNTRY_CHOICES = [
        ("PR", "PR"),
    ]
    STATUS_OPTIONS = [
        ("Nuevo", "Nuevo"),
        ("Contactado", "Contactado"),
        ("Calificado", "Calificado"),
        ("Descalificado", "Descalificado"),
        ("Propuesta Enviada", "Propuesta Enviada"),
        ("En Negociación", "En Negociación"),
        ("Vendido", "Vendido"),
        ("Perdido", "Perdido"),
    ]
    LEAD_SOURCE_OPTIONS = [
        ("", "---------"),
        ("Base de Datos", "Base de Datos"),
        ("Evento/Feria", "Evento/Feria"),
        ("Facebook Ads", "Facebook Ads"),
        ("Google Ads", "Google Ads"),
        ("Instagram", "Instagram"),
        ("Landing Page", "Landing Page"),
        ("Lead Generation", "Lead Generation"),
        ("Llamada Entrante", "Llamada Entrante"),
        ("Puerta a Puerta", "Puerta a Puerta"),
        ("Referido Asociado", "Referido Asociado"),
        ("Referido Cliente", "Referido Cliente"),
        ("TikTok", "TikTok"),
        ("Web Form", "Web Form"),
        ("WhatsApp", "WhatsApp"),
    ]
    status = forms.CharField(
        required=True,
        widget=forms.Select(choices=STATUS_OPTIONS),
    )
    lead_source = forms.CharField(
        required=False,
        widget=forms.Select(choices=LEAD_SOURCE_OPTIONS),
    )
    customer_city = forms.CharField(
        required=False,
        widget=forms.Select(choices=CUSTOMER_CITY_CHOICES),
    )
    customer_country = forms.CharField(
        required=False,
        widget=forms.Select(choices=COUNTRY_CHOICES),
    )
    ROOF_TYPE_CHOICES = [
        ("", "Selecciona tipo de techo"),
        ("Techo en Cemento", "Techo en Cemento"),
        ("Techo en Galvalume", "Techo en Galvalume"),
    ]
    roof_type = forms.ChoiceField(choices=ROOF_TYPE_CHOICES, required=False)

    class Meta:
        model = Lead
        fields = [
            "status",
            "lead_source",
            "customer_name",
            "customer_phone",
            "customer_phone2",
            "customer_address",
            "customer_city",
            "customer_postal_code",
            "customer_country",
            "customer_latitude",
            "customer_longitude",
            "customer_email",
            "roof_type",
            "owns_property",
            "electricity_bill",
            "system_size",
            "electricity_invoice_pdf",
            "use_invoice_images",
            "electricity_invoice_page1_img",
            "electricity_invoice_page2_img",
            "electricity_invoice_page3_img",
            "electricity_invoice_page4_img",
            "electricity_invoice_language",
            "invoice_name",
            "account_number",
            "meter_number",
            "location_id",
            "consumo_promedio_kwh",
            "id_consumo_historial",
            "hsp",
            "eff",
            "offset",
            "last_4_ssn_luma",
            "account_occupation_luma",
            "marital_status",
            "username_luma",
            "password_luma",
            "sunrun_contract_signed",
            "sunrun_call_completed",
            "loan_reference_number",
            "financing",
            "battery_option",
            "total_project_cost",
            "proof_title",
            "other_documents",
            "work_deadline",
        ]
        widgets = {
            "work_deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "id_consumo_historial": forms.HiddenInput(attrs={"id": "id_consumo_historial"}),
            "electricity_bill": forms.TextInput(
                attrs={"inputmode": "decimal", "autocomplete": "off", "placeholder": "$0,000.00"}
            ),
            "system_size": forms.TextInput(
                attrs={"inputmode": "decimal", "autocomplete": "off", "placeholder": "0,000"}
            ),
            "customer_postal_code": forms.TextInput(
                attrs={"inputmode": "numeric", "autocomplete": "off", "placeholder": "00000-0000"}
            ),
        }

    def __init__(self, *args, **kwargs):
        data = args[0] if args else kwargs.get("data")
        if data is not None:
            mutable_data = data.copy()
            roof_value = (mutable_data.get("roof_type") or "").strip().lower()
            if roof_value in {"hormigon", "hormigón"}:
                mutable_data["roof_type"] = "Techo en Cemento"
            source_value = (mutable_data.get("lead_source") or "").strip().lower()
            source_legacy_map = {
                "meta": "Facebook Ads",
                "facebook": "Facebook Ads",
                "fb ads": "Facebook Ads",
                "google": "Google Ads",
                "tiktok": "TikTok",
                "webform": "Web Form",
            }
            if source_value in source_legacy_map:
                mutable_data["lead_source"] = source_legacy_map[source_value]
            if args:
                args = (mutable_data,) + args[1:]
            else:
                kwargs["data"] = mutable_data
        super().__init__(*args, **kwargs)
        if not (self.initial.get("status") or getattr(self.instance, "status", "")):
            self.initial["status"] = "Nuevo"
        # Keep compatibility for old roof values that may exist in DB.
        current = (self.initial.get("roof_type") or getattr(self.instance, "roof_type", "") or "").strip()
        if current.lower() in {"hormigon", "hormigón"}:
            current = "Techo en Cemento"
            self.initial["roof_type"] = current
        choices = list(self.fields["roof_type"].choices)
        values = {value for value, _ in choices}
        if current and current not in values:
            choices.append((current, current))
            self.fields["roof_type"].choices = choices
        current_source = (self.initial.get("lead_source") or getattr(self.instance, "lead_source", "") or "").strip()
        source_choices = list(self.fields["lead_source"].widget.choices)
        source_values = {value for value, _ in source_choices}
        if current_source and current_source not in source_values:
            source_choices.append((current_source, current_source))
            self.fields["lead_source"].widget.choices = source_choices
        current_city = (self.initial.get("customer_city") or getattr(self.instance, "customer_city", "") or "").strip()
        city_choices = list(self.fields["customer_city"].widget.choices)
        city_values = {value for value, _ in city_choices}
        if current_city and current_city not in city_values:
            city_choices.append((current_city, current_city))
            self.fields["customer_city"].widget.choices = city_choices
        if not (self.initial.get("customer_country") or getattr(self.instance, "customer_country", "")):
            self.initial["customer_country"] = "PR"

    def clean_roof_type(self):
        value = (self.cleaned_data.get("roof_type") or "").strip()
        if not value:
            return ""
        normalized = value.lower()
        if normalized in {"cemento", "techo en cemento"}:
            return "Techo en Cemento"
        if normalized in {"hormigon", "hormigón"}:
            return "Techo en Cemento"
        if normalized in {"galvalume", "techo en galvalume"}:
            return "Techo en Galvalume"
        return value

    def clean_status(self):
        value = (self.cleaned_data.get("status") or "").strip()
        if not value:
            return "Nuevo"
        legacy_map = {
            "NEW": "Nuevo",
            "PENDING": "Contactado",
            "CONTACTED": "Contactado",
            "QUALIFIED": "Calificado",
            "CLOSED": "Vendido",
        }
        return legacy_map.get(value, value)

    def clean_electricity_bill(self):
        value = self.cleaned_data.get("electricity_bill")
        if value in (None, ""):
            return None
        if isinstance(value, Decimal):
            return value
        raw = str(value).strip().replace("$", "").replace(",", "")
        if not raw:
            return None
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("Monto de factura invalido.") from exc

    def clean_system_size(self):
        value = self.cleaned_data.get("system_size")
        if value in (None, ""):
            return None
        if isinstance(value, Decimal):
            return value
        raw = str(value).strip().replace(",", "")
        if not raw:
            return None
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("Tamano de sistema invalido.") from exc

    def clean_id_consumo_historial(self):
        value = (self.cleaned_data.get("id_consumo_historial") or "").strip()
        if not value:
            return "[]"
        try:
            import json

            data = json.loads(value)
        except Exception as exc:
            raise ValidationError("Historial mensual invalido.") from exc
        if not isinstance(data, list):
            raise ValidationError("El historial mensual debe ser una lista.")
        return value

    def clean(self):
        cleaned = super().clean()
        use_images = bool(cleaned.get("use_invoice_images"))
        pdf = cleaned.get("electricity_invoice_pdf")
        page1 = cleaned.get("electricity_invoice_page1_img")
        page2 = cleaned.get("electricity_invoice_page2_img")
        instance = getattr(self, "instance", None)
        existing_page1 = bool(getattr(instance, "electricity_invoice_page1_img", None)) if instance else False
        existing_page2 = bool(getattr(instance, "electricity_invoice_page2_img", None)) if instance else False

        if use_images:
            if not (page1 or existing_page1) or not (page2 or existing_page2):
                raise ValidationError("Debes subir ambas imagenes de factura cuando no uses PDF.")
        # Factura PDF no es obligatoria.
        return cleaned


class LeadNoteForm(forms.ModelForm):
    class Meta:
        model = LeadNote
        fields = ["body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "placeholder": "Escribe una nota..."})}


class LeadGenerationPublicForm(forms.ModelForm):
    PHONE_PATTERN = re.compile(r"^\(\d{3}\)\d{3}-\d{4}$")
    PR_MUNICIPALITIES = LeadForm.PR_MUNICIPALITIES
    CITY_CHOICES = [("", "Selecciona un pueblo")] + [(city, city) for city in PR_MUNICIPALITIES]
    ROOF_CHOICES = [
        ("", "Seleccione"),
        ("Cemento", "Cemento"),
        ("Galvalum", "Galvalum"),
    ]
    OWNS_PROPERTY_CHOICES = [
        ("", "Seleccione"),
        ("true", "SI"),
        ("false", "NO"),
    ]

    customer_city = forms.ChoiceField(choices=CITY_CHOICES, required=True)
    roof_type = forms.ChoiceField(choices=ROOF_CHOICES, required=False)
    owns_property = forms.ChoiceField(choices=OWNS_PROPERTY_CHOICES, required=False)
    electricity_bill = forms.CharField(required=False)

    class Meta:
        model = Lead
        fields = [
            "customer_name",
            "customer_phone",
            "customer_email",
            "customer_address",
            "customer_city",
            "roof_type",
            "owns_property",
            "electricity_bill",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            current = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{current} {css}".strip()
        self.fields["customer_name"].required = True
        self.fields["customer_phone"].required = True
        self.fields["customer_city"].required = True

    def clean_customer_name(self):
        value = (self.cleaned_data.get("customer_name") or "").strip()
        if not value:
            raise ValidationError("El nombre del cliente es obligatorio.")
        return value

    def clean_customer_phone(self):
        value = (self.cleaned_data.get("customer_phone") or "").strip()
        if not self.PHONE_PATTERN.match(value):
            raise ValidationError("Use formato (XXX)XXX-XXXX.")
        return value

    def clean_customer_city(self):
        value = (self.cleaned_data.get("customer_city") or "").strip()
        if not value:
            raise ValidationError("La ciudad es obligatoria.")
        return value

    def clean_owns_property(self):
        value = (self.cleaned_data.get("owns_property") or "").strip().lower()
        if value == "true":
            return "SI"
        if value == "false":
            return "NO"
        return ""

    def clean_electricity_bill(self):
        value = self.cleaned_data.get("electricity_bill")
        if value in (None, ""):
            return None
        if isinstance(value, Decimal):
            return value
        raw = str(value).strip().replace("$", "").replace(" ", "")
        if not raw:
            return None
        if "," in raw and "." in raw:
            raw = raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            normalized = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("Ingresa un monto valido. Ejemplo: 245.50") from exc
        if normalized < 0:
            raise ValidationError("Ingresa un monto valido. Ejemplo: 245.50")
        return normalized


class CrmDealSalesrepForm(forms.ModelForm):
    class Meta:
        model = CrmDeal
        fields = ["salesrep"]

    def __init__(self, *args, **kwargs):
        salesrep_queryset = kwargs.pop("salesrep_queryset", SalesRep.objects.none())
        super().__init__(*args, **kwargs)
        self.fields["salesrep"].queryset = salesrep_queryset
        self.fields["salesrep"].required = False
        self.fields["salesrep"].label = "Asociado"
        self.fields["salesrep"].widget.attrs["class"] = "form-select"


class CrmDealExcelUploadForm(forms.Form):
    ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}

    report_file = forms.FileField(label="Informe de adjudicacion (Excel)")
    sheet_name = forms.CharField(label="Hoja (opcional)", max_length=120, required=False)
    dry_run = forms.BooleanField(label="Solo validar (no guardar cambios)", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["report_file"].widget.attrs["class"] = "form-control"
        self.fields["sheet_name"].widget.attrs["class"] = "form-control"
        self.fields["sheet_name"].widget.attrs["placeholder"] = "Ej. FEBRERO 2026"
        self.fields["dry_run"].widget.attrs["class"] = "form-check-input"

    def clean_report_file(self):
        file_obj = self.cleaned_data.get("report_file")
        extension = Path((getattr(file_obj, "name", "") or "")).suffix.lower()
        if extension not in self.ALLOWED_EXTENSIONS:
            raise ValidationError("Formato no soportado. Usa .xlsx, .xlsm, .xltx o .xltm.")
        return file_obj
