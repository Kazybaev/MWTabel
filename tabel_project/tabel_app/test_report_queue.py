from datetime import date
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    MonthlyStudentReportAttempt,
    MonthlyStudentReportBatchItem,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
)
from .report_delivery import record_meta_delivery_callback
from .report_queue import claim_next_report_item, enqueue_monthly_report_batch, serialize_report_batch


class MonthlyReportQueueTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="queue-admin", full_name="Queue Admin", role=User.ROLE_ADMIN)
        mentor_user = User.objects.create_user(username="queue-mentor", full_name="Queue Mentor", role=User.ROLE_MENTOR)
        mentor = MentorProfile.objects.create(user=mentor_user)
        self.group = Group.objects.create(course_name="Queue Group", mentor=mentor, study_days=Group.MON_WED_SAT)
        student_user = User.objects.create_user(username="queue-student", full_name="Queue Student", role=User.ROLE_STUDENT)
        self.student = StudentProfile.objects.create(
            user=student_user,
            parent_phone="+996700000001",
            group=self.group,
        )
        lesson = Lesson.objects.create(group=self.group, lesson_date=date(2026, 8, 31))
        LessonRecord.objects.create(student=self.student, lesson=lesson, grade="5")

    def enqueue(self, **kwargs):
        return enqueue_monthly_report_batch(
            created_by=self.admin,
            month=date(2026, 8, 1),
            organization_type="academy",
            student_ids=[self.student.pk],
            **kwargs,
        )

    def test_database_claim_prevents_double_processing(self):
        self.enqueue()
        first = claim_next_report_item()
        second = claim_next_report_item()
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    @patch("tabel_app.report.run_dify_workflow")
    def test_worker_max_items_processes_exactly_one_item(self, mocked_dify):
        second_user = User.objects.create_user(
            username="queue-student-2", full_name="Queue Student 2", role=User.ROLE_STUDENT
        )
        second_student = StudentProfile.objects.create(
            user=second_user,
            parent_phone="+996700000002",
            group=self.group,
        )
        LessonRecord.objects.create(
            student=second_student,
            lesson=Lesson.objects.get(group=self.group, lesson_date=date(2026, 8, 31)),
            grade="5",
        )
        enqueue_monthly_report_batch(
            created_by=self.admin,
            month=date(2026, 8, 1),
            organization_type="academy",
            student_ids=[self.student.pk, second_student.pk],
        )
        mocked_dify.return_value = {"workflow_run_id": "run-no-callback", "data": {"status": "succeeded"}}

        call_command("process_report_queue", max_items=1)

        self.assertEqual(mocked_dify.call_count, 1)
        self.assertEqual(MonthlyStudentReportAttempt.objects.count(), 1)
        self.assertEqual(
            MonthlyStudentReportBatchItem.objects.filter(status=MonthlyStudentReportBatchItem.STATUS_QUEUED).count(),
            1,
        )

    @patch("tabel_app.report.run_dify_workflow")
    def test_worker_updates_the_correlated_attempt_to_accepted(self, mocked_dify):
        batch = self.enqueue()

        def accepted_callback(inputs, user_key):
            correlation = inputs["report"]["correlation"]
            self.assertEqual(correlation["batch_item_id"], batch.items.get().pk)
            record_meta_delivery_callback(
                delivery={"report": inputs["report"], "channel": "meta_whatsapp"},
                meta_status_code=200,
                meta_response={
                    "messaging_product": "whatsapp",
                    "messages": [{"id": "wamid.queue-accepted", "message_status": "accepted"}],
                },
            )
            return {"workflow_run_id": "run-queue-accepted", "data": {"status": "succeeded"}}

        mocked_dify.side_effect = accepted_callback
        call_command("process_report_queue", once=True)

        item = batch.items.get()
        item.refresh_from_db()
        item.attempt.refresh_from_db()
        item.dispatch.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_ACCEPTED)
        self.assertEqual(item.attempt.status, MonthlyStudentReportDispatch.STATUS_ACCEPTED)
        self.assertEqual(item.dispatch.status, MonthlyStudentReportDispatch.STATUS_ACCEPTED)
        self.assertEqual(item.attempt.meta_message_id, "wamid.queue-accepted")
        self.assertEqual(batch.status, batch.STATUS_COMPLETED)

    @patch("tabel_app.report.run_dify_workflow")
    def test_existing_success_is_skipped_without_network(self, mocked_dify):
        MonthlyStudentReportDispatch.objects.create(
            student=self.student,
            month=date(2026, 8, 1),
            trigger_date=date(2026, 8, 31),
            status=MonthlyStudentReportDispatch.STATUS_ACCEPTED,
            attempts=1,
        )
        batch = self.enqueue()
        item = batch.items.get()
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertEqual(item.error_message, "Already accepted or delivered.")
        call_command("process_report_queue", once=True)
        mocked_dify.assert_not_called()

    @patch("tabel_app.report.run_dify_workflow")
    def test_failed_retry_requires_explicit_batch_confirmation(self, mocked_dify):
        dispatch = MonthlyStudentReportDispatch.objects.create(
            student=self.student,
            month=date(2026, 8, 1),
            trigger_date=date(2026, 8, 31),
            status=MonthlyStudentReportDispatch.STATUS_FAILED,
            attempts=1,
        )
        MonthlyStudentReportAttempt.objects.create(
            dispatch=dispatch,
            attempt_number=1,
            status=MonthlyStudentReportDispatch.STATUS_FAILED,
        )
        batch = self.enqueue(confirm_retry_failed=False)
        item = batch.items.get()
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertEqual(item.error_message, "Retrying a failed attempt requires explicit confirmation.")
        call_command("process_report_queue", once=True)
        mocked_dify.assert_not_called()

    def test_batch_serialization_exposes_required_progress_counts(self):
        batch = self.enqueue()
        data = serialize_report_batch(batch)
        self.assertEqual(data["queued"], 1)
        self.assertEqual(data["processing"], 0)
        self.assertEqual(data["accepted"], 0)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(data["skipped"], 0)
        self.assertEqual(data["remaining"], 1)

    def test_same_meta_message_id_cannot_update_another_attempt(self):
        report = {
            "student": {"id": self.student.pk},
            "period": {"month": "2026-08"},
            "summary": {},
        }
        dispatch = MonthlyStudentReportDispatch.objects.create(
            student=self.student,
            month=date(2026, 8, 1),
            trigger_date=date(2026, 8, 31),
            status="pending",
            attempts=2,
            payload=report,
        )
        first = MonthlyStudentReportAttempt.objects.create(dispatch=dispatch, attempt_number=1, payload=report)
        second = MonthlyStudentReportAttempt.objects.create(dispatch=dispatch, attempt_number=2, payload=report)
        response = {"messages": [{"id": "wamid.unique", "message_status": "accepted"}]}
        for attempt in (first, second):
            callback_report = {**report, "correlation": {
                "dispatch_id": dispatch.pk,
                "attempt_id": attempt.pk,
                "batch_item_id": None,
            }}
            if attempt == first:
                record_meta_delivery_callback(
                    delivery={"report": callback_report}, meta_status_code=200, meta_response=response
                )
            else:
                with self.assertRaises(ValueError):
                    record_meta_delivery_callback(
                        delivery={"report": callback_report}, meta_status_code=200, meta_response=response
                    )

    def test_duplicate_callback_still_requires_the_exact_batch_item(self):
        batch = self.enqueue(confirm_retry_failed=True)
        item = batch.items.get()
        dispatch = MonthlyStudentReportDispatch.objects.create(
            student=self.student,
            month=date(2026, 8, 1),
            trigger_date=date(2026, 8, 31),
            status="pending",
            attempts=1,
        )
        attempt = MonthlyStudentReportAttempt.objects.create(
            dispatch=dispatch,
            attempt_number=1,
            status="pending",
        )
        item.dispatch = dispatch
        item.attempt = attempt
        item.status = MonthlyStudentReportBatchItem.STATUS_PROCESSING
        item.save(update_fields=["dispatch", "attempt", "status", "updated_at"])
        report = {
            "student": {"id": self.student.pk},
            "period": {"month": "2026-08"},
            "summary": {},
            "correlation": {
                "dispatch_id": dispatch.pk,
                "attempt_id": attempt.pk,
                "batch_item_id": item.pk,
            },
        }
        response = {"messages": [{"id": "wamid.exact-item", "message_status": "accepted"}]}
        record_meta_delivery_callback(
            delivery={"report": report}, meta_status_code=200, meta_response=response
        )
        report["correlation"]["batch_item_id"] = None
        with self.assertRaises(ValueError):
            record_meta_delivery_callback(
                delivery={"report": report}, meta_status_code=200, meta_response=response
            )
