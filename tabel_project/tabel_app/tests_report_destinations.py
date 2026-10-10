import io
import json
import os
from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Group, Lesson, LessonRecord, MentorProfile, MonthlyStudentReportDispatch, StudentProfile, User
from .report import build_dify_inputs, build_student_month_report, get_dify_run_url, ReportConfigurationError, run_dify_workflow, send_due_monthly_reports


class ReportDestinationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="destination-admin", full_name="Admin", role="ADMIN")
        cls.students = {}
        for organization in ["academy", "college"]:
            mentor_user = User.objects.create_user(username=f"{organization}-mentor", full_name="Mentor", role="MENTOR")
            mentor = MentorProfile.objects.create(user=mentor_user, organization_type=organization)
            group = Group.objects.create(course_name=f"{organization} subject", mentor=mentor, study_days=Group.MON_FRI, organization_type=organization)
            user = User.objects.create_user(username=f"{organization}-student", full_name=f"{organization} student", role="STUDENT")
            student = StudentProfile.objects.create(user=user, group=group, parent_name="Parent", parent_phone="+996700000001", organization_type=organization, college_course="1" if organization == "college" else "")
            lesson = Lesson.objects.create(group=group, lesson_date=date(2026, 4, 30))
            LessonRecord.objects.create(student=student, lesson=lesson, grade="5")
            cls.students[organization] = student

    def report(self, organization):
        return build_student_month_report(self.students[organization], date(2026, 4, 1))

    def admin_client(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        return client

    def test_kuwait_preserves_original_json_contract(self):
        report = self.report("academy")
        report["dispatch"] = {"id": 123, "attempt_number": 2}
        inputs = build_dify_inputs(report)
        self.assertSetEqual(set(inputs), {
            "report", "student_name", "recipient_name", "recipient_phone", "group_name", "mentor_name", "month",
            "average_grade", "attendance_count", "absence_count", "total_five", "total_four", "total_three", "total_two", "attendance_rate",
        })
        self.assertSetEqual(set(inputs["report"]), {"student", "group", "mentor", "period", "summary", "lessons"})
        self.assertSetEqual(set(inputs["report"]["student"]), {"id", "user_id", "full_name", "username", "parent_name", "parent_phone"})
        self.assertSetEqual(set(inputs["report"]["lessons"][0]), {"lesson_id", "date", "topic", "grade", "comment", "status"})
        self.assertEqual(inputs["recipient_phone"], str(self.students["academy"].parent_phone))
        self.assertIn("dispatch", report)  # Serialization must not mutate the stored report.

    def test_agrarian_has_its_own_multi_subject_contract(self):
        inputs = build_dify_inputs(self.report("college"))
        self.assertEqual(inputs["report_type"], "agrarian_monthly_v1")
        self.assertEqual(inputs["organization_type"], "college")
        self.assertEqual(inputs["subjects_count"], 1)
        self.assertEqual(inputs["college_course"], "1")
        self.assertEqual(inputs["subjects"], inputs["report"]["subjects"])
        self.assertEqual(inputs["summary"], inputs["report"]["summary"])

    @patch("tabel_app.report.request.urlopen")
    def test_transport_uses_separate_workflow_keys_urls_and_json(self, mocked_urlopen):
        captured = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"data":{"status":"succeeded"}}'

        def capture(http_request, timeout):
            captured.append((http_request.full_url, http_request.get_header("Authorization"), json.loads(http_request.data)))
            return FakeResponse()

        mocked_urlopen.side_effect = capture
        with patch.dict(os.environ, {
            "DIFY_API_KEY": "legacy-kuwait-key", "DIFY_API_URL": "https://kuwait.example/v1/workflows/run",
            "DIFY_AGRARIAN_API_KEY": "agrarian-key", "DIFY_AGRARIAN_BASE_URL": "https://agrarian.example/v1",
        }, clear=True):
            run_dify_workflow(build_dify_inputs(self.report("academy")), "kuwait-test")
            run_dify_workflow(build_dify_inputs(self.report("college")), "agrarian-test")
        self.assertEqual(captured[0][0], "https://kuwait.example/v1/workflows/run")
        self.assertEqual(captured[0][1], "Bearer legacy-kuwait-key")
        self.assertNotIn("subjects", captured[0][2]["inputs"])
        self.assertEqual(captured[1][0], "https://agrarian.example/v1/workflows/run")
        self.assertEqual(captured[1][1], "Bearer agrarian-key")
        self.assertEqual(captured[1][2]["inputs"]["report_type"], "agrarian_monthly_v1")

    def test_kuwait_override_takes_precedence_over_legacy_url(self):
        with patch.dict(os.environ, {"DIFY_KUWAIT_BASE_URL": "https://new-kuwait.example/v1", "DIFY_API_URL": "https://old.example/v1/workflows/run"}, clear=True):
            self.assertEqual(get_dify_run_url("academy"), "https://new-kuwait.example/v1/workflows/run")

    @patch("tabel_app.report.request.urlopen")
    def test_agrarian_never_falls_back_to_kuwait_credentials(self, mocked_urlopen):
        with patch.dict(os.environ, {"DIFY_API_KEY": "kuwait-key", "DIFY_BASE_URL": "https://kuwait.example/v1"}, clear=True):
            with self.assertRaises(ReportConfigurationError):
                run_dify_workflow(build_dify_inputs(self.report("college")), "agrarian-test")
            with self.assertRaises(ReportConfigurationError):
                get_dify_run_url("college")
        mocked_urlopen.assert_not_called()

    def test_individual_routes_reject_other_destination_and_wrong_header(self):
        client = self.admin_client()
        body = {"student_id": self.students["college"].pk, "month": "2026-04", "run_date": "2026-04-30", "dry_run": True}
        wrong_header = client.post("/api/reports/agrarian/send/", body, format="json")
        self.assertEqual(wrong_header.status_code, 400)
        other_student = client.post("/api/reports/kuwait/send/", body, format="json")
        self.assertEqual(other_student.status_code, 404)
        valid = client.post("/api/reports/agrarian/send/", body, format="json", HTTP_X_ORGANIZATION_TYPE="college")
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.data["destination"], "agrarian")
        self.assertIn("subjects", valid.data["payload"])
        self.assertEqual(MonthlyStudentReportDispatch.objects.count(), 0)

    @patch("tabel_app.views.force_send_all_monthly_reports", return_value=[])
    def test_mass_routes_are_scoped_to_one_destination(self, mocked_send):
        client = self.admin_client()
        for destination, organization in [("kuwait", "academy"), ("agrarian", "college")]:
            response = client.post(f"/api/reports/{destination}/send-all/", {}, format="json", HTTP_X_ORGANIZATION_TYPE=organization)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["destination"], destination)
            self.assertEqual(mocked_send.call_args.kwargs["organization_type"], organization)

    def test_command_destination_selects_only_its_students(self):
        output = io.StringIO()
        call_command("send_monthly_reports", "--destination", "agrarian", "--date", "2026-04-30", "--dry-run", stdout=output)
        self.assertIn("college student", output.getvalue())
        self.assertNotIn("academy student", output.getvalue())
        results = send_due_monthly_reports(run_date=date(2026, 4, 30), organization_type="academy", dry_run=True)
        self.assertEqual([result["student_id"] for result in results], [self.students["academy"].pk])

    def create_callback(self, organization):
        report = self.report(organization)
        dispatch = MonthlyStudentReportDispatch.objects.create(student=self.students[organization], month=date(2026, 4, 1), trigger_date=date(2026, 4, 30), attempts=1, payload=report)
        return dispatch, {"delivery": {"report": report}, "meta_status_code": 200, "meta_response": {"messages": [{"id": f"message-{organization}"}]}}

    @patch.dict(os.environ, {
        "BACKEND_REPORT_CALLBACK_TOKEN": "kuwait-token-at-least-thirty-two-characters",
        "BACKEND_AGRARIAN_REPORT_CALLBACK_TOKEN": "agrarian-token-at-least-thirty-two-characters",
    }, clear=True)
    def test_callback_tokens_and_routes_cannot_mix_destinations(self):
        dispatch, body = self.create_callback("college")
        client = APIClient()
        wrong_token = client.post("/api/reports/agrarian/callback/", body, format="json", HTTP_AUTHORIZATION="Bearer kuwait-token-at-least-thirty-two-characters")
        self.assertEqual(wrong_token.status_code, 401)
        wrong_route = client.post("/api/reports/kuwait/callback/", body, format="json", HTTP_AUTHORIZATION="Bearer kuwait-token-at-least-thirty-two-characters")
        self.assertEqual(wrong_route.status_code, 400)
        valid = client.post("/api/reports/agrarian/callback/", body, format="json", HTTP_AUTHORIZATION="Bearer agrarian-token-at-least-thirty-two-characters")
        self.assertEqual(valid.status_code, 200)
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, "succeeded")

    @patch.dict(os.environ, {"BACKEND_REPORT_CALLBACK_TOKEN": "kuwait-token-at-least-thirty-two-characters"}, clear=True)
    def test_forged_legacy_callback_cannot_update_agrarian_dispatch(self):
        dispatch, body = self.create_callback("college")
        body["delivery"]["report"].pop("organization_type")
        response = APIClient().post("/api/report-logs/", body, format="json", HTTP_AUTHORIZATION="Bearer kuwait-token-at-least-thirty-two-characters")
        self.assertEqual(response.status_code, 404)
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, "pending")
