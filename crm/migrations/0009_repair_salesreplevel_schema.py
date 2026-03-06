# Generated manually to repair environments where crm.0008 was faked
# while crm_salesreplevel already existed with a partial schema.

from django.db import migrations


def repair_salesreplevel_schema(apps, schema_editor):
    connection = schema_editor.connection
    table_name = "crm_salesreplevel"

    existing_tables = set(connection.introspection.table_names())
    if table_name not in existing_tables:
        return

    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
        existing_columns = {col.name for col in description}

        if "sales_goal" not in existing_columns:
            cursor.execute(
                "ALTER TABLE crm_salesreplevel "
                "ADD COLUMN sales_goal integer NOT NULL DEFAULT 0"
            )

        if "indirect_sales_cap_percentage" not in existing_columns:
            cursor.execute(
                "ALTER TABLE crm_salesreplevel "
                "ADD COLUMN indirect_sales_cap_percentage decimal NOT NULL DEFAULT 0"
            )

        if "sort_value" not in existing_columns:
            cursor.execute(
                "ALTER TABLE crm_salesreplevel "
                "ADD COLUMN sort_value integer NOT NULL DEFAULT 0"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0008_salesreplevel"),
    ]

    operations = [
        migrations.RunPython(repair_salesreplevel_schema, migrations.RunPython.noop),
    ]
