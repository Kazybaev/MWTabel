from datetime import date
from importlib import import_module

from django.apps import apps
from django.test import TransactionTestCase

from .models import (
    CollegeGroup,
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    StudentProfile,
    User,
)


class CollegeBranchMigrationTests(TransactionTestCase):
    reset_sequences = True

    def test_owner_mapping_preserves_courses_and_relations(self):
        migration = import_module("tabel_app.migrations.0016_classify_college_branches")
        decisions = migration.load_decisions()
        mentor = MentorProfile.objects.create(
            user=User.objects.create_user(username="branch-migration-mentor", role="MENTOR"),
            organization_type="college",
        )
        snapshots = {}

        for index, ((college_group_id, name), expected_branch) in enumerate(
            sorted(decisions.items()),
            start=1,
        ):
            opposite_branch = "kuwait" if expected_branch == "agrarian" else "agrarian"
            course = "2" if expected_branch == "agrarian" else "1"
            college_group = CollegeGroup.objects.create(
                id=college_group_id,
                name=name,
                college_branch=opposite_branch,
            )
            group = Group.objects.create(
                course_name=f"{name}-subject",
                mentor=mentor,
                main_group=college_group,
                study_days=Group.MON_FRI,
                organization_type="college",
                college_course=course,
                college_branch=opposite_branch,
            )
            student = StudentProfile.objects.create(
                user=User.objects.create_user(
                    username=f"branch-migration-student-{index}",
                    role="STUDENT",
                ),
                parent_phone=f"+9967000{index:05d}",
                group=group,
                organization_type="college",
                college_course=course,
                college_branch=opposite_branch,
            )
            student.college_groups.add(group)
            snapshots[student.pk] = {
                "expected_branch": expected_branch,
                "college_course": course,
                "primary_group_id": group.pk,
                "main_group_id": college_group.pk,
                "membership_ids": [group.pk],
            }

        preserved_student = StudentProfile.objects.get(group__main_group_id=6)
        lesson = Lesson.objects.create(
            group=preserved_student.group,
            lesson_date=date(2026, 8, 1),
        )
        record = LessonRecord.objects.create(
            student=preserved_student,
            lesson=lesson,
            sequence=1,
            grade="5",
        )
        relation_snapshot = (
            lesson.pk,
            lesson.group_id,
            lesson.lesson_date,
            record.pk,
            record.student_id,
            record.lesson_id,
            record.grade,
        )

        migration.classify_college_branches(apps, None)

        for student_id, snapshot in snapshots.items():
            student = StudentProfile.objects.get(pk=student_id)
            student.group.refresh_from_db()
            student.group.main_group.refresh_from_db()
            self.assertEqual(student.college_branch, snapshot["expected_branch"])
            self.assertEqual(student.group.college_branch, snapshot["expected_branch"])
            self.assertEqual(student.group.main_group.college_branch, snapshot["expected_branch"])
            self.assertEqual(student.college_course, snapshot["college_course"])
            self.assertEqual(student.group.college_course, snapshot["college_course"])
            self.assertEqual(student.group_id, snapshot["primary_group_id"])
            self.assertEqual(student.group.main_group_id, snapshot["main_group_id"])
            self.assertEqual(
                list(student.college_groups.values_list("id", flat=True)),
                snapshot["membership_ids"],
            )

        lesson.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(
            (
                lesson.pk,
                lesson.group_id,
                lesson.lesson_date,
                record.pk,
                record.student_id,
                record.lesson_id,
                record.grade,
            ),
            relation_snapshot,
        )
