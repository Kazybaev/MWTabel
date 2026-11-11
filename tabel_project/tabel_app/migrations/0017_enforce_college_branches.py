from django.db import migrations, models


KUWAIT = "kuwait"
AGRARIAN = "agrarian"


def branch_field():
    return models.CharField(
        choices=[
            (KUWAIT, "Кувейтский колледж"),
            (AGRARIAN, "Аграрный колледж"),
        ],
        db_index=True,
        default=KUWAIT,
        max_length=16,
    )


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0016_classify_college_branches")]

    operations = [
        migrations.AlterField(
            model_name="collegegroup",
            name="college_branch",
            field=branch_field(),
        ),
        migrations.AlterField(
            model_name="group",
            name="college_branch",
            field=branch_field(),
        ),
        migrations.AlterField(
            model_name="studentprofile",
            name="college_branch",
            field=branch_field(),
        ),
        migrations.AddConstraint(
            model_name="collegegroup",
            constraint=models.UniqueConstraint(
                fields=("college_branch", "name"),
                name="unique_college_group_name_per_branch",
            ),
        ),
    ]
