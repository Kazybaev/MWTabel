import json
import os
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    COLLEGE_BRANCH_KUWAIT,
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    MonthlyStudentReportBatch,
    MonthlyStudentReportBatchItem,
    StudentProfile,
    User,
)
from .report import ReportConfigurationError, build_dify_inputs, build_student_month_report, run_dify_workflow
from .report_delivery import build_report_message_text
from .report_queue import claim_next_report_item, enqueue_monthly_report_batch, process_claimed_report_item


class AcademyWorkflowRoutingTests(TestCase):
    def setUp(self):
        self.keys = patch.dict(os.environ, {
            "DIFY_API_KEY": "shared-key-must-not-route-academy",
            "DIFY_ACADEMY_API_KEY": "academy-key",
            "DIFY_KUWAIT_API_KEY": "kuwait-key",
            "DIFY_AGRARIAN_API_KEY": "",
            "BACKEND_REPORT_CALLBACK_TOKEN": "callback-token-at-least-32-characters",
            "DIFY_API_URL": "https://dify.invalid/v1/workflows/run",
        })
        self.keys.start()
        self.addCleanup(self.keys.stop)
        self.admin = User.objects.create_user(username="academy-admin", role=User.ROLE_ADMIN)
        mentor_user = User.objects.create_user(username="academy-mentor", full_name="Academy Mentor", role=User.ROLE_MENTOR)
        mentor = MentorProfile.objects.create(user=mentor_user, organization_type="academy")
        self.group = Group.objects.create(
            pk=14,
            course_name="ИИ-30",
            mentor=mentor,
            organization_type="academy",
            study_days=Group.MON_WED_SAT,
        )
        student_user = User.objects.create_user(username="academy-student", full_name="Academy Student", role=User.ROLE_STUDENT)
        self.student = StudentProfile.objects.create(
            pk=100,
            user=student_user,
            parent_name="Academy Parent",
            parent_phone="+996700000001",
            group=self.group,
            organization_type="academy",
        )
        for day, grade in ((1, "5"), (2, "4"), (3, "3"), (4, "2")):
            lesson = Lesson.objects.create(group=self.group, lesson_date=date(2026, 9, day))
            LessonRecord.objects.create(student=self.student, lesson=lesson, grade=grade)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def post_batch(self, body, organization="academy", college_branch="kuwait"):
        return self.client.post(
            "/api/reports/send-all/",
            body,
            format="json",
            HTTP_X_ORGANIZATION_TYPE=organization,
            HTTP_X_COLLEGE_BRANCH=college_branch,
        )

    def test_target_academy_request_is_exact_and_persists_route(self):
        response = self.post_batch({
            "organization": "academy",
            "month": "2026-09",
            "group_ids": [14],
            "student_ids": [100],
        })

        self.assertEqual(response.status_code, 202)
        batch = MonthlyStudentReportBatch.objects.get(pk=response.data["id"])
        self.assertEqual(batch.requested_filters["workflow_route"], "academy")
        self.assertEqual(list(batch.items.values_list("student_id", flat=True)), [100])

    def test_request_organization_mismatch_is_rejected_before_queue(self):
        response = self.post_batch({"organization": "college", "month": "2026-09"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(MonthlyStudentReportBatch.objects.count(), 0)

    def test_foreign_student_and_group_are_rejected_instead_of_shrinking_selection(self):
        college_mentor_user = User.objects.create_user(username="college-mentor", role=User.ROLE_MENTOR)
        college_mentor = MentorProfile.objects.create(user=college_mentor_user, organization_type="college")
        college_group = Group.objects.create(
            course_name="Foreign",
            mentor=college_mentor,
            organization_type="college",
            college_branch=COLLEGE_BRANCH_KUWAIT,
        )
        college_user = User.objects.create_user(username="college-student", role=User.ROLE_STUDENT)
        college_student = StudentProfile.objects.create(
            user=college_user,
            parent_phone="+996700000002",
            group=college_group,
            organization_type="college",
            college_branch=COLLEGE_BRANCH_KUWAIT,
        )

        student_response = self.post_batch({
            "organization": "academy", "month": "2026-09", "student_ids": [college_student.pk],
        })
        group_response = self.post_batch({
            "organization": "academy", "month": "2026-09", "group_ids": [college_group.pk],
        })

        self.assertEqual(student_response.status_code, 400)
        self.assertEqual(group_response.status_code, 400)
        self.assertEqual(MonthlyStudentReportBatch.objects.count(), 0)

    def test_missing_academy_key_has_user_safe_error_and_creates_no_queue(self):
        with patch.dict(os.environ, {"DIFY_ACADEMY_API_KEY": ""}):
            response = self.post_batch({"organization": "academy", "month": "2026-09"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("пока не настроена", str(response.data))
        self.assertNotIn("DIFY_", str(response.data))
        self.assertEqual(MonthlyStudentReportBatch.objects.count(), 0)

    def test_academy_contract_has_exact_fifteen_inputs_and_exact_counts(self):
        report = build_student_month_report(self.student, month_start=date(2026, 9, 1))
        inputs = build_dify_inputs(report)

        self.assertEqual(set(inputs), {
            "student_name", "recipient_name", "recipient_phone", "group_name", "mentor_name", "month",
            "average_grade", "attendance_count", "absence_count", "attendance_rate",
            "total_five", "total_four", "total_three", "total_two", "report",
        })
        self.assertEqual([inputs[name] for name in ("total_five", "total_four", "total_three", "total_two")], [1, 1, 1, 1])
        self.assertEqual(inputs["attendance_count"], 4)
        self.assertEqual(inputs["absence_count"], 0)
        self.assertEqual(inputs["report"]["workflow_route"], "academy")

    def test_missing_parent_name_is_not_replaced_with_student_name(self):
        self.student.parent_name = ""
        self.student.save(update_fields=["parent_name"])

        inputs = build_dify_inputs(build_student_month_report(self.student, month_start=date(2026, 9, 1)))

        self.assertEqual(inputs["recipient_name"], "")

    def test_unmarked_lesson_is_explicit_in_snapshot_and_text(self):
        Lesson.objects.create(group=self.group, lesson_date=date(2026, 9, 5))

        report = build_student_month_report(self.student, month_start=date(2026, 9, 1))
        summary = report["summary"]
        self.assertEqual(summary["total_lessons"], 5)
        self.assertEqual(summary["attendance_count"], 4)
        self.assertEqual(summary["absence_count"], 0)
        self.assertEqual(summary["unmarked_count"], 1)
        self.assertEqual(summary["attendance_rate"], 80.0)
        self.assertEqual(
            summary["attendance_status_text"],
            "Белгиленген калуулар (Н): 0; белги коюлбаган сабактар: 1.",
        )
        self.assertIn(summary["attendance_status_text"], build_report_message_text(report))
        self.assertNotIn("сабактан калган жок", build_report_message_text(report))
        self.assertIn(
            "Сентябрь айындагы баалары:\n“5” – 1 даана\n“4” – 1 даана\n“3” – 1 даана\n“2” – 1 даана",
            build_report_message_text(report),
        )

    def test_zero_grade_counts_keep_fixed_positions_in_backend_text(self):
        report = build_student_month_report(self.student, month_start=date(2026, 9, 1))
        report["summary"].update({
            "total_five": 0, "total_four": 3, "total_three": 10, "total_two": 0,
            "absence_count": 0, "unmarked_count": 15,
        })
        text = build_report_message_text(report)
        self.assertIn(
            "Сентябрь айындагы баалары:\n“5” – 0 даана\n“4” – 3 даана\n“3” – 10 даана\n“2” – 0 даана",
            text,
        )
        self.assertIn("Белгиленген калуулар (Н): 0; белги коюлбаган сабактар: 15.", text)

    def test_multiple_academy_grades_for_one_lesson_are_rejected(self):
        lesson = Lesson.objects.get(group=self.group, lesson_date=date(2026, 9, 1))
        LessonRecord.objects.create(student=self.student, lesson=lesson, grade="4", sequence=2)

        with self.assertRaisesRegex(Exception, "больше одной оценки"):
            build_student_month_report(self.student, month_start=date(2026, 9, 1))

    @patch("tabel_app.report.run_dify_workflow")
    def test_manual_api_queue_worker_mock_uses_one_academy_route(self, mocked_dify):
        response = self.post_batch({
            "organization": "academy", "month": "2026-09", "group_ids": [14], "student_ids": [100],
        })
        self.assertEqual(response.status_code, 202)
        item = claim_next_report_item(batch_ids=[response.data["id"]])

        def accepted(inputs, user_key, workflow_route):
            backend = dict(inputs["report"])
            backend.update({
                "provider_status": "accepted",
                "provider_message_id": "wamid.mock-academy",
                "provider_http_status": 200,
                "delivery_confirmed": False,
            })
            return {
                "workflow_run_id": "run-mock-academy",
                "data": {"status": "succeeded", "outputs": {
                    "provider_status": "accepted",
                    "provider_message_id": "wamid.mock-academy",
                    "provider_http_status": 200,
                    "outcome_reason": "accepted in mock",
                    "backend_payload": json.dumps({"report": inputs["report"]}),
                }},
            }

        mocked_dify.side_effect = accepted
        result = process_claimed_report_item(item.pk, item.worker_token)

        item.refresh_from_db()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_ACCEPTED)
        self.assertEqual(mocked_dify.call_args.args[2], "academy")
        self.assertEqual(mocked_dify.call_count, 1)

    @patch("tabel_app.report.run_dify_workflow")
    def test_old_queue_without_route_is_blocked_before_worker_send(self, mocked_dify):
        batch = enqueue_monthly_report_batch(
            created_by=self.admin,
            month=date(2026, 9, 1),
            organization_type="academy",
            student_ids=[self.student.pk],
        )
        batch.requested_filters.pop("workflow_route")
        batch.save(update_fields=["requested_filters", "updated_at"])
        item = claim_next_report_item(batch_ids=[batch.pk])

        result = process_claimed_report_item(item.pk, item.worker_token)

        item.refresh_from_db()
        self.assertEqual(result["reason"], "missing_workflow_route")
        self.assertTrue(item.requires_operator_review)
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_FAILED)
        mocked_dify.assert_not_called()

    @patch("tabel_app.report.request.urlopen")
    def test_route_specific_keys_do_not_fall_back(self, mocked_urlopen):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"workflow_run_id":"mock"}'

        mocked_urlopen.return_value = Response()
        run_dify_workflow({}, "report:100:2026-09", "academy")
        academy_header = mocked_urlopen.call_args.args[0].get_header("Authorization")
        run_dify_workflow({}, "report:200:2026-09", "kuwait")
        kuwait_header = mocked_urlopen.call_args.args[0].get_header("Authorization")

        self.assertEqual(academy_header, "Bearer academy-key")
        self.assertEqual(kuwait_header, "Bearer kuwait-key")
        with self.assertRaisesRegex(ReportConfigurationError, "Аграрного колледжа пока не настроена"):
            run_dify_workflow({}, "report:300:2026-09", "agrarian")
