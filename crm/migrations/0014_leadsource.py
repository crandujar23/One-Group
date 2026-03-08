from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0013_lead_customer_country_lead_customer_postal_code_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="LeadSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
    ]
