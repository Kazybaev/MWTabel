from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0007_studentprofile_college_course")]

    operations = [
        migrations.AddField(
            model_name="group",
            name="college_course",
            field=models.CharField(
                blank=True,
                choices=[
                    ("1", "1 курс"),
                    ("2", "2 курс"),
                    ("3", "3 курс"),
                    ("4", "4 курс"),
                ],
                max_length=1,
            ),
        ),
    ]
