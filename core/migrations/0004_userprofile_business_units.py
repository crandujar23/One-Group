from django.db import migrations, models


def copy_business_unit_to_business_units(apps, schema_editor):
    UserProfile = apps.get_model("core", "UserProfile")
    for profile in UserProfile.objects.exclude(business_unit_id__isnull=True):
        profile.business_units.add(profile.business_unit_id)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_alter_userprofile_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="business_units",
            field=models.ManyToManyField(blank=True, related_name="scoped_user_profiles", to="core.businessunit"),
        ),
        migrations.RunPython(copy_business_unit_to_business_units, migrations.RunPython.noop),
    ]
