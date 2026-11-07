from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    CollegeGroup, Group, Lesson, LessonRecord, MentorProfile,
    MonthlyStudentReportAttempt, MonthlyStudentReportBatchItem, MonthlyStudentReportDispatch,
    StudentProfile, User,
)
from .report import build_student_month_report, get_student_report_groups
from .report_queue import enqueue_monthly_report_batch


class HistoricalKuwaitSelectionTests(TestCase):
    month = date(2026, 10, 1)

    def setUp(self):
        self.admin = User.objects.create_user(username="historical-admin", role=User.ROLE_ADMIN)
        mentor = MentorProfile.objects.create(
            user=User.objects.create_user(username="historical-mentor", role=User.ROLE_MENTOR),
            organization_type="college",
        )
        main = CollegeGroup.objects.create(name="ПИ-история", college_branch="kuwait")
        self.groups = {}
        for label, archived_at in (
            ("before", datetime(2026, 9, 20, tzinfo=dt_timezone.utc)),
            ("during", datetime(2026, 10, 14, tzinfo=dt_timezone.utc)),
            ("after", datetime(2026, 11, 2, tzinfo=dt_timezone.utc)),
            ("active", None),
        ):
            self.groups[label] = Group.objects.create(
                course_name=label, mentor=mentor, main_group=main,
                organization_type="college", college_branch="kuwait",
                study_days=Group.MON_FRI, archived_at=archived_at,
            )
        self.students = {}
        for label in self.groups:
            student = StudentProfile.objects.create(
                user=User.objects.create_user(username=f"historical-{label}", full_name=label, role=User.ROLE_STUDENT),
                parent_phone=f"+99670000000{len(self.students) + 1}",
                group=self.groups[label], organization_type="college", college_branch="kuwait",
                archived_at=self.groups[label].archived_at,
            )
            student.college_groups.add(self.groups[label])
            lesson = Lesson.objects.create(group=self.groups[label], lesson_date=date(2026, 10, 8))
            LessonRecord.objects.create(student=student, lesson=lesson, grade="5")
            self.students[label] = student

    def enqueue(self, **kwargs):
        return enqueue_monthly_report_batch(
            created_by=self.admin, month=self.month, organization_type="college",
            college_branch="kuwait", **kwargs,
        )

    def test_archive_before_during_and_after_period(self):
        batch = self.enqueue()
        self.assertSetEqual(
            set(batch.items.values_list("student_id", flat=True)),
            {self.students[label].id for label in ("during", "after", "active")},
        )
        for label in ("during", "after"):
            report = build_student_month_report(self.students[label], month_start=self.month)
            self.assertEqual(report["student"]["id"], self.students[label].id)
            self.assertEqual(report["subjects"][0]["grade_counts"]["5"], 1)
        self.assertEqual(build_student_month_report(self.students["before"], self.month)["status"], "skipped")

    def test_archived_group_without_month_lessons_is_not_an_extra_subject(self):
        student = self.students["during"]
        empty = Group.objects.create(
            course_name="empty historical subject", mentor=student.group.mentor,
            main_group=student.group.main_group, organization_type="college",
            college_branch="kuwait", study_days=Group.MON_FRI,
            archived_at=datetime(2026, 10, 14, tzinfo=dt_timezone.utc),
        )
        student.college_groups.add(empty)
        self.assertEqual([group.id for group in get_student_report_groups(student, self.month)], [student.group_id])
        self.assertEqual(len(build_student_month_report(student, self.month)["subjects"]), 1)

    def test_explicit_selection_and_accepted_report_are_preserved(self):
        selected = self.students["during"]
        MonthlyStudentReportDispatch.objects.create(
            student=selected, month=self.month, trigger_date=date(2026, 10, 8), status="accepted",
        )
        batch = self.enqueue(student_ids=[selected.id], group_ids=[selected.group_id])
        item = batch.items.get()
        self.assertEqual(item.student_id, selected.id)
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertIn("Already accepted", item.error_message)
        with self.assertRaises(ValueError):
            self.enqueue(student_ids=[self.students["before"].id])
        with self.assertRaises(ValueError):
            self.enqueue(group_ids=[self.groups["before"].id])
        foreign = Group.objects.create(
            course_name="foreign branch", mentor=selected.group.mentor,
            organization_type="college", college_branch="agrarian",
            study_days=Group.MON_FRI,
        )
        foreign_student = StudentProfile.objects.create(
            user=User.objects.create_user(username="historical-foreign", role=User.ROLE_STUDENT),
            parent_phone="+996700000099", group=foreign,
            organization_type="college", college_branch="agrarian",
        )
        with self.assertRaises(ValueError):
            self.enqueue(student_ids=[foreign_student.id])
        with self.assertRaises(ValueError):
            self.enqueue(group_ids=[foreign.id])

    def test_more_than_four_subjects_are_skipped_without_truncation(self):
        student = self.students["active"]
        for index in range(4):
            group = Group.objects.create(
                course_name=f"extra-{index}", mentor=student.group.mentor,
                main_group=student.group.main_group, organization_type="college",
                college_branch="kuwait", study_days=Group.MON_FRI,
            )
            student.college_groups.add(group)
        self.assertEqual(len(build_student_month_report(student, self.month)["subjects"]), 5)
        batch = self.enqueue(student_ids=[student.id])
        item = batch.items.get()
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertIn("More than four subjects", item.error_message)

    def test_unknown_prior_attempt_is_not_retried(self):
        student = self.students["during"]
        dispatch = MonthlyStudentReportDispatch.objects.create(
            student=student, month=self.month, trigger_date=date(2026, 10, 8),
            status="failed", attempts=1,
        )
        MonthlyStudentReportAttempt.objects.create(
            dispatch=dispatch, attempt_number=1, status="failed", message_status="unknown",
        )
        batch = self.enqueue(student_ids=[student.id], confirm_retry_failed=True)
        item = batch.items.get()
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertIn("unknown", item.error_message)

    def test_api_keeps_organization_rights_and_exact_student_filter(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        headers = {"HTTP_X_ORGANIZATION_TYPE": "college", "HTTP_X_COLLEGE_BRANCH": "kuwait"}
        with self.settings(DIFY_KUWAIT_API_KEY="test-key"):
            response = client.post("/api/reports/send-all/", {
                "organization": "college", "college_branch": "kuwait", "month": "2026-10",
                "student_ids": [self.students["during"].id],
            }, format="json", **headers)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(list(MonthlyStudentReportBatchItem.objects.filter(batch_id=response.data["id"]).values_list("student_id", flat=True)), [self.students["during"].id])
        client.force_authenticate(self.students["during"].user)
        denied = client.post("/api/reports/send-all/", {
            "organization": "college", "college_branch": "kuwait", "month": "2026-10",
            "student_ids": [self.students["during"].id],
        }, format="json", **headers)
        self.assertEqual(denied.status_code, 403)
