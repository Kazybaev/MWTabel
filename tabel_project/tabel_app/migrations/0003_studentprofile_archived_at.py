from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tabel_app", "0002_monthlystudentreportdispatch"),
    ]

    operations = [
        migrations.AddField(
            model_name="studentprofile",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
