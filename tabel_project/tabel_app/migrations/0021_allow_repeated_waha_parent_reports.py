from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tabel_app", "0020_waha_parent_report_batches"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="wahaparentreportbatchitem",
            name="unique_active_waha_parent_report_context",
        ),
    ]
