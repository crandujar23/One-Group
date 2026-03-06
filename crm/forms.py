from django import forms

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
