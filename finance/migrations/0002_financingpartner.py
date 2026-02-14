# Generated manually for FinancingPartner model.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
        ("finance", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancingPartner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                (
                    "partner_type",
                    models.CharField(
                        choices=[("BANK", "Banco"), ("COOPERATIVE", "Cooperativa"), ("OTHER", "Otro")],
                        default="BANK",
                        max_length=16,
                    ),
                ),
                ("contact_name", models.CharField(blank=True, max_length=120)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("contact_phone", models.CharField(blank=True, max_length=30)),
                ("website", models.URLField(blank=True)),
                (
                    "services",
                    models.TextField(
                        blank=True,
                        help_text="Describe los servicios financieros disponibles: préstamos personales, comerciales, líneas verdes, etc.",
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("priority", models.PositiveSmallIntegerField(default=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "business_units",
                    models.ManyToManyField(blank=True, related_name="financing_partners", to="core.businessunit"),
                ),
            ],
            options={
                "ordering": ["priority", "name"],
            },
        ),
    ]
