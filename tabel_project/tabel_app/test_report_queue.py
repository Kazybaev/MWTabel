from datetime import date
from io import StringIO
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

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
from .report_queue import (
    claim_next_report_item,
    enqueue_monthly_report_batch,
    report_dedupe_key,
    serialize_report_batch,
)
from .scheduler import start_report_scheduler


class MonthlyReportQueueTests(TestCase):
    def setUp(self):
        worker_gate = patch.dict(os.environ, {"REPORT_LEGACY_QUEUE_REVIEWED": "true"})
        worker_gate.start()
        self.addCleanup(worker_gate.stop)
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
        batch = enqueue_monthly_report_batch(
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
        self.assertEqual(data["cancelled"], 0)
        self.assertEqual(data["remaining"], 1)

    def test_repeat_enqueue_keeps_only_one_active_report(self):
        first = self.enqueue()
        second = self.enqueue()

        self.assertEqual(first.items.get().status, MonthlyStudentReportBatchItem.STATUS_QUEUED)
        self.assertEqual(second.items.get().status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertEqual(
            MonthlyStudentReportBatchItem.objects.filter(
                status__in=MonthlyStudentReportBatchItem.ACTIVE_STATUSES,
            ).count(),
            1,
        )

    def test_same_recipient_is_allowed_for_a_different_report_context(self):
        sibling_user = User.objects.create_user(
            username="queue-sibling", full_name="Queue Sibling", role=User.ROLE_STUDENT
        )
        sibling = StudentProfile.objects.create(
            user=sibling_user,
            parent_phone=self.student.parent_phone,
            group=self.group,
        )
        batch = enqueue_monthly_report_batch(
            created_by=self.admin,
            month=date(2026, 8, 1),
            organization_type="academy",
            student_ids=[self.student.pk, sibling.pk],
        )

        self.assertEqual(batch.items.filter(status=MonthlyStudentReportBatchItem.STATUS_QUEUED).count(), 2)
        self.assertEqual(batch.items.exclude(dedupe_key__isnull=True).count(), 2)

    def test_dedupe_identity_accounts_for_period_recipient_and_context(self):
        base = report_dedupe_key(
            student=self.student,
            month=date(2026, 8, 1),
            organization_type="academy",
        )
        next_month = report_dedupe_key(
            student=self.student,
            month=date(2026, 9, 1),
            organization_type="academy",
        )
        self.student.parent_phone = "+996700000777"
        other_recipient = report_dedupe_key(
            student=self.student,
            month=date(2026, 8, 1),
            organization_type="academy",
        )
        sibling_user = User.objects.create_user(username="dedupe-sibling", role=User.ROLE_STUDENT)
        sibling = StudentProfile.objects.create(
            user=sibling_user,
            parent_phone="+996700000001",
            group=self.group,
        )
        other_context = report_dedupe_key(
            student=sibling,
            month=date(2026, 8, 1),
            organization_type="academy",
        )

        self.assertEqual(len({base, next_month, other_recipient, other_context}), 4)

    def test_cancel_command_is_dry_run_by_default_and_preserves_history(self):
        batch = self.enqueue()
        output = StringIO()

        call_command("cancel_report_batches", batch_ids=[batch.pk], stdout=output)
        batch.refresh_from_db()
        self.assertEqual(batch.status, batch.STATUS_QUEUED)
        self.assertEqual(batch.items.get().status, MonthlyStudentReportBatchItem.STATUS_QUEUED)
        self.assertIn('"mode": "dry-run"', output.getvalue())

        call_command("cancel_report_batches", batch_ids=[batch.pk], apply=True)
        batch.refresh_from_db()
        item = batch.items.get()
        self.assertEqual(batch.status, batch.STATUS_CANCELLED)
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_CANCELLED)
        self.assertIsNotNone(item.finished_at)
        self.assertIsNone(claim_next_report_item(batch_ids=[batch.pk]))

    def test_cancel_command_preserves_a_claimed_item(self):
        batch = self.enqueue()
        claim_next_report_item(batch_ids=[batch.pk])

        call_command("cancel_report_batches", batch_ids=[batch.pk], apply=True)

        batch.refresh_from_db()
        self.assertEqual(batch.status, batch.STATUS_PROCESSING)
        self.assertEqual(batch.items.get().status, MonthlyStudentReportBatchItem.STATUS_PROCESSING)

    def test_partial_batch_cancellation_preserves_history_and_started_items(self):
        extra_students = []
        for suffix in (2, 3):
            user = User.objects.create_user(
                username=f"cancel-student-{suffix}", role=User.ROLE_STUDENT
            )
            extra_students.append(StudentProfile.objects.create(
                user=user,
                parent_phone=f"+99670000000{suffix}",
                group=self.group,
            ))
        batch = enqueue_monthly_report_batch(
            created_by=self.admin,
            month=date(2026, 8, 1),
            organization_type="academy",
            student_ids=[self.student.pk, *(student.pk for student in extra_students)],
        )
        completed_item = batch.items.order_by("id").first()
        dispatch = MonthlyStudentReportDispatch.objects.create(
            student=completed_item.student,
            month=completed_item.month,
            trigger_date=date(2026, 8, 31),
            status=MonthlyStudentReportDispatch.STATUS_ACCEPTED,
            attempts=1,
        )
        attempt = MonthlyStudentReportAttempt.objects.create(
            dispatch=dispatch,
            attempt_number=1,
            status=MonthlyStudentReportDispatch.STATUS_ACCEPTED,
        )
        completed_item.status = MonthlyStudentReportBatchItem.STATUS_ACCEPTED
        completed_item.dispatch = dispatch
        completed_item.attempt = attempt
        completed_item.save(update_fields=["status", "dispatch", "attempt", "updated_at"])
        claimed = claim_next_report_item(batch_ids=[batch.pk])
        history_counts = (
            MonthlyStudentReportDispatch.objects.count(),
            MonthlyStudentReportAttempt.objects.count(),
        )

        call_command("cancel_report_batches", batch_ids=[batch.pk], apply=True)

        completed_item.refresh_from_db()
        claimed.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(completed_item.status, MonthlyStudentReportBatchItem.STATUS_ACCEPTED)
        self.assertEqual(claimed.status, MonthlyStudentReportBatchItem.STATUS_PROCESSING)
        self.assertEqual(
            batch.items.filter(status=MonthlyStudentReportBatchItem.STATUS_CANCELLED).count(),
            1,
        )
        self.assertEqual(
            history_counts,
            (
                MonthlyStudentReportDispatch.objects.count(),
                MonthlyStudentReportAttempt.objects.count(),
            ),
        )
        self.assertEqual(batch.status, batch.STATUS_PROCESSING)

    def test_continuous_worker_does_not_claim_legacy_review_items(self):
        batch = self.enqueue()
        batch.items.update(requires_operator_review=True)

        call_command("process_report_queue", once=True)

        self.assertEqual(batch.items.get().status, MonthlyStudentReportBatchItem.STATUS_QUEUED)

    def test_continuous_worker_is_blocked_before_legacy_review(self):
        with patch.dict(os.environ, {"REPORT_LEGACY_QUEUE_REVIEWED": "false"}):
            with self.assertRaises(CommandError):
                call_command("process_report_queue", once=True)

    def test_recovery_worker_rejects_an_unknown_batch_scope(self):
        with self.assertRaises(CommandError):
            call_command("process_report_queue", once=True, recovery_batch_ids="999999")

    @patch("tabel_app.report.send_student_month_report")
    def test_recovery_worker_processes_only_explicit_legacy_batch(self, mocked_send):
        selected = self.enqueue()
        selected.items.update(requires_operator_review=True)
        other = enqueue_monthly_report_batch(
            created_by=self.admin,
            month=date(2026, 9, 1),
            organization_type="academy",
            student_ids=[self.student.pk],
        )
        other.items.update(requires_operator_review=True)
        mocked_send.return_value = {"status": "skipped", "reason": "mocked no-send"}

        call_command(
            "process_report_queue",
            once=True,
            recovery_batch_ids=str(selected.pk),
        )

        selected.items.get().refresh_from_db()
        self.assertEqual(selected.items.get().status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertEqual(other.items.get().status, MonthlyStudentReportBatchItem.STATUS_QUEUED)
        mocked_send.assert_called_once()

    @patch("tabel_app.report.send_student_month_report")
    def test_saving_a_grade_does_not_create_or_send_a_report(self, mocked_send):
        next_lesson = Lesson.objects.create(group=self.group, lesson_date=date(2026, 9, 1))
        LessonRecord.objects.create(student=self.student, lesson=next_lesson, grade="4")

        mocked_send.assert_not_called()
        self.assertEqual(MonthlyStudentReportBatchItem.objects.count(), 0)

    @patch("tabel_app.scheduler.threading.Thread")
    def test_disabled_scheduler_does_not_start_on_application_call(self, mocked_thread):
        with patch.dict(
            os.environ,
            {"AUTO_MONTHLY_REPORTS": "false", "REPORT_SCHEDULER_RUN_ON_START": "false"},
        ):
            start_report_scheduler()

        mocked_thread.assert_not_called()

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


@skipUnless(connection.vendor == "postgresql", "Concurrent row-lock test requires PostgreSQL.")
class MonthlyReportQueueConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        worker_gate = patch.dict(os.environ, {"REPORT_LEGACY_QUEUE_REVIEWED": "true"})
        worker_gate.start()
        self.addCleanup(worker_gate.stop)
        self.admin = User.objects.create_user(username="concurrent-admin", role=User.ROLE_ADMIN)
        mentor_user = User.objects.create_user(username="concurrent-mentor", role=User.ROLE_MENTOR)
        mentor = MentorProfile.objects.create(user=mentor_user)
        self.group = Group.objects.create(course_name="Concurrent Group", mentor=mentor)
        student_user = User.objects.create_user(username="concurrent-student", role=User.ROLE_STUDENT)
        self.student = StudentProfile.objects.create(
            user=student_user,
            parent_phone="+996700000099",
            group=self.group,
        )

    def _enqueue_in_thread(self):
        close_old_connections()
        try:
            return enqueue_monthly_report_batch(
                created_by=User.objects.get(pk=self.admin.pk),
                month=date(2026, 8, 1),
                organization_type="academy",
                student_ids=[self.student.pk],
            ).pk
        finally:
            close_old_connections()

    def test_concurrent_requests_create_only_one_active_report(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            batch_ids = list(pool.map(lambda _: self._enqueue_in_thread(), range(2)))

        statuses = list(
            MonthlyStudentReportBatchItem.objects.filter(batch_id__in=batch_ids)
            .order_by("batch_id")
            .values_list("status", flat=True)
        )
        self.assertCountEqual(
            statuses,
            [MonthlyStudentReportBatchItem.STATUS_QUEUED, MonthlyStudentReportBatchItem.STATUS_SKIPPED],
        )
        self.assertEqual(
            MonthlyStudentReportBatchItem.objects.filter(
                status__in=MonthlyStudentReportBatchItem.ACTIVE_STATUSES,
            ).count(),
            1,
        )

    def test_continuous_worker_waits_for_and_processes_a_new_manual_batch(self):
        empty_queue_seen = Event()
        real_claim = claim_next_report_item

        def observed_claim(**kwargs):
            item = real_claim(**kwargs)
            if item is None:
                empty_queue_seen.set()
            return item

        def run_worker():
            close_old_connections()
            try:
                call_command("process_report_queue", max_items=1, poll_interval=0.01)
            finally:
                close_old_connections()

        with (
            patch(
                "tabel_app.management.commands.process_report_queue.claim_next_report_item",
                side_effect=observed_claim,
            ),
            patch("tabel_app.report.send_student_month_report") as mocked_send,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            mocked_send.return_value = {"status": "skipped", "reason": "mocked no-send"}
            future = pool.submit(run_worker)
            self.assertTrue(empty_queue_seen.wait(timeout=5))
            client = APIClient()
            client.force_authenticate(user=self.admin)
            response = client.post(
                "/api/reports/send-all/",
                {"month": "2026-08", "student_ids": [self.student.pk]},
                format="json",
            )
            self.assertEqual(response.status_code, 202)
            future.result(timeout=5)

        item = MonthlyStudentReportBatchItem.objects.get(batch_id=response.data["id"])
        self.assertEqual(item.status, MonthlyStudentReportBatchItem.STATUS_SKIPPED)
        self.assertFalse(item.requires_operator_review)
        mocked_send.assert_called_once()

    def test_cancellation_lock_prevents_a_worker_claim(self):
        batch = enqueue_monthly_report_batch(
            created_by=self.admin,
            month=date(2026, 8, 1),
            organization_type="academy",
            student_ids=[self.student.pk],
        )

        def claim_in_other_connection():
            close_old_connections()
            try:
                return claim_next_report_item(batch_ids=[batch.pk])
            finally:
                close_old_connections()

        with transaction.atomic():
            list(
                MonthlyStudentReportBatchItem.objects.select_for_update()
                .filter(batch=batch)
                .values_list("id", flat=True)
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertIsNone(pool.submit(claim_in_other_connection).result(timeout=5))
            call_command("cancel_report_batches", batch_ids=[batch.pk], apply=True)

        self.assertEqual(
            batch.items.get().status,
            MonthlyStudentReportBatchItem.STATUS_CANCELLED,
        )
