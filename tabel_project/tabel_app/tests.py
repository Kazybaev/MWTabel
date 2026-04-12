from datetime import date
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
)
from .report import build_student_month_report, send_due_monthly_reports


SQLITE_TEST_DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
class TabelApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            password="admin-pass-123",
            full_name="Admin User",
            role=User.ROLE_ADMIN,
        )
        mentor_user = User.objects.create_user(
            username="mentor",
            password="mentor-pass-123",
            full_name="Mentor User",
            role=User.ROLE_MENTOR,
        )
        self.mentor = MentorProfile.objects.create(user=mentor_user)
        self.group = Group.objects.create(
            course_name="Python Morning",
            mentor=self.mentor,
            study_days=Group.MON_WED_SAT,
            description="Backend fundamentals",
        )
        student_user = User.objects.create_user(
            username="student",
            password="student-pass-123",
            full_name="Student User",
            role=User.ROLE_STUDENT,
        )
        self.student = StudentProfile.objects.create(
            user=student_user,
            parent_name="Parent User",
            parent_phone="+996700000001",
            group=self.group,
        )
        second_student_user = User.objects.create_user(
            username="student-two",
            password="student-pass-456",
            full_name="Second Student",
            role=User.ROLE_STUDENT,
        )
        self.second_student = StudentProfile.objects.create(
            user=second_student_user,
            parent_name="Second Parent",
            parent_phone="+996700000002",
            group=self.group,
        )
        self.lesson = Lesson.objects.create(group=self.group, topic="HTTP basics")

    def auth_client(self, username, password):
        login_response = self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}")
        return client

    def test_api_root_is_available(self):
        response = self.client.get("/api-info/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["backend"], "Django REST Framework")

    def test_frontend_shell_is_served_from_root(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/html", response["Content-Type"])

    def test_admin_dashboard_is_available(self):
        client = self.auth_client("admin", "admin-pass-123")
        response = client.get("/api/dashboard/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["dashboard_title"], "Панель администратора")

    def test_mentor_can_save_gradebook(self):
        client = self.auth_client("mentor", "mentor-pass-123")
        month_value = self.lesson.lesson_date.strftime("%Y-%m")
        response = client.post(
            f"/api/groups/{self.group.pk}/gradebook/",
            {
                "month": month_value,
                "entries": [
                    {"student": self.student.pk, "date": self.lesson.lesson_date.isoformat(), "grade": "5"},
                    {"student": self.second_student.pk, "date": self.lesson.lesson_date.isoformat(), "grade": "4"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        record = LessonRecord.objects.get(student=self.student, lesson=self.lesson)
        self.assertEqual(record.grade, "5")
        self.assertEqual(response.data["month_value"], month_value)

    def test_mentor_can_save_absence_mark(self):
        client = self.auth_client("mentor", "mentor-pass-123")
        month_value = self.lesson.lesson_date.strftime("%Y-%m")
        response = client.post(
            f"/api/groups/{self.group.pk}/gradebook/",
            {
                "month": month_value,
                "entries": [
                    {"student": self.student.pk, "date": self.lesson.lesson_date.isoformat(), "grade": "Н"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        record = LessonRecord.objects.get(student=self.student, lesson=self.lesson)
        self.assertEqual(record.grade, "Н")

    def test_student_can_view_only_own_grade_row(self):
        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="4", comment="Good")
        LessonRecord.objects.create(student=self.second_student, lesson=self.lesson, grade="5", comment="Great")

        client = self.auth_client("student", "student-pass-123")
        month_value = self.lesson.lesson_date.strftime("%Y-%m")
        response = client.get(f"/api/groups/{self.group.pk}/gradebook/?month={month_value}")
        detail_response = client.get(f"/api/groups/{self.group.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["rows"]), 1)
        self.assertEqual(response.data["rows"][0]["student"]["full_name"], "Student User")
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data["students"], [])
        self.assertEqual(len(detail_response.data["lessons"][0]["records"]), 1)

    def test_gradebook_returns_average_and_attendance(self):
        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="5", comment="Great")
        second_day = self.lesson.lesson_date.day + 1 if self.lesson.lesson_date.day < 28 else self.lesson.lesson_date.day - 1
        second_lesson = Lesson.objects.create(group=self.group, lesson_date=self.lesson.lesson_date.replace(day=second_day))
        LessonRecord.objects.create(student=self.student, lesson=second_lesson, grade="Рќ", comment="Absent")

        client = self.auth_client("mentor", "mentor-pass-123")
        month_value = self.lesson.lesson_date.strftime("%Y-%m")
        response = client.get(f"/api/groups/{self.group.pk}/gradebook/?month={month_value}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        student_row = next(row for row in response.data["rows"] if row["student"]["id"] == self.student.pk)
        self.assertEqual(student_row["average_grade"], 5.0)
        self.assertEqual(student_row["attendance_count"], 1)

    def test_api_me_returns_logged_user(self):
        client = self.auth_client("mentor", "mentor-pass-123")
        response = client.get("/api/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], User.ROLE_MENTOR)

    def test_student_dashboard_returns_compact_overview(self):
        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="4", comment="Good")
        client = self.auth_client("student", "student-pass-123")
        response = client.get("/api/dashboard/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("recent_grades", response.data)
        self.assertEqual(response.data["student_overview"]["group_name"], "Python Morning")
        self.assertEqual(response.data["student_overview"]["mentor_name"], "Mentor User")
        self.assertEqual(response.data["student_overview"]["grades_count"], 1)
        self.assertEqual(response.data["student_overview"]["attendance_count"], 1)


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
class MonthlyReportServiceTests(APITestCase):
    def setUp(self):
        mentor_user = User.objects.create_user(
            username="mentor-report",
            password="mentor-pass-123",
            full_name="Report Mentor",
            role=User.ROLE_MENTOR,
        )
        self.mentor = MentorProfile.objects.create(user=mentor_user)
        self.group = Group.objects.create(
            course_name="Motion Web",
            mentor=self.mentor,
            study_days=Group.MON_WED_SAT,
            description="Monthly report group",
        )
        self.student_user = User.objects.create_user(
            username="student-report",
            password="student-pass-123",
            full_name="Report Student",
            role=User.ROLE_STUDENT,
        )
        self.student = StudentProfile.objects.create(
            user=self.student_user,
            parent_name="Parent Report",
            parent_phone="+996700123456",
            group=self.group,
        )
        self.second_user = User.objects.create_user(
            username="student-report-two",
            password="student-pass-123",
            full_name="Second Report Student",
            role=User.ROLE_STUDENT,
        )
        self.second_student = StudentProfile.objects.create(
            user=self.second_user,
            parent_name="Second Parent",
            parent_phone="+996700123457",
            group=self.group,
        )
        self.month_start = date(2026, 4, 1)
        self.first_lesson = Lesson.objects.create(group=self.group, lesson_date=date(2026, 4, 6), topic="Intro")
        self.second_lesson = Lesson.objects.create(group=self.group, lesson_date=date(2026, 4, 13), topic="Practice")
        self.third_lesson = Lesson.objects.create(group=self.group, lesson_date=date(2026, 4, 30), topic="Final")

    def test_build_student_month_report_collects_summary(self):
        LessonRecord.objects.create(student=self.student, lesson=self.first_lesson, grade="5", comment="Great")
        LessonRecord.objects.create(student=self.student, lesson=self.second_lesson, grade="4", comment="Stable")
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="\u041d", comment="Absent")

        payload = build_student_month_report(self.student, month_start=self.month_start)

        self.assertEqual(payload["student"]["full_name"], "Report Student")
        self.assertEqual(payload["group"]["course_name"], "Motion Web")
        self.assertEqual(payload["summary"]["total_lessons"], 3)
        self.assertEqual(payload["summary"]["attendance_count"], 2)
        self.assertEqual(payload["summary"]["absence_count"], 1)
        self.assertEqual(payload["summary"]["unmarked_count"], 0)
        self.assertEqual(payload["summary"]["average_grade"], 4.5)
        self.assertEqual(payload["period"]["last_lesson_date"], "2026-04-30")
        self.assertEqual(len(payload["lessons"]), 3)

    @patch("tabel_app.report.run_dify_workflow")
    def test_reports_are_sent_individually_on_last_lesson_day(self, mocked_run_dify_workflow):
        mocked_run_dify_workflow.side_effect = [
            {"workflow_run_id": "run-1", "data": {"status": "succeeded"}},
            {"workflow_run_id": "run-2", "data": {"status": "succeeded"}},
        ]
        LessonRecord.objects.create(student=self.student, lesson=self.first_lesson, grade="5")
        LessonRecord.objects.create(student=self.second_student, lesson=self.first_lesson, grade="4")

        early_results = send_due_monthly_reports(run_date=date(2026, 4, 29))
        due_results = send_due_monthly_reports(run_date=date(2026, 4, 30))
        second_due_results = send_due_monthly_reports(run_date=date(2026, 4, 30))

        self.assertEqual(mocked_run_dify_workflow.call_count, 2)
        self.assertTrue(all(result["status"] == "skipped" for result in early_results))
        self.assertEqual(
            [result["status"] for result in due_results],
            ["sent", "sent"],
        )
        self.assertTrue(all(result["reason"] == "already_sent" for result in second_due_results))
        self.assertEqual(MonthlyStudentReportDispatch.objects.count(), 2)

    @patch("tabel_app.report.run_dify_workflow")
    def test_failed_report_is_logged_for_retry(self, mocked_run_dify_workflow):
        mocked_run_dify_workflow.side_effect = RuntimeError("Dify is unavailable")

        results = send_due_monthly_reports(
            run_date=date(2026, 4, 30),
            student_id=self.student.pk,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "failed")
        dispatch = MonthlyStudentReportDispatch.objects.get(student=self.student, month=self.month_start)
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_FAILED)
        self.assertEqual(dispatch.attempts, 1)
