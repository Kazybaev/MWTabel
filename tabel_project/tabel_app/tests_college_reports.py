from datetime import date
from unittest.mock import patch

from django.test import TestCase

from tabel_app.college_reports import (
    force_send_all_college_monthly_reports,
    send_college_student_month_report,
    send_due_college_monthly_reports,
)
from tabel_app.models import (
    Group,
    Lesson,
    LessonRecord,
    MonthlyStudentReportDispatch,
    MentorProfile,
    ORGANIZATION_ACADEMY,
    ORGANIZATION_COLLEGE,
    StudentProfile,
    User,
)

from tabel_app.report import build_student_month_report, send_student_month_report
from tabel_app.report_delivery import build_report_message_text


class CollegeMonthlyReportServiceTests(TestCase):
    def setUp(self):
        mentor_user = User.objects.create_user(
            username="college-report-mentor",
            password="test-password",
            full_name="College Report Mentor",
            role=User.ROLE_MENTOR,
        )
        mentor = MentorProfile.objects.create(
            user=mentor_user,
            organization_type=ORGANIZATION_COLLEGE,
        )
        self.college_group = Group.objects.create(
            course_name="College Subject",
            mentor=mentor,
            study_days=Group.MON_FRI,
            organization_type=ORGANIZATION_COLLEGE,
        )
        college_user = User.objects.create_user(
            username="college-report-student",
            password="test-password",
            full_name="College Report Student",
            role=User.ROLE_STUDENT,
        )
        self.college_student = StudentProfile.objects.create(
            user=college_user,
            parent_name="College Parent",
            parent_phone="+996700000001",
            group=self.college_group,
            organization_type=ORGANIZATION_COLLEGE,
        )

        academy_mentor_user = User.objects.create_user(
            username="academy-report-mentor",
            password="test-password",
            full_name="Academy Report Mentor",
            role=User.ROLE_MENTOR,
        )
        academy_mentor = MentorProfile.objects.create(
            user=academy_mentor_user,
            organization_type=ORGANIZATION_ACADEMY,
        )
        academy_group = Group.objects.create(
            course_name="Academy Group",
            mentor=academy_mentor,
            study_days=Group.MON_WED_SAT,
            organization_type=ORGANIZATION_ACADEMY,
        )
        academy_user = User.objects.create_user(
            username="academy-report-student",
            password="test-password",
            full_name="Academy Report Student",
            role=User.ROLE_STUDENT,
        )
        self.academy_student = StudentProfile.objects.create(
            user=academy_user,
            parent_name="Academy Parent",
            parent_phone="+996700000002",
            group=academy_group,
            organization_type=ORGANIZATION_ACADEMY,
        )

    @patch("tabel_app.college_reports.service.send_student_month_report")
    def test_single_college_report_uses_standard_report_logic(self, mocked_send):
        mocked_send.return_value = {"status": "sent"}

        result = send_college_student_month_report(self.college_student, dry_run=True)

        self.assertEqual(result["status"], "sent")
        mocked_send.assert_called_once_with(self.college_student, dry_run=True)

    @patch("tabel_app.college_reports.service.send_student_month_report")
    def test_academy_student_is_rejected_before_delivery(self, mocked_send):
        result = send_college_student_month_report(self.academy_student)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "not_college_student")
        mocked_send.assert_not_called()

    @patch("tabel_app.college_reports.service.force_send_all_monthly_reports")
    def test_bulk_college_report_is_always_scoped_to_college(self, mocked_send_all):
        mocked_send_all.return_value = []

        force_send_all_college_monthly_reports(run_date=None)

        mocked_send_all.assert_called_once_with(
            organization_type=ORGANIZATION_COLLEGE,
            run_date=None,
        )

    @patch("tabel_app.college_reports.service.send_due_monthly_reports")
    def test_due_college_report_is_always_scoped_to_college(self, mocked_send_due):
        mocked_send_due.return_value = []

        send_due_college_monthly_reports(group_id=self.college_group.pk)

        mocked_send_due.assert_called_once_with(
            organization_type=ORGANIZATION_COLLEGE,
            group_id=self.college_group.pk,
        )

    def create_subject_lessons(self):
        self.second_group = Group.objects.create(
            course_name="Second Subject", mentor=self.college_group.mentor,
            study_days=Group.MON_FRI, organization_type=ORGANIZATION_COLLEGE,
        )
        self.college_student.college_groups.set([self.college_group, self.second_group])
        self.math_first = Lesson.objects.create(group=self.college_group, lesson_date=date(2026, 4, 10))
        self.math_last = Lesson.objects.create(group=self.college_group, lesson_date=date(2026, 4, 28))
        self.english_first = Lesson.objects.create(group=self.second_group, lesson_date=date(2026, 4, 10))
        self.english_last = Lesson.objects.create(group=self.second_group, lesson_date=date(2026, 4, 30))
        return date(2026, 4, 1)

    def test_report_collects_all_subjects_and_same_day_grades(self):
        month = self.create_subject_lessons()
        for lesson, grade in [(self.math_first, "5"), (self.math_last, "3"), (self.english_first, "4"), (self.english_last, "\u041d")]:
            LessonRecord.objects.create(student=self.college_student, lesson=lesson, grade=grade)
        # Invalid cross-organization membership must never enter the report.
        self.college_student.college_groups.add(self.academy_student.group)
        foreign = Lesson.objects.create(group=self.academy_student.group, lesson_date=date(2026, 4, 30))
        LessonRecord.objects.create(student=self.college_student, lesson=foreign, grade="2")
        report = build_student_month_report(self.college_student, month)
        self.assertEqual(report["organization_type"], "college")
        self.assertEqual(len(report["subjects"]), 2)
        self.assertEqual(report["summary"]["grades"], ["5", "4", "3", "\u041d"])
        self.assertEqual(report["summary"]["total_lessons"], 4)
        self.assertEqual(report["summary"]["average_grade"], 4.0)
        self.assertEqual(report["summary"]["attendance_rate"], 75.0)
        self.assertEqual(report["summary"]["absence_count"], 1)
        self.assertEqual(report["period"]["last_lesson_date"], "2026-04-30")
        self.assertEqual(report["subjects"][0]["summary"]["average_grade"], 4.0)
        self.assertEqual(report["subjects"][1]["summary"]["average_grade"], 4.0)
        text = build_report_message_text(report)
        self.assertIn("College Subject", text)
        self.assertIn("Second Subject", text)
        self.assertIn("2026-04-30: \u041d", text)

    @patch("tabel_app.report.run_dify_workflow")
    def test_report_waits_for_last_marks_of_all_subjects(self, mocked_workflow):
        month = self.create_subject_lessons()
        LessonRecord.objects.create(student=self.college_student, lesson=self.english_last, grade="5")
        result = send_student_month_report(self.college_student, run_date=date(2026, 4, 30), month_start=month)
        self.assertEqual(result["reason"], "trigger_lesson_not_marked")
        self.assertEqual(result["unmarked_group_ids"], [self.college_group.pk])
        mocked_workflow.assert_not_called()
        LessonRecord.objects.create(student=self.college_student, lesson=self.math_last, grade="\u041d")
        result = send_student_month_report(self.college_student, run_date=date(2026, 4, 30), month_start=month, dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["payload"]["summary"]["absence_count"], 1)
        self.assertEqual(MonthlyStudentReportDispatch.objects.count(), 0)

    @patch("tabel_app.report.run_dify_workflow")
    def test_earlier_subject_cannot_trigger_incomplete_monthly_report(self, mocked_workflow):
        month = self.create_subject_lessons()
        LessonRecord.objects.create(student=self.college_student, lesson=self.math_last, grade="5")
        result = send_student_month_report(self.college_student, run_date=date(2026, 4, 28), month_start=month)
        self.assertEqual(result["reason"], "not_due_today")
        self.assertEqual(result["trigger_date"], "2026-04-30")
        mocked_workflow.assert_not_called()

    def test_additional_subject_is_selected_when_main_group_has_no_lessons(self):
        month = self.create_subject_lessons()
        self.college_group.lessons.all().delete()
        LessonRecord.objects.create(student=self.college_student, lesson=self.english_last, grade="5")
        results = send_due_college_monthly_reports(
            run_date=date(2026, 4, 30), month_start=month,
            group_id=self.second_group.pk, dry_run=True,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "dry_run")
        self.assertEqual(len(results[0]["payload"]["subjects"]), 2)
        self.assertEqual(results[0]["payload"]["subjects"][0]["summary"]["total_lessons"], 0)

    def test_academy_report_ignores_additional_college_memberships(self):
        Lesson.objects.create(group=self.academy_student.group, lesson_date=date(2026, 4, 30))
        self.academy_student.college_groups.add(self.college_group)
        Lesson.objects.create(group=self.college_group, lesson_date=date(2026, 4, 30))
        report = build_student_month_report(self.academy_student, date(2026, 4, 1))
        self.assertEqual(report["summary"]["total_lessons"], 1)
        self.assertNotIn("subjects", report)

    @patch.dict("os.environ", {"AUTO_MONTHLY_REPORTS": "True"})
    @patch("tabel_app.views.timezone.localdate", return_value=date(2026, 4, 29))
    def test_personal_gradebook_returns_skip_reason(self, mocked_date):
        month = self.create_subject_lessons()
        from tabel_app.views import save_admin_student_gradebook
        results = save_admin_student_gradebook(self.college_student, "college", month, [
            {"group": self.college_group.pk, "date": "2026-04-28", "grade": "4"},
            {"group": self.second_group.pk, "date": "2026-04-30", "grade": "5"},
        ])
        self.assertEqual(results[0]["reason"], "not_due_today")
