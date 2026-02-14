from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from crm.models import CallLog
from crm.models import SalesRep

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
            "hire_date",
            "avatar",
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
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control"}),
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

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar

        max_size = 2 * 1024 * 1024  # 2MB
        if avatar.size > max_size:
            raise ValidationError("La imagen no puede superar 2MB.")
        return avatar
