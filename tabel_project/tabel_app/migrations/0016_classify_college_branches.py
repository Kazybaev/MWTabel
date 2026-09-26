import json
from pathlib import Path

from django.db import migrations


VALID_BRANCHES = {"agrarian", "kuwait"}
DECISIONS_PATH = Path(__file__).with_name("college_branch_decisions.json")


def load_decisions():
    data = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    rows = data.get("college_groups", [])
    if data.get("schema_version") != "1.0" or not rows:
        raise RuntimeError("College branch decisions are missing or invalid.")
    decisions = {}
    names = set()
    for row in rows:
        key = (row.get("id"), row.get("name"))
        branch = row.get("college_branch")
        if (
            not isinstance(key[0], int)
            or not isinstance(key[1], str)
            or not key[1]
            or key in decisions
            or key[1] in names
            or branch not in VALID_BRANCHES
        ):
            raise RuntimeError("College branch decisions are ambiguous or invalid.")
        decisions[key] = branch
        names.add(key[1])
    return decisions


def classify_college_branches(apps, schema_editor):
    CollegeGroup = apps.get_model("tabel_app", "CollegeGroup")
    Group = apps.get_model("tabel_app", "Group")
    StudentProfile = apps.get_model("tabel_app", "StudentProfile")
    Membership = StudentProfile.college_groups.through

    actual_groups = set(CollegeGroup.objects.values_list("id", "name"))
    if not actual_groups:
        return
    decisions = load_decisions()
    if actual_groups != set(decisions):
        raise RuntimeError("Production CollegeGroup ids/names do not match approved decisions.")

    subject_groups = list(
        Group.objects.filter(organization_type="college")
        .values_list("id", "main_group_id")
    )
    approved_ids = {group_id for group_id, _ in decisions}
    if any(main_group_id not in approved_ids for _, main_group_id in subject_groups):
        raise RuntimeError("A college subject group has no approved CollegeGroup mapping.")
    if Group.objects.exclude(organization_type="college").filter(main_group_id__in=approved_ids).exists():
        raise RuntimeError("A non-college subject group points at an approved CollegeGroup.")

    subject_to_main = dict(subject_groups)
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
        primary_main_id = subject_to_main.get(primary_group_id)
        linked_group_ids = memberships.get(student_id, set())
        if primary_main_id not in approved_ids or not linked_group_ids:
            raise RuntimeError(f"College student {student_id} has incomplete group links.")
        linked_main_ids = {subject_to_main.get(group_id) for group_id in linked_group_ids}
        if linked_main_ids != {primary_main_id}:
            raise RuntimeError(f"College student {student_id} spans multiple CollegeGroups.")

    for (college_group_id, _), branch in decisions.items():
        CollegeGroup.objects.filter(pk=college_group_id).update(college_branch=branch)
        Group.objects.filter(
            organization_type="college",
            main_group_id=college_group_id,
        ).update(college_branch=branch)
        StudentProfile.objects.filter(
            organization_type="college",
            group__main_group_id=college_group_id,
        ).update(college_branch=branch)

    if CollegeGroup.objects.filter(college_branch__isnull=True).exists():
        raise RuntimeError("A CollegeGroup was left without a branch.")
    if Group.objects.filter(organization_type="college", college_branch__isnull=True).exists():
        raise RuntimeError("A college subject group was left without a branch.")
    if StudentProfile.objects.filter(organization_type="college", college_branch__isnull=True).exists():
        raise RuntimeError("A college student was left without a branch.")


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0015_merge_college_and_report_queue")]

    operations = [
        migrations.RunPython(classify_college_branches, migrations.RunPython.noop),
    ]
