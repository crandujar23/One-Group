from datetime import timedelta
from urllib.parse import parse_qs
from urllib.parse import urlparse

import bleach
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags
from django.utils import timezone

from core.models import BusinessUnit
from core.models import UserProfile
from crm.models import CallLog
from crm.models import SalesRep
from dashboard.models import Appointment
from dashboard.models import Announcement
from dashboard.models import CalendarEvent
from dashboard.models import Offer
from dashboard.models import ResourceTag
from dashboard.models import SharedResource
from dashboard.models import Task
from rewards.models import Tier

User = get_user_model()


class CallLogForm(forms.ModelForm):
    class Meta:
        model = CallLog
        fields = ["sale", "contact_type", "subject", "notes", "next_action_date"]
        widgets = {
            "next_action_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class LoginForm(AuthenticationForm):
    remember_me = forms.BooleanField(required=False, label="Recordarme en este dispositivo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Usuario o correo",
                "autocomplete": "username",
                "autofocus": True,
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Contraseña",
                "autocomplete": "current-password",
            }
        )
        self.fields["remember_me"].widget.attrs.update({"class": "form-check-input"})


class PasswordResetRequestForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "correo@empresa.com",
                "autocomplete": "email",
            }
        )


class PasswordResetSetForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Nueva contraseña",
                "autocomplete": "new-password",
            }
        )
        self.fields["new_password2"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Confirmar nueva contraseña",
                "autocomplete": "new-password",
            }
        )


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Primer apellido"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "correo@empresa.com"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["last_name"].required = True
        self.fields["last_name"].label = "Primer apellido"
        self.fields["first_name"].label = "Nombre"


class AssociateProfileForm(forms.ModelForm):
    def __init__(self, *args, active_tab="pane-personal", **kwargs):
        self.active_tab = active_tab
        super().__init__(*args, **kwargs)

    class Meta:
        model = SalesRep
        fields = [
            "phone",
            "second_last_name",
            "postal_address_line_1",
            "postal_address_line_2",
            "postal_city",
            "postal_state",
            "postal_zip_code",
            "physical_same_as_postal",
            "physical_address_line_1",
            "physical_address_line_2",
            "physical_city",
            "physical_state",
            "physical_zip_code",
        ]
        widgets = {
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "(787)555-1234",
                    "inputmode": "numeric",
                    "autocomplete": "tel-national",
                    "maxlength": "13",
                    "pattern": r"^\(\d{3}\)\d{3}-\d{4}$",
                }
            ),
            "second_last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Segundo apellido (opcional)"}),
            "postal_address_line_1": forms.TextInput(attrs={"class": "form-control", "placeholder": "Dirección"}),
            "postal_address_line_2": forms.TextInput(attrs={"class": "form-control", "placeholder": "Dirección 2"}),
            "postal_city": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ciudad"}),
            "postal_state": forms.Select(attrs={"class": "form-select"}),
            "postal_zip_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "00000-0000",
                    "inputmode": "numeric",
                    "maxlength": "10",
                    "pattern": r"^\d{5}(-\d{4})?$",
                }
            ),
            "physical_same_as_postal": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "physical_address_line_1": forms.TextInput(attrs={"class": "form-control", "placeholder": "Dirección Física"}),
            "physical_address_line_2": forms.TextInput(attrs={"class": "form-control", "placeholder": "Dirección Física 2"}),
            "physical_city": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ciudad Física"}),
            "physical_state": forms.Select(attrs={"class": "form-select"}),
            "physical_zip_code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "00000-0000",
                    "inputmode": "numeric",
                    "maxlength": "10",
                    "pattern": r"^\d{5}(-\d{4})?$",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        physical_same_as_postal = cleaned_data.get("physical_same_as_postal")

        address_fields = [
            "postal_address_line_1",
            "postal_address_line_2",
            "postal_city",
            "postal_state",
            "postal_zip_code",
            "physical_address_line_1",
            "physical_address_line_2",
            "physical_city",
            "physical_state",
            "physical_zip_code",
        ]
        has_address_input = any(cleaned_data.get(field_name) for field_name in address_fields)
        # Validate address fields on address tab or whenever address data is being submitted.
        validate_addresses = self.active_tab == "pane-addresses" or has_address_input or bool(physical_same_as_postal)
        if validate_addresses:
            required_postal = ["postal_address_line_1", "postal_city", "postal_state", "postal_zip_code"]
            for field_name in required_postal:
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, "Este campo es obligatorio.")

            if physical_same_as_postal:
                cleaned_data["physical_address_line_1"] = cleaned_data.get("postal_address_line_1", "")
                cleaned_data["physical_address_line_2"] = cleaned_data.get("postal_address_line_2", "")
                cleaned_data["physical_city"] = cleaned_data.get("postal_city", "")
                cleaned_data["physical_state"] = cleaned_data.get("postal_state", "")
                cleaned_data["physical_zip_code"] = cleaned_data.get("postal_zip_code", "")
            else:
                required_physical = ["physical_address_line_1", "physical_city", "physical_state", "physical_zip_code"]
                for field_name in required_physical:
                    if not cleaned_data.get(field_name):
                        self.add_error(field_name, "Este campo es obligatorio.")

        return cleaned_data

class UserWorkProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["hire_date", "avatar"]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar

        max_size = 2 * 1024 * 1024  # 2MB
        if avatar.size > max_size:
            raise ValidationError("La imagen no puede superar 2MB.")
        return avatar


class AssociateAccessCreateForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "usuario_asociado"}),
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Apellido"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "correo@empresa.com"}),
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Contraseña temporal"}),
    )
    business_units = forms.ModelMultipleChoiceField(
        queryset=BusinessUnit.objects.filter(is_active=True).order_by("name"),
        required=True,
        widget=forms.CheckboxSelectMultiple(),
    )
    tier = forms.ModelChoiceField(
        queryset=Tier.objects.order_by("rank", "name"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin tier",
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Este usuario ya existe.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Este correo ya existe.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        units = cleaned_data.get("business_units")
        if not units:
            self.add_error("business_units", "Selecciona al menos una unidad de negocio.")
        return cleaned_data


class AccessManagementCreateForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "usuario"}),
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Apellido"}),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "correo@empresa.com"}),
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Contraseña temporal"}),
    )
    role = forms.ChoiceField(
        choices=UserProfile.Role.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    business_units = forms.ModelMultipleChoiceField(
        queryset=BusinessUnit.objects.filter(is_active=True).order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    tier = forms.ModelChoiceField(
        queryset=Tier.objects.order_by("rank", "name"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin tier",
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Este usuario ya existe.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Este correo ya existe.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        business_units = cleaned_data.get("business_units")
        units_count = len(business_units) if business_units is not None else 0
        if role == UserProfile.Role.MANAGER and units_count == 0:
            self.add_error("business_units", "Este rol requiere al menos una unidad de negocio.")
        if role == UserProfile.Role.SALES_REP and units_count == 0:
            self.add_error("business_units", "Asociado requiere al menos una unidad de negocio.")
        return cleaned_data


class AccessManagementAssignForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.order_by("username"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    role = forms.ChoiceField(
        choices=UserProfile.Role.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    business_units = forms.ModelMultipleChoiceField(
        queryset=BusinessUnit.objects.filter(is_active=True).order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    tier = forms.ModelChoiceField(
        queryset=Tier.objects.order_by("rank", "name"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Sin tier",
    )

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        business_units = cleaned_data.get("business_units")
        units_count = len(business_units) if business_units is not None else 0
        if role == UserProfile.Role.MANAGER and units_count == 0:
            self.add_error("business_units", "Este rol requiere al menos una unidad de negocio.")
        if role == UserProfile.Role.SALES_REP and units_count == 0:
            self.add_error("business_units", "Asociado requiere al menos una unidad de negocio.")
        return cleaned_data


class SharedResourceForm(forms.ModelForm):
    tags_input = forms.CharField(
        required=False,
        label="Tags",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "crm, onboarding, ventas"}),
        help_text="Separa tags por comas.",
    )

    class Meta:
        model = SharedResource
        fields = ["title", "provider", "description", "resource_type", "is_active", "file", "video_url"]
        labels = {
            "title": "Titulo",
            "provider": "Proveedor",
            "description": "Descripcion",
            "resource_type": "Tipo de recurso",
            "is_active": "Activo",
            "file": "Archivo",
            "video_url": "Enlace de video",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Deck comercial Q1"}),
            "provider": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Interno, YouTube, Partner X"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Contexto o instrucciones de uso (opcional)"}
            ),
            "resource_type": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "video_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
        }
        help_texts = {
            "file": "Formatos permitidos: PDF, PPT y PPTX (maximo 25MB).",
            "video_url": "Proveedores soportados: YouTube, Vimeo, Loom y Google Drive (archivo compartido con enlace).",
        }

    def clean(self):
        cleaned_data = super().clean()
        resource_type = cleaned_data.get("resource_type")
        file = cleaned_data.get("file")
        video_url = cleaned_data.get("video_url")

        if resource_type == SharedResource.ResourceType.FILE and not file:
            self.add_error("file", "Debes subir un archivo.")
        if resource_type == SharedResource.ResourceType.VIDEO and not video_url:
            self.add_error("video_url", "Debes agregar un enlace de video.")
        return cleaned_data

    def clean_video_url(self):
        video_url = (self.cleaned_data.get("video_url") or "").strip()
        if not video_url:
            return video_url

        parsed = urlparse(video_url)
        host = parsed.netloc.lower().replace("www.", "")
        path_parts = [part for part in parsed.path.split("/") if part]

        if host in {"drive.google.com", "docs.google.com"}:
            file_id = None
            if len(path_parts) >= 3 and path_parts[0] == "file" and path_parts[1] == "d":
                file_id = path_parts[2]
            if not file_id:
                file_id = parse_qs(parsed.query).get("id", [None])[0]
            if not file_id:
                raise ValidationError(
                    "En Google Drive usa un enlace de archivo compartido valido, por ejemplo: "
                    "https://drive.google.com/file/d/<ID>/view"
                )

        return video_url

    def get_tags(self):
        raw = self.cleaned_data.get("tags_input", "")
        names = [name.strip().lower() for name in raw.split(",") if name.strip()]
        unique_names = []
        seen = set()
        for name in names:
            if name not in seen:
                seen.add(name)
                unique_names.append(name[:50])
        tags = []
        for name in unique_names:
            tag, _ = ResourceTag.objects.get_or_create(name=name)
            tags.append(tag)
        return tags


class AnnouncementForm(forms.ModelForm):
    ALLOWED_MESSAGE_TAGS = [
        "p",
        "br",
        "strong",
        "em",
        "u",
        "ul",
        "ol",
        "li",
        "a",
    ]
    ALLOWED_MESSAGE_ATTRIBUTES = {
        "a": ["href", "target", "rel"],
    }

    class Meta:
        model = Announcement
        fields = ["title", "message", "start_date", "end_date", "media_type", "media_file", "video_url", "is_active"]
        labels = {
            "title": "Titulo del anuncio",
            "message": "Contenido",
            "start_date": "Fecha de implementacion",
            "end_date": "Fecha de finalizacion",
            "media_type": "Tipo de medio",
            "media_file": "Archivo (PDF o imagen)",
            "video_url": "Enlace de video",
            "is_active": "Activo",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Nuevo esquema de comisiones"}),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Mensaje del anuncio"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "media_type": forms.Select(attrs={"class": "form-select"}),
            "media_file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "video_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "media_file": "Para PDF (max 30MB) o imagen JPG/PNG/WEBP/GIF (max 8MB).",
            "video_url": "Proveedores soportados: YouTube y Google Drive.",
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La fecha de finalizacion debe ser igual o posterior a la de implementacion.")
        return cleaned_data

    def clean_message(self):
        raw_message = (self.cleaned_data.get("message") or "").strip()
        if not raw_message:
            raise ValidationError("Este campo es obligatorio.")

        cleaned_message = bleach.clean(
            raw_message,
            tags=self.ALLOWED_MESSAGE_TAGS,
            attributes=self.ALLOWED_MESSAGE_ATTRIBUTES,
            protocols=["http", "https", "mailto"],
            strip=True,
        )

        if not strip_tags(cleaned_message).strip():
            raise ValidationError("El contenido del anuncio no puede estar vacio.")

        return cleaned_message


class OfferForm(forms.ModelForm):
    ALLOWED_MESSAGE_TAGS = AnnouncementForm.ALLOWED_MESSAGE_TAGS
    ALLOWED_MESSAGE_ATTRIBUTES = AnnouncementForm.ALLOWED_MESSAGE_ATTRIBUTES

    class Meta:
        model = Offer
        fields = ["title", "message", "start_date", "end_date", "business_units", "media_type", "media_file", "video_url", "is_active"]
        labels = {
            "title": "Titulo de la oferta",
            "message": "Contenido",
            "start_date": "Fecha de implementacion",
            "end_date": "Fecha de finalizacion",
            "business_units": "Linea Comercial",
            "media_type": "Tipo de medio",
            "media_file": "Archivo (PDF o imagen)",
            "video_url": "Enlace de video",
            "is_active": "Activo",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Oferta especial de la semana"}),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Mensaje de la oferta"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "business_units": forms.CheckboxSelectMultiple(),
            "media_type": forms.Select(attrs={"class": "form-select"}),
            "media_file": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "video_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "media_file": "Para PDF (max 30MB) o imagen JPG/PNG/WEBP/GIF (max 8MB).",
            "video_url": "Proveedores soportados: YouTube y Google Drive.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_units"].queryset = BusinessUnit.objects.filter(is_active=True).order_by("name")
        self.fields["business_units"].required = True

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        business_units = cleaned_data.get("business_units")
        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "La fecha de finalizacion debe ser igual o posterior a la de implementacion.")
        if not business_units:
            self.add_error("business_units", "Selecciona al menos un producto para la oferta.")
        return cleaned_data

    def clean_message(self):
        raw_message = (self.cleaned_data.get("message") or "").strip()
        if not raw_message:
            raise ValidationError("Este campo es obligatorio.")

        cleaned_message = bleach.clean(
            raw_message,
            tags=self.ALLOWED_MESSAGE_TAGS,
            attributes=self.ALLOWED_MESSAGE_ATTRIBUTES,
            protocols=["http", "https", "mailto"],
            strip=True,
        )

        if not strip_tags(cleaned_message).strip():
            raise ValidationError("El contenido de la oferta no puede estar vacio.")

        return cleaned_message


class CalendarEventForm(forms.ModelForm):
    class Meta:
        model = CalendarEvent
        fields = ["title", "description", "start_at", "end_at", "all_day", "color"]
        labels = {
            "title": "Titulo",
            "description": "Descripcion",
            "start_at": "Inicio",
            "end_at": "Final",
            "all_day": "Todo el dia",
            "color": "Color",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Título del evento"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Descripción"}),
            "start_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "all_day": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "color": forms.TextInput(attrs={"class": "form-control form-control-color", "type": "color"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_at = cleaned_data.get("start_at")
        end_at = cleaned_data.get("end_at")
        if start_at and end_at and end_at <= start_at:
            self.add_error("end_at", "La fecha/hora final debe ser posterior al inicio.")
        return cleaned_data


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "due_at", "priority"]
        labels = {
            "title": "Titulo",
            "description": "Descripcion",
            "due_at": "Fecha limite",
            "priority": "Prioridad",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Título de la tarea"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Descripción"}),
            "due_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_due_at(self):
        due_at = self.cleaned_data["due_at"]
        if due_at < timezone.now() - timedelta(days=365):
            raise ValidationError("La fecha límite no puede ser tan antigua.")
        return due_at


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ["subject", "contact_name", "start_at", "end_at", "location", "notes", "status"]
        labels = {
            "subject": "Asunto",
            "contact_name": "Cliente",
            "start_at": "Inicio",
            "end_at": "Final",
            "location": "Ubicacion",
            "notes": "Notas",
            "status": "Estado",
        }
        widgets = {
            "subject": forms.TextInput(attrs={"class": "form-control", "placeholder": "Asunto de la cita"}),
            "contact_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre del cliente"}),
            "start_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ubicación o enlace"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Notas"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_at = cleaned_data.get("start_at")
        end_at = cleaned_data.get("end_at")
        if start_at and end_at and end_at <= start_at:
            self.add_error("end_at", "La hora final debe ser posterior al inicio.")
        return cleaned_data
