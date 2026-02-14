from django.core.validators import FileExtensionValidator
from django.db import migrations, models


def copy_salesrep_profile_data(apps, schema_editor):
    UserProfile = apps.get_model("core", "UserProfile")
    SalesRep = apps.get_model("crm", "SalesRep")

    for sales_rep in SalesRep.objects.exclude(user_id__isnull=True):
        profile = UserProfile.objects.filter(user_id=sales_rep.user_id).first()
        if not profile:
            continue

        changed_fields = []
        if not profile.hire_date and sales_rep.hire_date:
            profile.hire_date = sales_rep.hire_date
            changed_fields.append("hire_date")

        if not profile.avatar and sales_rep.avatar:
            profile.avatar = sales_rep.avatar
            changed_fields.append("avatar")

        if changed_fields:
            profile.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0006_salesrep_second_last_name_alter_salesrep_phone"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="avatar",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="profiles/avatars/",
                validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="hire_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(copy_salesrep_profile_data, migrations.RunPython.noop),
    ]
