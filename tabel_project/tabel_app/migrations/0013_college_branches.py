import json
from pathlib import Path

from django.db import migrations, models


KUWAIT = "kuwait"
AGRARIAN = "agrarian"
DECISIONS_PATH = Path(__file__).with_name("college_branch_decisions.json")


def validate_approved_college_structure(apps, schema_editor):
    CollegeGroup = apps.get_model("tabel_app", "CollegeGroup")
    Group = apps.get_model("tabel_app", "Group")
    StudentProfile = apps.get_model("tabel_app", "StudentProfile")
    Membership = StudentProfile.college_groups.through

    actual_groups = set(CollegeGroup.objects.values_list("id", "name"))
    if not actual_groups:
        return
    data = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    rows = data.get("college_groups", [])
    approved_groups = {(row.get("id"), row.get("name")) for row in rows}
    if (
        data.get("schema_version") != "1.0"
        or len(approved_groups) != len(rows)
        or any(row.get("college_branch") not in {AGRARIAN, KUWAIT} for row in rows)
        or actual_groups != approved_groups
    ):
        raise RuntimeError("Production CollegeGroup ids/names do not match approved decisions.")

    approved_ids = {group_id for group_id, _ in approved_groups}
    subject_groups = dict(
        Group.objects.filter(organization_type="college")
        .values_list("id", "main_group_id")
    )
    if any(main_group_id not in approved_ids for main_group_id in subject_groups.values()):
        raise RuntimeError("A college subject group has no approved CollegeGroup mapping.")
    if Group.objects.exclude(organization_type="college").filter(main_group_id__in=approved_ids).exists():
        raise RuntimeError("A non-college subject group points at an approved CollegeGroup.")

    students = list(
        StudentProfile.objects.filter(organization_type="college")
        .values_list("id", "group_id")
    )
    memberships = {}
    for student_id, group_id in Membership.objects.filter(
        studentprofile_id__in=[student_id for student_id, _ in students]
    ).values_list("studentprofile_id", "group_id"):
        memberships.setdefault(student_id, set()).add(group_id)
    for student_id, primary_group_id in students:
        primary_main_id = subject_groups.get(primary_group_id)
        linked_main_ids = {
            subject_groups.get(group_id)
            for group_id in memberships.get(student_id, set())
        }
        if primary_main_id not in approved_ids or linked_main_ids != {primary_main_id}:
            raise RuntimeError(f"College student {student_id} has inconsistent group links.")


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0012_merge_college_and_import")]

    operations = [
        migrations.RunPython(
            validate_approved_college_structure,
            migrations.RunPython.noop,
        ),
        migrations.AddField(
            model_name="collegegroup",
            name="college_branch",
            field=models.CharField(
                choices=[
                    (KUWAIT, "Кувейтский колледж"),
                    (AGRARIAN, "Аграрный колледж"),
                ],
                db_index=True,
                max_length=16,
                null=True,
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
                max_length=16,
                null=True,
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
                max_length=16,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="collegegroup",
            name="name",
            field=models.CharField(max_length=100),
        ),
    ]
