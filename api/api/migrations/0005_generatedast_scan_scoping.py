from django.db import migrations, models


class Migration(migrations.Migration):
    """Give every AST row an owner.

    Both columns are nullable with no backfill: rows written before this
    migration belong to a scan that has already finished, and inventing an
    owner for them would only make them eligible to be read back by a scan
    they have nothing to do with. Null means "unowned", which the lookups
    treat as never matching a scoped query.
    """

    dependencies = [
        ("api", "0004_generatedast_protocols"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedast",
            name="project_id",
            field=models.CharField(
                max_length=64, blank=True, null=True, db_index=True
            ),
        ),
        migrations.AddField(
            model_name="generatedast",
            name="scan_id",
            field=models.CharField(
                max_length=64, blank=True, null=True, db_index=True
            ),
        ),
    ]
