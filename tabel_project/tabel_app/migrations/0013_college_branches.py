from django.db import migrations, models


KUWAIT = "kuwait"
AGRARIAN = "agrarian"


def split_existing_college_data(apps, schema_editor):
    CollegeGroup = apps.get_model("tabel_app", "CollegeGroup")
    Group = apps.get_model("tabel_app", "Group")
    StudentProfile = apps.get_model("tabel_app", "StudentProfile")

    # The production convention requested for the initial split is:
    # first-year data belongs to the Agrarian college; second-year (and old
    # rows without a course) belongs to the Kuwait college.
    StudentProfile.objects.filter(organization_type="college").exclude(
        college_course="1"
    ).update(college_branch=KUWAIT)
    StudentProfile.objects.filter(
        organization_type="college", college_course="1"
    ).update(college_branch=AGRARIAN)
    Group.objects.filter(organization_type="college").exclude(
        college_course="1"
    ).update(college_branch=KUWAIT)
    Group.objects.filter(
        organization_type="college", college_course="1"
    ).update(college_branch=AGRARIAN)

    for main_group in CollegeGroup.objects.all().iterator():
        subgroups = Group.objects.filter(main_group_id=main_group.pk)
        first_year_groups = subgroups.filter(college_course="1")
        other_groups = subgroups.exclude(college_course="1")
        has_first_year = first_year_groups.exists()
        has_other_year = other_groups.exists()
        if not has_first_year:
            has_first_year = StudentProfile.objects.filter(
                college_groups__main_group_id=main_group.pk,
                organization_type="college",
                college_course="1",
            ).exists()
        if not has_other_year:
            has_other_year = StudentProfile.objects.filter(
                college_groups__main_group_id=main_group.pk,
                organization_type="college",
            ).exclude(
                college_course="1",
            ).exists()

        if has_first_year and has_other_year:
            CollegeGroup.objects.filter(pk=main_group.pk).update(college_branch=KUWAIT)
            agrarian_main_group = CollegeGroup.objects.filter(
                name=main_group.name,
                college_branch=AGRARIAN,
            ).first()
            if agrarian_main_group is None:
                agrarian_main_group = CollegeGroup.objects.create(
                    name=main_group.name,
                    college_branch=AGRARIAN,
                )
            first_year_groups.update(
                college_branch=AGRARIAN,
                main_group_id=agrarian_main_group.pk,
            )
            other_groups.update(college_branch=KUWAIT)
        else:
            branch = AGRARIAN if has_first_year else KUWAIT
            CollegeGroup.objects.filter(pk=main_group.pk).update(college_branch=branch)
            subgroups.update(college_branch=branch)


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0012_merge_college_and_import")]

    operations = [
        migrations.AddField(
            model_name="collegegroup",
            name="college_branch",
            field=models.CharField(
                choices=[
                    (KUWAIT, "Кувейтский колледж"),
                    (AGRARIAN, "Аграрный колледж"),
                ],
                db_index=True,
                default=KUWAIT,
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="group",
            name="college_branch",
            field=models.CharField(
                choices=[
                    (KUWAIT, "Кувейтский колледж"),
                    (AGRARIAN, "Аграрный колледж"),
                ],
                db_index=True,
                default=KUWAIT,
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="studentprofile",
            name="college_branch",
            field=models.CharField(
                choices=[
                    (KUWAIT, "Кувейтский колледж"),
                    (AGRARIAN, "Аграрный колледж"),
                ],
                db_index=True,
                default=KUWAIT,
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="collegegroup",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.RunPython(split_existing_college_data, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="collegegroup",
            constraint=models.UniqueConstraint(
                fields=("college_branch", "name"),
                name="unique_college_group_name_per_branch",
            ),
        ),
    ]
