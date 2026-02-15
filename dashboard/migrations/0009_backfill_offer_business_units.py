from django.db import migrations


def assign_existing_offers_to_solar(apps, schema_editor):
    Offer = apps.get_model("dashboard", "Offer")
    BusinessUnit = apps.get_model("core", "BusinessUnit")
    solar_unit = BusinessUnit.objects.filter(code="solar-home-power").first()
    if solar_unit is None:
        return

    for offer in Offer.objects.all():
        if not offer.business_units.exists():
            offer.business_units.add(solar_unit)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0008_offer_business_units"),
    ]

    operations = [
        migrations.RunPython(assign_existing_offers_to_solar, noop_reverse),
    ]
