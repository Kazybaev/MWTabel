from django.db import migrations, models


def use_weekdays_for_college_groups(apps, schema_editor):
    group_model = apps.get_model("tabel_app", "Group")
    group_model.objects.filter(organization_type="college").update(
        study_days="MON_FRI"
    )


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0008_group_college_course")]

    operations = [
        migrations.AlterField(
            model_name="group",
            name="study_days",
            field=models.CharField(
                choices=[
                    ("MON_WED_SAT", "Пн • Ср • Сб"),
                    ("TUE_THU_SUN", "Вт • Чт • Вс"),
                    ("MON_FRI", "Пн • Вт • Ср • Чт • Пт"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(
            use_weekdays_for_college_groups,
            migrations.RunPython.noop,
        ),
    ]
