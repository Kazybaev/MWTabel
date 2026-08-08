from django.db import migrations, models


def assign_existing_college_groups(apps, schema_editor):
    StudentProfile = apps.get_model("tabel_app", "StudentProfile")
    for student in StudentProfile.objects.filter(organization_type="college").iterator():
        student.college_groups.add(student.group_id)


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0005_organization_scope")]

    operations = [
        migrations.AddField(
            model_name="studentprofile",
            name="college_groups",
            field=models.ManyToManyField(
                blank=True,
                related_name="college_students",
                to="tabel_app.group",
            ),
        ),
        migrations.RunPython(assign_existing_college_groups, migrations.RunPython.noop),
    ]
