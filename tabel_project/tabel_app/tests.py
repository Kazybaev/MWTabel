import os
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    MonthlyStudentReportAttempt,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
)
from .report import (
    build_dify_inputs,
    build_student_month_report,
    force_send_all_monthly_reports,
    run_dify_workflow,
    send_due_monthly_reports,
    send_student_month_report,
)
from .report_delivery import record_meta_delivery_callback


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
        frontend_index = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
        if frontend_index.exists():
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("text/html", response["Content-Type"])
        else:
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

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
        LessonRecord.objects.create(student=self.student, lesson=second_lesson, grade="Н", comment="Absent")

        client = self.auth_client("mentor", "mentor-pass-123")
        month_value = self.lesson.lesson_date.strftime("%Y-%m")
        response = client.get(f"/api/groups/{self.group.pk}/gradebook/?month={month_value}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        student_row = next(row for row in response.data["rows"] if row["student"]["id"] == self.student.pk)
        self.assertEqual(student_row["average_grade"], 5.0)
        self.assertEqual(student_row["attendance_count"], 1)

    def test_student_transfer_moves_grades_to_new_group_lessons(self):
        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="5", comment="Great")
        new_group = Group.objects.create(
            course_name="Python Evening",
            mentor=self.mentor,
            study_days=Group.TUE_THU_SUN,
            description="Evening stream",
        )

        client = self.auth_client("admin", "admin-pass-123")
        response = client.patch(
            f"/api/students/{self.student.pk}/",
            {"group": new_group.pk},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.assertEqual(self.student.group, new_group)
        self.assertFalse(LessonRecord.objects.filter(student=self.student, lesson=self.lesson).exists())
        moved_lesson = Lesson.objects.get(group=new_group, lesson_date=self.lesson.lesson_date)
        moved_record = LessonRecord.objects.get(student=self.student, lesson=moved_lesson)
        self.assertEqual(moved_record.grade, "5")
        self.assertEqual(moved_record.comment, "Great")

    def test_admin_can_archive_and_restore_student_with_grades(self):
        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="5", comment="Great")
        new_group = Group.objects.create(
            course_name="Archive Restore Group",
            mentor=self.mentor,
            study_days=Group.TUE_THU_SUN,
        )
        client = self.auth_client("admin", "admin-pass-123")

        archive_response = client.post(f"/api/students/{self.student.pk}/archive/")
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.student.user.refresh_from_db()
        self.assertIsNotNone(self.student.archived_at)
        self.assertFalse(self.student.user.is_active)
        self.assertNotContains(client.get("/api/students/"), "Student User")
        self.assertContains(client.get("/api/students/archived/"), "Student User")

        failed_login = self.client.post(
            "/api/auth/login/",
            {"username": "student", "password": "student-pass-123"},
            format="json",
        )
        self.assertEqual(failed_login.status_code, status.HTTP_400_BAD_REQUEST)

        restore_response = client.post(
            f"/api/students/{self.student.pk}/restore/",
            {"group": new_group.pk},
            format="json",
        )
        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.student.refresh_from_db()
        self.student.user.refresh_from_db()
        self.assertIsNone(self.student.archived_at)
        self.assertTrue(self.student.user.is_active)
        self.assertEqual(self.student.group, new_group)
        moved_lesson = Lesson.objects.get(group=new_group, lesson_date=self.lesson.lesson_date)
        self.assertTrue(
            LessonRecord.objects.filter(student=self.student, lesson=moved_lesson, grade="5").exists()
        )

    def test_only_archived_students_can_be_deleted_permanently(self):
        client = self.auth_client("admin", "admin-pass-123")
        active_delete = client.delete(f"/api/students/{self.student.pk}/")
        self.assertEqual(active_delete.status_code, status.HTTP_404_NOT_FOUND)

        client.post(f"/api/students/{self.student.pk}/archive/")
        archived_delete = client.delete(f"/api/students/{self.student.pk}/")
        self.assertEqual(archived_delete.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StudentProfile.objects.filter(pk=self.student.pk).exists())

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

    @patch("tabel_app.views.send_student_month_report")
    def test_mentor_can_trigger_report_dispatch_endpoint(self, mocked_send_student_month_report):
        mocked_send_student_month_report.return_value = {
            "student_id": self.student.pk,
            "student_name": self.student.user.full_name,
            "status": "sent",
            "dispatch_id": 7,
            "workflow_run_id": "run-007",
        }

        client = self.auth_client("mentor", "mentor-pass-123")
        response = client.post(
            "/api/reports/send/",
            {
                "student_id": self.student.pk,
                "month": "2026-04",
                "run_date": "2026-04-30",
                "dry_run": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mocked_send_student_month_report.assert_called_once()
        called_student = mocked_send_student_month_report.call_args.args[0]
        self.assertEqual(called_student.pk, self.student.pk)
        self.assertEqual(mocked_send_student_month_report.call_args.kwargs["month_start"], date(2026, 4, 1))
        self.assertEqual(mocked_send_student_month_report.call_args.kwargs["run_date"], date(2026, 4, 30))
        self.assertFalse(mocked_send_student_month_report.call_args.kwargs["dry_run"])
        self.assertFalse(mocked_send_student_month_report.call_args.kwargs["force"])
        self.assertEqual(response.data["workflow_run_id"], "run-007")

    def test_student_cannot_trigger_report_dispatch_endpoint(self):
        client = self.auth_client("student", "student-pass-123")
        response = client.post(
            "/api/reports/send/",
            {"student_id": self.student.pk},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("tabel_app.views.force_send_all_monthly_reports")
    def test_only_admin_can_force_send_reports_to_all_students(self, mocked_send_all):
        mocked_send_all.return_value = [
            {"student_id": self.student.pk, "status": "sent"},
            {"student_id": 999, "status": "failed"},
        ]

        admin_response = self.auth_client("admin", "admin-pass-123").post(
            "/api/reports/send-all/",
            {},
            format="json",
        )
        mentor_response = self.auth_client("mentor", "mentor-pass-123").post(
            "/api/reports/send-all/",
            {},
            format="json",
        )

        self.assertEqual(admin_response.status_code, status.HTTP_200_OK)
        self.assertEqual(admin_response.data["total"], 2)
        self.assertEqual(admin_response.data["sent"], 1)
        self.assertEqual(admin_response.data["failed"], 1)
        self.assertEqual(mentor_response.status_code, status.HTTP_403_FORBIDDEN)
        mocked_send_all.assert_called_once()

    def test_mentor_cannot_trigger_report_dispatch_for_foreign_student(self):
        foreign_mentor_user = User.objects.create_user(
            username="mentor-foreign",
            password="mentor-pass-456",
            full_name="Foreign Mentor",
            role=User.ROLE_MENTOR,
        )
        foreign_mentor = MentorProfile.objects.create(user=foreign_mentor_user)
        foreign_group = Group.objects.create(
            course_name="Foreign Group",
            mentor=foreign_mentor,
            study_days=Group.TUE_THU_SUN,
            description="Another mentor group",
        )
        foreign_student_user = User.objects.create_user(
            username="foreign-student",
            password="student-pass-789",
            full_name="Foreign Student",
            role=User.ROLE_STUDENT,
        )
        foreign_student = StudentProfile.objects.create(
            user=foreign_student_user,
            parent_name="Foreign Parent",
            parent_phone="+996700000003",
            group=foreign_group,
        )

        client = self.auth_client("mentor", "mentor-pass-123")
        response = client.post(
            "/api/reports/send/",
            {"student_id": foreign_student.pk},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


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
            study_days=Group.TUE_THU_SUN,
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
        self.assertEqual(payload["summary"]["total_five"], 1)
        self.assertEqual(payload["summary"]["total_four"], 1)
        self.assertEqual(payload["summary"]["total_three"], 0)
        self.assertEqual(payload["summary"]["total_two"], 0)
        self.assertEqual(payload["period"]["last_lesson_date"], "2026-04-30")
        self.assertEqual(len(payload["lessons"]), 3)

    def test_build_dify_inputs_matches_workflow_fields(self):
        LessonRecord.objects.create(student=self.student, lesson=self.first_lesson, grade="5", comment="Great")
        LessonRecord.objects.create(student=self.student, lesson=self.second_lesson, grade="4", comment="Stable")
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="\u041d", comment="Absent")
        payload = build_student_month_report(self.student, month_start=self.month_start)

        inputs = build_dify_inputs(payload)

        self.assertEqual(
            set(inputs.keys()),
            {
                "report",
                "student_name",
                "recipient_name",
                "recipient_phone",
                "group_name",
                "mentor_name",
                "month",
                "average_grade",
                "attendance_count",
                "absence_count",
                "total_five",
                "total_four",
                "total_three",
                "total_two",
                "attendance_rate",
            },
        )
        self.assertEqual(inputs["student_name"], "Report Student")
        self.assertEqual(inputs["recipient_phone"], "+996700123456")
        self.assertEqual(inputs["group_name"], "Motion Web")
        self.assertEqual(inputs["total_five"], 1)
        self.assertEqual(inputs["total_four"], 1)
        self.assertEqual(inputs["total_three"], 0)
        self.assertEqual(inputs["total_two"], 0)

    @patch("tabel_app.report.request.urlopen")
    def test_run_dify_workflow_sends_user_agent_header(self, mocked_urlopen):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"workflow_run_id":"run-ua"}'

        def fake_urlopen(http_request, timeout=0):
            captured["headers"] = {key.lower(): value for key, value in http_request.header_items()}
            captured["timeout"] = timeout
            return FakeResponse()

        mocked_urlopen.side_effect = fake_urlopen

        with patch.dict(
            os.environ,
            {
                "DIFY_API_KEY": "app-test-key",
                "DIFY_API_URL": "https://api.dify.ai/v1/workflows/run",
            },
            clear=False,
        ):
            response_payload = run_dify_workflow(
                {"student_name": "Report Student", "month": "2026-04"},
                "report:1:2026-04",
            )

        self.assertEqual(response_payload["workflow_run_id"], "run-ua")
        self.assertIn("user-agent", captured["headers"])
        self.assertIn("TabelBackend/1.0", captured["headers"]["user-agent"])

    @patch("tabel_app.report.time.sleep")
    @patch("tabel_app.report.run_dify_workflow")
    def test_reports_are_sent_individually_on_last_lesson_day(self, mocked_run_dify_workflow, mocked_sleep):
        def confirm_message(inputs, user_key):
            record_meta_delivery_callback(
                {"report": inputs["report"]}, 200,
                {"messages": [{"id": f"message-{inputs['report']['student']['id']}"}]},
            )
            return {"workflow_run_id": "run-confirmed", "data": {"status": "succeeded"}}
        mocked_run_dify_workflow.side_effect = confirm_message
        LessonRecord.objects.create(student=self.student, lesson=self.first_lesson, grade="5")
        LessonRecord.objects.create(student=self.second_student, lesson=self.first_lesson, grade="4")
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")
        LessonRecord.objects.create(student=self.second_student, lesson=self.third_lesson, grade="4")

        early_results = send_due_monthly_reports(run_date=date(2026, 4, 29))
        due_results = send_due_monthly_reports(run_date=date(2026, 4, 30))
        second_due_results = send_due_monthly_reports(run_date=date(2026, 4, 30))

        self.assertEqual(mocked_run_dify_workflow.call_count, 2)
        mocked_sleep.assert_called_once_with(10)
        self.assertTrue(all(result["status"] == "skipped" for result in early_results))
        self.assertEqual(
            [result["status"] for result in due_results],
            ["sent", "sent"],
        )
        self.assertTrue(all(result["reason"] == "already_sent" for result in second_due_results))
        self.assertEqual(MonthlyStudentReportDispatch.objects.count(), 2)

    @patch("tabel_app.report.run_dify_workflow")
    def test_report_waits_until_student_has_mark_on_last_lesson(self, mocked_run_dify_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.first_lesson, grade="5")

        results = send_due_monthly_reports(
            run_date=date(2026, 4, 30),
            student_id=self.student.pk,
        )

        self.assertEqual(results[0]["status"], "skipped")
        self.assertEqual(results[0]["reason"], "trigger_lesson_not_marked")
        mocked_run_dify_workflow.assert_not_called()
        self.assertEqual(MonthlyStudentReportDispatch.objects.count(), 0)

    @patch("tabel_app.report.run_dify_workflow")
    def test_report_uses_last_actual_lesson_instead_of_calendar_schedule(self, mocked_run_dify_workflow):
        self.third_lesson.delete()
        LessonRecord.objects.create(student=self.student, lesson=self.first_lesson, grade="5")
        LessonRecord.objects.create(student=self.student, lesson=self.second_lesson, grade="4")

        results = send_due_monthly_reports(
            run_date=date(2026, 4, 30),
            student_id=self.student.pk,
        )

        self.assertEqual(results[0]["status"], "skipped")
        self.assertEqual(results[0]["reason"], "not_due_today")
        self.assertEqual(results[0]["trigger_date"], "2026-04-13")
        preview = send_due_monthly_reports(run_date=date(2026, 4, 13), student_id=self.student.pk, dry_run=True)
        self.assertEqual(preview[0]["status"], "dry_run")
        mocked_run_dify_workflow.assert_not_called()
        self.assertEqual(MonthlyStudentReportDispatch.objects.count(), 0)

    @patch("tabel_app.report.run_dify_workflow")
    def test_successful_report_is_not_resent_even_with_force(self, mocked_run_dify_workflow):
        def confirm_message(inputs, user_key):
            record_meta_delivery_callback({"report": inputs["report"]}, 200, {"messages": [{"id": "confirmed"}]})
            return {"workflow_run_id": "run-1"}
        mocked_run_dify_workflow.side_effect = confirm_message
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")

        first_results = send_due_monthly_reports(
            run_date=date(2026, 4, 30),
            student_id=self.student.pk,
        )
        second_results = send_due_monthly_reports(
            run_date=date(2026, 5, 1),
            month_start=self.month_start,
            student_id=self.student.pk,
            force=True,
        )

        self.assertEqual(first_results[0]["status"], "sent")
        self.assertEqual(second_results[0]["status"], "skipped")
        self.assertEqual(second_results[0]["reason"], "not_due_today")
        self.assertEqual(mocked_run_dify_workflow.call_count, 1)

    @patch("tabel_app.report.run_dify_workflow")
    def test_admin_bulk_service_preserves_schedule_marks_and_previous_success(self, mocked_workflow):
        existing = MonthlyStudentReportDispatch.objects.create(
            student=self.student, month=self.month_start, trigger_date=date(2026, 4, 30),
            status=MonthlyStudentReportDispatch.STATUS_SUCCEEDED, attempts=1,
        )
        early = force_send_all_monthly_reports(run_date=date(2026, 4, 10), month_start=self.month_start)
        self.assertTrue(all(result["reason"] == "not_due_today" for result in early))
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")
        due = force_send_all_monthly_reports(run_date=date(2026, 4, 30), month_start=self.month_start)
        self.assertEqual([result["reason"] for result in due], ["already_sent", "trigger_lesson_not_marked"])
        mocked_workflow.assert_not_called()
        existing.refresh_from_db()
        self.assertEqual(existing.attempts, 1)
        self.assertEqual(existing.delivery_attempts.count(), 0)

    @patch("tabel_app.report.run_dify_workflow")
    def test_failed_report_is_logged_for_retry(self, mocked_run_dify_workflow):
        mocked_run_dify_workflow.side_effect = RuntimeError("Dify is unavailable")
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")

        results = send_due_monthly_reports(
            run_date=date(2026, 4, 30),
            student_id=self.student.pk,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "failed")
        dispatch = MonthlyStudentReportDispatch.objects.get(student=self.student, month=self.month_start)
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_FAILED)
        self.assertEqual(dispatch.attempts, 1)

    def build_callback_payload(self, meta_status_code=200, meta_response=None):
        report = build_student_month_report(self.student, month_start=self.month_start)
        return {
            "delivery": {
                "event": "student_monthly_report_sent",
                "channel": "meta_whatsapp",
                "student_name": self.student.user.full_name,
                "recipient_phone": str(self.student.parent_phone),
                "month": "2026-04",
                "report": report,
                "meta_request": {"messaging_product": "whatsapp"},
            },
            "meta_status_code": meta_status_code,
            "meta_response": meta_response if meta_response is not None else {"messages": [{"id": "wamid.local-1"}]},
        }

    def create_pending_dispatch(self):
        dispatch = MonthlyStudentReportDispatch.objects.create(
            student=self.student,
            month=self.month_start,
            trigger_date=date(2026, 4, 30),
            status=MonthlyStudentReportDispatch.STATUS_PENDING,
            attempts=1,
            payload=build_student_month_report(self.student, month_start=self.month_start),
        )
        MonthlyStudentReportAttempt.objects.create(
            dispatch=dispatch,
            attempt_number=1,
            status=dispatch.status,
            payload=dispatch.payload,
        )
        return dispatch

    @patch.dict(os.environ, {"BACKEND_REPORT_CALLBACK_TOKEN": "local-callback-token-at-least-32-chars"}, clear=False)
    def test_meta_callback_requires_valid_token(self):
        self.create_pending_dispatch()
        response = self.client.post("/api/report-logs/", self.build_callback_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch.dict(os.environ, {"BACKEND_REPORT_CALLBACK_TOKEN": "local-callback-token-at-least-32-chars"}, clear=False)
    def test_meta_callback_stores_success_idempotently(self):
        dispatch = self.create_pending_dispatch()
        headers = {"HTTP_AUTHORIZATION": "Bearer local-callback-token-at-least-32-chars"}

        first = self.client.post("/api/report-logs/", self.build_callback_payload(), format="json", **headers)
        second = self.client.post("/api/report-logs/", self.build_callback_payload(), format="json", **headers)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertFalse(first.data["duplicate"])
        self.assertTrue(second.data["duplicate"])
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_SUCCEEDED)
        self.assertEqual(dispatch.response_payload["meta"]["status_code"], 200)
        self.assertIn("Motion Web IT академиясынан", dispatch.response_payload["meta"]["rendered_text"])
        self.assertIn("Report Student", dispatch.response_payload["meta"]["rendered_text"])
        self.assertIsNotNone(dispatch.sent_at)
        self.assertEqual(MonthlyStudentReportDispatch.objects.count(), 1)

    @patch.dict(os.environ, {"BACKEND_REPORT_CALLBACK_TOKEN": "local-callback-token-at-least-32-chars"}, clear=False)
    def test_meta_callback_stores_failure(self):
        dispatch = self.create_pending_dispatch()
        response = self.client.post(
            "/api/report-logs/",
            self.build_callback_payload(400, {"error": {"message": "Invalid recipient"}}),
            format="json",
            HTTP_AUTHORIZATION="Bearer local-callback-token-at-least-32-chars",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_FAILED)
        self.assertIn("400", dispatch.error_message)

    @patch("tabel_app.report.run_dify_workflow")
    def test_meta_failure_is_not_overwritten_by_late_dify_success(self, mocked_run_dify_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")

        def complete_workflow_after_callback(inputs, user_key):
            record_meta_delivery_callback(
                delivery={"report": inputs["report"], "meta_request": {"messaging_product": "whatsapp"}},
                meta_status_code=400,
                meta_response={"error": {"message": "Invalid recipient"}},
            )
            return {"workflow_run_id": "run-after-failed-meta"}

        mocked_run_dify_workflow.side_effect = complete_workflow_after_callback
        results = send_due_monthly_reports(
            run_date=date(2026, 4, 30),
            student_id=self.student.pk,
        )

        dispatch = MonthlyStudentReportDispatch.objects.get(student=self.student, month=self.month_start)
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_FAILED)
        self.assertEqual(dispatch.response_payload["meta"]["status_code"], 400)
        self.assertEqual(dispatch.response_payload["dify"]["workflow_run_id"], "run-after-failed-meta")

    @patch.dict(os.environ, {"DIFY_ACCEPT_PARTIAL_SUCCESS": "False"}, clear=False)
    @patch("tabel_app.report.run_dify_workflow")
    def test_partial_dify_result_without_callback_is_failed(self, mocked_run_dify_workflow):
        mocked_run_dify_workflow.return_value = {
            "workflow_run_id": "run-partial",
            "data": {"status": "partial-succeeded", "error": None},
        }
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")

        results = send_due_monthly_reports(run_date=date(2026, 4, 30), student_id=self.student.pk)

        dispatch = MonthlyStudentReportDispatch.objects.get(student=self.student, month=self.month_start)
        self.assertEqual(results[0]["status"], "failed")
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_FAILED)
        self.assertIsNone(dispatch.sent_at)
        self.assertIn("partial-succeeded", dispatch.error_message)

    @patch.dict(os.environ, {"DIFY_ACCEPT_PARTIAL_SUCCESS": "True"}, clear=False)
    @patch("tabel_app.report.run_dify_workflow")
    def test_partial_result_needs_delivery_confirmation_even_in_local_mode(
        self,
        mocked_run_dify_workflow,
    ):
        mocked_run_dify_workflow.return_value = {
            "workflow_run_id": "run-local-partial",
            "data": {
                "status": "partial-succeeded",
                "outputs": {"clean_phone": "996700123456"},
            },
        }
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")

        results = send_due_monthly_reports(
            run_date=date(2026, 4, 30),
            student_id=self.student.pk,
        )

        dispatch = MonthlyStudentReportDispatch.objects.get(student=self.student, month=self.month_start)
        self.assertEqual(results[0]["status"], "pending")
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_PENDING)
        self.assertEqual(dispatch.error_message, "")
        self.assertIsNone(dispatch.sent_at)

    @patch("tabel_app.report.run_dify_workflow")
    def test_successful_meta_callback_wins_over_partial_dify_result(self, mocked_run_dify_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")

        def complete_workflow_after_callback(inputs, user_key):
            record_meta_delivery_callback(
                delivery={"report": inputs["report"], "rendered_text": "Exact message"},
                meta_status_code=200,
                meta_response={"messages": [{"id": "wamid.success"}]},
            )
            return {"workflow_run_id": "run-partial-after-meta", "data": {"status": "partial-succeeded"}}

        mocked_run_dify_workflow.side_effect = complete_workflow_after_callback
        results = send_due_monthly_reports(run_date=date(2026, 4, 30), student_id=self.student.pk)

        dispatch = MonthlyStudentReportDispatch.objects.get(student=self.student, month=self.month_start)
        self.assertEqual(results[0]["status"], "sent")
        self.assertEqual(dispatch.status, MonthlyStudentReportDispatch.STATUS_SUCCEEDED)
        self.assertEqual(dispatch.response_payload["meta"]["rendered_text"], "Exact message")

    def test_only_admin_can_read_report_conversations(self):
        self.create_pending_dispatch()
        admin = User.objects.create_user(
            username="report-admin",
            password="admin-pass-123",
            full_name="Report Admin",
            role=User.ROLE_ADMIN,
        )
        admin_client = APIClient()
        admin_client.force_authenticate(admin)
        mentor_client = APIClient()
        mentor_client.force_authenticate(self.mentor.user)

        admin_list = admin_client.get("/api/reports/conversations/")
        admin_detail = admin_client.get(f"/api/reports/conversations/{self.student.pk}/")
        mentor_list = mentor_client.get("/api/reports/conversations/")

        self.assertEqual(admin_list.status_code, status.HTTP_200_OK)
        self.assertEqual(admin_list.data[0]["student_name"], "Report Student")
        self.assertEqual(admin_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(len(admin_detail.data["messages"]), 1)
        self.assertIn("Motion Web IT академиясынан", admin_detail.data["messages"][0]["rendered_text"])
        self.assertEqual(mentor_list.status_code, status.HTTP_403_FORBIDDEN)

    @patch("tabel_app.report.run_dify_workflow")
    def test_workflow_response_never_confirms_delivery_without_callback(self, mocked_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")
        for payload in ({}, {"raw_response": "not json"}, {"data": {"status": "running"}}, {"data": {"status": "succeeded"}}):
            with self.subTest(payload=payload):
                MonthlyStudentReportDispatch.objects.all().delete()
                mocked_workflow.return_value = payload
                result = send_student_month_report(self.student, run_date=date(2026, 4, 30))
                self.assertEqual(result["status"], "pending")
                dispatch = MonthlyStudentReportDispatch.objects.get()
                self.assertIsNone(dispatch.sent_at)
                self.assertEqual(dispatch.delivery_attempts.get().status, "pending")

    @patch("tabel_app.report.run_dify_workflow")
    def test_force_cannot_restart_pending_attempt(self, mocked_workflow):
        pending = self.create_pending_dispatch()
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="\u041d")
        result = send_student_month_report(self.student, run_date=date(2026, 4, 30), force=True)
        self.assertEqual(result["reason"], "send_already_in_progress")
        mocked_workflow.assert_not_called()
        pending.refresh_from_db()
        self.assertEqual(pending.attempts, 1)

    @patch("tabel_app.report.run_dify_workflow")
    def test_callback_success_survives_workflow_exception(self, mocked_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="\u041d")
        def confirm_then_timeout(inputs, user_key):
            record_meta_delivery_callback({"report": inputs["report"]}, 200, {"messages": [{"id": "accepted"}]})
            raise TimeoutError("Response timed out after message acceptance")
        mocked_workflow.side_effect = confirm_then_timeout
        result = send_student_month_report(self.student, run_date=date(2026, 4, 30))
        self.assertEqual(result["status"], "sent")
        dispatch = MonthlyStudentReportDispatch.objects.get()
        self.assertEqual(dispatch.status, "succeeded")
        self.assertIsNotNone(dispatch.sent_at)
        second = send_student_month_report(self.student, run_date=date(2026, 4, 30), force=True)
        self.assertEqual(second["reason"], "already_sent")
        self.assertEqual(mocked_workflow.call_count, 1)

    def test_late_failure_callback_cannot_erase_confirmed_success(self):
        dispatch = self.create_pending_dispatch()
        callback = self.build_callback_payload()
        record_meta_delivery_callback(**callback)
        dispatch.refresh_from_db()
        sent_at = dispatch.sent_at
        record_meta_delivery_callback(**self.build_callback_payload(400, {"error": "late failure"}))
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, "succeeded")
        self.assertEqual(dispatch.sent_at, sent_at)
        self.assertEqual(dispatch.response_payload["meta"]["status_code"], 200)

    def test_callback_without_message_id_is_not_success(self):
        dispatch = self.create_pending_dispatch()
        record_meta_delivery_callback(**self.build_callback_payload(200, {}))
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, "failed")
        self.assertIsNone(dispatch.sent_at)

    @patch("tabel_app.report.run_dify_workflow")
    def test_retry_rejects_callback_from_old_attempt(self, mocked_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="5")
        mocked_workflow.side_effect = RuntimeError("first attempt failed")
        send_student_month_report(self.student, run_date=date(2026, 4, 30))
        old_payload = MonthlyStudentReportDispatch.objects.get().payload
        mocked_workflow.side_effect = None
        mocked_workflow.return_value = {"data": {"status": "succeeded"}}
        result = send_student_month_report(self.student, run_date=date(2026, 4, 30))
        self.assertEqual(result["status"], "pending")
        with self.assertRaises(ValueError):
            record_meta_delivery_callback({"report": old_payload}, 200, {"messages": [{"id": "old"}]})
        dispatch = MonthlyStudentReportDispatch.objects.get()
        record_meta_delivery_callback({"report": dispatch.payload}, 200, {"messages": [{"id": "new"}]})
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, "succeeded")
        self.assertEqual(list(dispatch.delivery_attempts.order_by("attempt_number").values_list("status", flat=True)), ["failed", "succeeded"])

    @patch("tabel_app.report.run_dify_workflow")
    def test_blank_record_on_last_lesson_does_not_trigger_report(self, mocked_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="")
        result = send_student_month_report(self.student, run_date=date(2026, 4, 30))
        self.assertEqual(result["reason"], "trigger_lesson_not_marked")
        mocked_workflow.assert_not_called()
        report = build_student_month_report(self.student, self.month_start)
        self.assertEqual(report["summary"]["unmarked_count"], 3)

    @patch("tabel_app.report.run_dify_workflow")
    def test_archived_student_cannot_send_report_directly(self, mocked_workflow):
        from django.utils import timezone
        self.student.archived_at = timezone.now()
        result = send_student_month_report(self.student, run_date=date(2026, 4, 30))
        self.assertEqual(result["reason"], "inactive_student")
        mocked_workflow.assert_not_called()

    @patch.dict(os.environ, {"AUTO_MONTHLY_REPORTS": "True"}, clear=False)
    @patch("tabel_app.views.timezone.localdate", return_value=date(2026, 4, 29))
    @patch("tabel_app.report.run_dify_workflow")
    def test_gradebook_response_keeps_report_skip_reason(self, mocked_workflow, mocked_date):
        from .views import dispatch_due_reports_after_gradebook_save
        results = dispatch_due_reports_after_gradebook_save([self.student], self.month_start)
        self.assertEqual(results[0]["reason"], "not_due_today")
        mocked_workflow.assert_not_called()

    @patch.dict(os.environ, {"AUTO_MONTHLY_REPORTS": "False"}, clear=False)
    @patch("tabel_app.views.send_student_month_report")
    def test_disabled_automatic_reports_remain_disabled(self, mocked_send):
        from .views import dispatch_due_reports_after_gradebook_save
        self.assertEqual(dispatch_due_reports_after_gradebook_save([self.student], self.month_start), [])
        mocked_send.assert_not_called()

    @patch("tabel_app.report.run_dify_workflow")
    def test_previous_month_is_not_automatically_sent_in_next_month(self, mocked_workflow):
        LessonRecord.objects.create(student=self.student, lesson=self.third_lesson, grade="\u041d")
        results = send_due_monthly_reports(run_date=date(2026, 5, 1), month_start=self.month_start)
        self.assertTrue(all(result["reason"] == "not_due_today" for result in results))
        mocked_workflow.assert_not_called()
