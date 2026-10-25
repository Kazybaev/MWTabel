import json
import os
from datetime import date, timedelta
from unittest.mock import patch
from urllib.error import URLError

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    User,
    WahaTestReportBatchItem,
)
from .waha_reports import (
    WahaTestConfigurationError,
    claim_next_waha_test_item,
    enqueue_waha_test_batch,
    get_waha_test_configuration,
    process_waha_test_item,
)

WAHA_TEST_ENV = {
    "WAHA_TEST_MODE_ENABLED": "true",
    "WAHA_WORKER_ENABLED": "true",
    "WAHA_TEST_RECIPIENT": "+996700000099",
    "WAHA_CLIENT_API_KEY": "test-waha-api-key",
    "WAHA_API_URL": "http://waha-test:3000",
    "WAHA_SESSION": "test",
    "WAHA_SERVER_API_KEY_CONFIGURED": "true",
}


class WahaTestReportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="waha-admin",
            password="waha-admin-password",
            full_name="WAHA Admin",
            role=User.ROLE_ADMIN,
        )
        self.mentor_user = User.objects.create_user(
            username="waha-mentor",
            password="waha-mentor-password",
            full_name="WAHA Mentor",
            role=User.ROLE_MENTOR,
        )
        mentor = MentorProfile.objects.create(user=self.mentor_user)
        self.group = Group.objects.create(
            course_name="WAHA Test Group",
            mentor=mentor,
            study_days=Group.MON_WED_SAT,
        )
        self.student_user = User.objects.create_user(
            username="waha-student",
            password="waha-student-password",
            full_name="WAHA Student",
            role=User.ROLE_STUDENT,
        )
        self.student = self.group.students.create(
            user=self.student_user,
            parent_name="Parent",
            parent_phone="+996700000001",
        )
        self.month = date(2026, 8, 1)
        self.lesson = Lesson.objects.create(
            group=self.group,
            lesson_date=date(2026, 8, 31),
            topic="Test lesson",
        )
        LessonRecord.objects.create(student=self.student, lesson=self.lesson, grade="5")

    def make_batch(self):
        with patch("tabel_app.waha_reports.timezone.localdate", return_value=date(2026, 8, 31)):
            return enqueue_waha_test_batch(
                created_by=self.admin,
                students=[self.student],
                month=self.month,
                organization_type="academy",
            )

    def test_report_is_skipped_before_last_lesson_date(self):
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            with patch("tabel_app.waha_reports.timezone.localdate", return_value=date(2026, 8, 30)):
                batch = enqueue_waha_test_batch(
                    created_by=self.admin,
                    students=[self.student],
                    month=self.month,
                    organization_type="academy",
                )

        item = batch.items.get()
        self.assertEqual(item.status, WahaTestReportBatchItem.STATUS_SKIPPED)
        self.assertIn("last lesson date", item.error_message)

    def test_report_can_queue_without_record_on_last_lesson_if_month_has_marks(self):
        self.lesson.records.all().delete()
        earlier_lesson = Lesson.objects.create(
            group=self.group,
            lesson_date=date(2026, 8, 29),
            topic="Earlier lesson",
        )
        LessonRecord.objects.create(student=self.student, lesson=earlier_lesson, grade="5")

        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            batch = self.make_batch()

        item = batch.items.get()
        self.assertEqual(item.status, WahaTestReportBatchItem.STATUS_QUEUED)
        self.assertEqual(item.error_message, "")

    def test_config_only_returns_masked_test_recipient(self):
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            config = get_waha_test_configuration()

        self.assertTrue(config["ready"])
        self.assertEqual(config["recipient_masked"], "***0099")
        self.assertNotIn(WAHA_TEST_ENV["WAHA_TEST_RECIPIENT"], str(config))

    def test_test_recipient_must_be_valid_international_number(self):
        with patch.dict(os.environ, {**WAHA_TEST_ENV, "WAHA_TEST_RECIPIENT": "not-a-number"}, clear=False):
            with self.assertRaises(WahaTestConfigurationError):
                self.make_batch()

    def test_queue_snapshot_uses_test_number_and_removes_parent_phone(self):
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            batch = self.make_batch()

        item = batch.items.get()
        self.assertEqual(item.status, WahaTestReportBatchItem.STATUS_QUEUED)
        self.assertEqual(str(item.recipient_phone), WAHA_TEST_ENV["WAHA_TEST_RECIPIENT"])
        self.assertNotIn("parent_phone", item.report_payload["student"])
        self.assertIn("WAHA Student", item.message_text)
        self.assertNotIn("+996700000001", item.message_text)

    def test_repeated_successful_report_is_skipped(self):
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            first = self.make_batch()
            first_item = first.items.get()
            first_item.status = WahaTestReportBatchItem.STATUS_ACCEPTED
            first_item.save(update_fields=["status"])
            second = self.make_batch()

        second_item = second.items.get()
        self.assertEqual(second_item.status, WahaTestReportBatchItem.STATUS_SKIPPED)
        self.assertEqual(WahaTestReportBatchItem.objects.count(), 2)

    def test_admin_endpoint_enqueues_only_when_test_mode_is_configured(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            with patch("tabel_app.waha_reports.timezone.localdate", return_value=date(2026, 8, 31)):
                with patch("tabel_app.waha_reports.request.urlopen") as mocked_urlopen:
                    response = client.post(
                        "/api/reports/waha-test/batches/",
                        {"month": "2026-08", "student_ids": [self.student.pk]},
                        format="json",
                    )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["queued"], 1)
        self.assertEqual(response.data["items"][0]["recipient_masked"], "***0099")
        mocked_urlopen.assert_not_called()

    def test_admin_endpoint_is_disabled_by_default(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        with patch.dict(
            os.environ,
            {
                "WAHA_TEST_MODE_ENABLED": "false",
                "WAHA_WORKER_ENABLED": "false",
                "WAHA_TEST_RECIPIENT": "",
                "WAHA_CLIENT_API_KEY": "",
                "WAHA_SERVER_API_KEY_CONFIGURED": "false",
            },
            clear=False,
        ):
            response = client.post(
                "/api/reports/waha-test/batches/",
                {"month": "2026-08", "student_ids": [self.student.pk]},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(WahaTestReportBatchItem.objects.count(), 0)

    def test_non_admin_cannot_read_waha_test_configuration(self):
        client = APIClient()
        client.force_authenticate(user=self.mentor_user)
        response = client.get("/api/reports/waha-test/config/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_posts_to_test_number_not_parent_phone(self):
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            batch = self.make_batch()
            item = claim_next_waha_test_item()

            class FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b'{"id":{"_serialized":"message-id"}}'

            with patch("tabel_app.waha_reports.request.urlopen", return_value=FakeResponse()) as mocked_urlopen:
                result = process_waha_test_item(item.pk)

        request_obj = mocked_urlopen.call_args.args[0]
        request_body = json.loads(request_obj.data)
        self.assertEqual(request_obj.full_url, "http://waha-test:3000/api/sendText")
        self.assertEqual(request_body["chatId"], "996700000099@c.us")
        self.assertNotIn("996700000001", request_body["chatId"])
        self.assertIn("WAHA Student", request_body["text"])
        self.assertEqual(result["status"], WahaTestReportBatchItem.STATUS_ACCEPTED)
        self.assertEqual(batch.items.get().status, WahaTestReportBatchItem.STATUS_ACCEPTED)

    def test_unknown_delivery_result_is_not_requeued(self):
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            batch = self.make_batch()
            item = claim_next_waha_test_item()
            with patch("tabel_app.waha_reports.request.urlopen", side_effect=URLError("timeout")):
                result = process_waha_test_item(item.pk)
            repeated = self.make_batch()

        self.assertEqual(result["status"], WahaTestReportBatchItem.STATUS_UNKNOWN)
        self.assertEqual(repeated.items.get().status, WahaTestReportBatchItem.STATUS_SKIPPED)

    def test_stale_processing_item_becomes_unknown_instead_of_being_retried(self):
        with patch.dict(os.environ, WAHA_TEST_ENV, clear=False):
            batch = self.make_batch()
            item = claim_next_waha_test_item()
            item.started_at = timezone.now() - timedelta(minutes=6)
            item.save(update_fields=["started_at"])

            next_item = claim_next_waha_test_item()

        item.refresh_from_db()
        batch.refresh_from_db()
        self.assertIsNone(next_item)
        self.assertEqual(item.status, WahaTestReportBatchItem.STATUS_UNKNOWN)
        self.assertEqual(batch.status, batch.STATUS_COMPLETED)
