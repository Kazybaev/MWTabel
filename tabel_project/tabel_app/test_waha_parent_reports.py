import json
import os
from datetime import date
from unittest.mock import patch
from urllib.error import URLError

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    MonthlyStudentReportBatchItem,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
    WahaParentReportBatchItem,
    WahaTestReportBatch,
    WahaTestReportBatchItem,
)
from .report_queue import enqueue_monthly_report_batch
from .report import send_student_month_report
from .waha_parent_reports import (
    WahaParentConfigurationError,
    claim_next_waha_parent_item,
    confirm_waha_parent_batch,
    get_waha_parent_configuration,
    prepare_waha_parent_batch,
    process_waha_parent_item,
    run_waha_parent_worker,
)


WAHA_PARENT_ENV = {
    "WAHA_PARENT_REPORTS_ENABLED": "true",
    "WAHA_PARENT_WORKER_ENABLED": "true",
    "WAHA_PARENT_CLIENT_API_KEY": "test-waha-parent-api-key",
    "WAHA_API_URL": "http://waha-test:3000",
    "WAHA_SESSION": "default",
    "WAHA_PARENT_SERVER_API_KEY_CONFIGURED": "true",
}


class WahaParentReportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="waha-parent-admin",
            password="test-password",
            full_name="WAHA Parent Admin",
            role=User.ROLE_ADMIN,
        )
        mentor_user = User.objects.create_user(
            username="waha-parent-mentor",
            password="test-password",
            full_name="WAHA Parent Mentor",
            role=User.ROLE_MENTOR,
        )
        mentor = MentorProfile.objects.create(user=mentor_user)
        self.group = Group.objects.create(
            course_name="WAHA Parent Group",
            mentor=mentor,
            study_days=Group.MON_WED_SAT,
        )
        student_user = User.objects.create_user(
            username="waha-parent-student",
            password="test-password",
            full_name="WAHA Parent Student",
            role=User.ROLE_STUDENT,
        )
        self.student = self.group.students.create(
            user=student_user,
            parent_name="Parent",
            parent_phone="+996700000001",
        )
        self.month = date(2026, 8, 1)
        self.lesson = Lesson.objects.create(
            group=self.group,
            lesson_date=date(2026, 8, 31),
            topic="Monthly report lesson",
        )
        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="5")

    def prepare_batch(self, today=date(2026, 8, 31)):
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=today):
            return prepare_waha_parent_batch(
                created_by=self.admin,
                month=self.month,
                organization_type="academy",
                students=[self.student],
                requested_filters={},
            )

    def confirm_batch(self, batch):
        with patch.dict(os.environ, WAHA_PARENT_ENV, clear=False):
            return confirm_waha_parent_batch(batch.pk)

    def test_preparation_is_draft_routes_to_parent_and_never_sends(self):
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            with patch("tabel_app.waha_parent_reports.request.urlopen") as send:
                batch = self.prepare_batch()

        item = batch.items.get()
        self.assertEqual(batch.status, "draft")
        self.assertEqual(item.status, WahaParentReportBatchItem.STATUS_DRAFT)
        self.assertEqual(str(item.recipient_phone), "+996700000001")
        self.assertNotIn("parent_phone", item.report_payload["student"])
        self.assertNotIn("+996700000001", item.message_text)
        send.assert_not_called()

    def test_preparation_requires_month_mark_but_not_group_last_lesson_date(self):
        self.lesson.records.all().delete()
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            no_mark_batch = self.prepare_batch()
        self.assertEqual(no_mark_batch.items.get().status, WahaParentReportBatchItem.STATUS_SKIPPED)
        self.assertIn("No marked lesson", no_mark_batch.items.get().error_message)

        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="5")
        batch = self.prepare_batch(today=date(2026, 8, 30))
        self.assertEqual(batch.items.get().status, WahaParentReportBatchItem.STATUS_DRAFT)

    def test_confirmation_is_not_limited_to_group_last_lesson_date(self):
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 30)):
            batch = self.prepare_batch(today=date(2026, 8, 30))

        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 9, 15)):
            confirmed = self.confirm_batch(batch)

        self.assertEqual(confirmed.status, "queued")
        self.assertEqual(
            confirmed.items.get().status,
            WahaParentReportBatchItem.STATUS_QUEUED,
        )

    def test_confirm_requires_both_explicit_feature_flags(self):
        batch = self.prepare_batch()
        with patch.dict(
            os.environ,
            {
                "WAHA_PARENT_REPORTS_ENABLED": "false",
                "WAHA_PARENT_WORKER_ENABLED": "false",
                "WAHA_PARENT_CLIENT_API_KEY": "",
                "WAHA_PARENT_SERVER_API_KEY_CONFIGURED": "false",
            },
            clear=False,
        ):
            with self.assertRaises(WahaParentConfigurationError):
                confirm_waha_parent_batch(batch.pk)

        batch.items.get().refresh_from_db()
        self.assertEqual(batch.items.get().status, WahaParentReportBatchItem.STATUS_DRAFT)

    def test_production_configuration_is_disabled_without_separate_credentials(self):
        with patch.dict(
            os.environ,
            {
                "WAHA_PARENT_REPORTS_ENABLED": "false",
                "WAHA_PARENT_WORKER_ENABLED": "false",
                "WAHA_PARENT_CLIENT_API_KEY": "",
                "WAHA_PARENT_CLIENT_API_KEY_CONFIGURED": "false",
                "WAHA_PARENT_SERVER_API_KEY_CONFIGURED": "false",
            },
            clear=False,
        ):
            config = get_waha_parent_configuration()

        self.assertFalse(config["ready"])
        self.assertFalse(config["enabled"])
        self.assertFalse(config["worker_enabled"])

    def test_confirm_then_worker_sends_only_to_parent_phone(self):
        batch = self.prepare_batch()
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            batch = self.confirm_batch(batch)
        item = claim_next_waha_parent_item()
        self.assertEqual(item.status, WahaParentReportBatchItem.STATUS_PROCESSING)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"id":{"_serialized":"message-id"}}'

        with patch.dict(os.environ, WAHA_PARENT_ENV, clear=False):
            with patch("tabel_app.waha_parent_reports.request.urlopen", return_value=FakeResponse()) as send:
                result = process_waha_parent_item(item.pk)

        request_obj = send.call_args.args[0]
        request_body = json.loads(request_obj.data)
        self.assertEqual(request_body["chatId"], "996700000001@c.us")
        self.assertIn("WAHA Parent Student", request_body["text"])
        self.assertEqual(result["status"], WahaParentReportBatchItem.STATUS_ACCEPTED)
        self.assertEqual(batch.items.get().status, WahaParentReportBatchItem.STATUS_ACCEPTED)

    def test_unknown_delivery_is_never_requeued(self):
        batch = self.prepare_batch()
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            self.confirm_batch(batch)
        item = claim_next_waha_parent_item()
        with patch.dict(os.environ, WAHA_PARENT_ENV, clear=False):
            with patch("tabel_app.waha_parent_reports.request.urlopen", side_effect=URLError("timeout")):
                result = process_waha_parent_item(item.pk)
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            repeated = self.prepare_batch()

        self.assertEqual(result["status"], WahaParentReportBatchItem.STATUS_UNKNOWN)
        self.assertEqual(repeated.items.get().status, WahaParentReportBatchItem.STATUS_SKIPPED)

    def test_worker_will_not_claim_queue_when_session_is_not_working(self):
        batch = self.prepare_batch()
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            self.confirm_batch(batch)

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"status":"SCAN_QR_CODE"}'

        with patch.dict(os.environ, WAHA_PARENT_ENV, clear=False):
            with patch("tabel_app.waha_parent_reports.request.urlopen", return_value=FakeResponse()):
                with self.assertRaises(WahaParentConfigurationError):
                    run_waha_parent_worker(once=True)

        self.assertEqual(batch.items.get().status, WahaParentReportBatchItem.STATUS_QUEUED)

    def test_worker_pauses_queue_during_whatsapp_reachout_timelock(self):
        batch = self.prepare_batch()
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            self.confirm_batch(batch)

        class FakeResponse:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return self.body

        with patch.dict(os.environ, WAHA_PARENT_ENV, clear=False):
            with patch(
                "tabel_app.waha_parent_reports.request.urlopen",
                side_effect=[
                    FakeResponse(b'{"status":"WORKING"}'),
                    FakeResponse(b'{"isActive":true,"timeEnforcementEnds":1900000000}'),
                ],
            ):
                with self.assertRaisesRegex(WahaParentConfigurationError, "timelock is active"):
                    run_waha_parent_worker(once=True)

        self.assertEqual(batch.items.get().status, WahaParentReportBatchItem.STATUS_QUEUED)

    def test_dify_batch_is_blocked_while_parent_report_is_prepared(self):
        self.prepare_batch()
        batch = enqueue_monthly_report_batch(
            created_by=self.admin,
            month=self.month,
            organization_type="academy",
        )
        item = batch.items.get()
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertIn("WAHA parent report", item.error_message)

    def test_direct_dify_send_is_blocked_while_parent_draft_exists(self):
        self.prepare_batch()
        with patch("tabel_app.report.run_dify_workflow") as send:
            result = send_student_month_report(
                self.student,
                run_date=date(2026, 8, 31),
                month_start=self.month,
                bypass_schedule=True,
                force=True,
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "waha_parent_report_exists")
        self.assertFalse(MonthlyStudentReportDispatch.objects.exists())
        send.assert_not_called()

    def create_waha_test_attempt(self, status_value):
        test_batch = WahaTestReportBatch.objects.create(
            month=self.month,
            organization_type="academy",
            created_by=self.admin,
        )
        return WahaTestReportBatchItem.objects.create(
            batch=test_batch,
            student=self.student,
            month=self.month,
            recipient_phone="+996700000099",
            message_text="test",
            status=status_value,
        )

    def test_dify_queue_is_blocked_by_accepted_or_unknown_waha_test_attempt(self):
        for waha_status in (
            WahaTestReportBatchItem.STATUS_ACCEPTED,
            WahaTestReportBatchItem.STATUS_UNKNOWN,
        ):
            with self.subTest(status=waha_status):
                self.create_waha_test_attempt(waha_status)
                batch = enqueue_monthly_report_batch(
                    created_by=self.admin,
                    month=self.month,
                    organization_type="academy",
                )
                self.assertEqual(
                    batch.items.get().status,
                    MonthlyStudentReportBatchItem.STATUS_SKIPPED,
                )
                batch.delete()
                WahaTestReportBatchItem.objects.all().delete()

    def test_direct_dify_send_is_blocked_by_waha_test_attempt(self):
        self.create_waha_test_attempt(WahaTestReportBatchItem.STATUS_UNKNOWN)
        with patch("tabel_app.report.run_dify_workflow") as send:
            result = send_student_month_report(
                self.student,
                run_date=date(2026, 8, 31),
                month_start=self.month,
                bypass_schedule=True,
                force=True,
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "waha_test_report_exists")
        self.assertFalse(MonthlyStudentReportDispatch.objects.exists())
        send.assert_not_called()

    def test_existing_dify_dispatch_blocks_parent_preparation(self):
        MonthlyStudentReportDispatch.objects.create(
            student=self.student,
            month=self.month,
            trigger_date=date(2026, 8, 31),
            status=MonthlyStudentReportDispatch.STATUS_FAILED,
        )
        batch = self.prepare_batch()
        item = batch.items.get()
        self.assertEqual(item.status, WahaParentReportBatchItem.STATUS_SKIPPED)
        self.assertIn("Dify/Meta dispatch", item.error_message)

    def test_confirmation_requires_a_freshly_reviewed_report_snapshot(self):
        batch = self.prepare_batch()
        LessonRecord.objects.filter(student=self.student, lesson=self.lesson).update(grade="4")
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            with patch.dict(os.environ, WAHA_PARENT_ENV, clear=False):
                confirmed = confirm_waha_parent_batch(batch.pk)

        item = confirmed.items.get()
        self.assertEqual(item.status, WahaParentReportBatchItem.STATUS_SKIPPED)
        self.assertIn("data changed after preparation", item.error_message)

    def test_batch_accepts_more_than_500_students(self):
        users = User.objects.bulk_create([
            User(
                username=f"waha-parent-bulk-{index}",
                password="!",
                full_name=f"Bulk Student {index}",
                role=User.ROLE_STUDENT,
            )
            for index in range(501)
        ])
        students = StudentProfile.objects.bulk_create([
            StudentProfile(
                user=user,
                parent_name="Parent",
                parent_phone="+996700000001",
                group=self.group,
            )
            for user in users
        ])
        LessonRecord.objects.bulk_create([
            LessonRecord(student=student, lesson=self.lesson, grade="5")
            for student in students
        ])
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            batch = prepare_waha_parent_batch(
                created_by=self.admin,
                month=self.month,
                organization_type="academy",
                students=students,
                requested_filters={},
            )

        self.assertEqual(batch.items.filter(status=WahaParentReportBatchItem.STATUS_DRAFT).count(), 501)

    def test_admin_endpoint_only_creates_preview_and_non_admin_is_denied(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        with patch("tabel_app.waha_parent_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            with patch("tabel_app.waha_parent_reports.request.urlopen") as send:
                response = client.post(
                    "/api/reports/waha-parent/batches/",
                    {"month": "2026-08", "student_ids": [self.student.pk]},
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(response.data["items"][0]["recipient_masked"], "***0001")
        self.assertIn("message_text", response.data["items"][0])
        send.assert_not_called()

        client.force_authenticate(user=self.student.user)
        denied = client.get("/api/reports/waha-parent/config/")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
