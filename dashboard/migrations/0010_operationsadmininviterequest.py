from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0009_backfill_offer_business_units"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationsAdminInviteRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("invited", "Invited"),
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("expires_at", models.DateTimeField()),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_notes", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "invited_user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operations_admin_invites_received", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "inviter_partner",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operations_admin_invites_sent", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="operations_admin_invites_reviewed", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
