from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    MonthlyStudentReportBatch,
    MonthlyStudentReportBatchItem,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
    WahaParentReportBatchItem,
    WahaTestReportBatchItem,
)


def report_dedupe_key(*, student: StudentProfile, month: date, organization_type: str) -> str:
    """Identify one active report without retaining a readable recipient in the queue."""
    recipient = re.sub(r"\D", "", str(student.parent_phone or ""))
    context = {
        "student_id": student.pk,
        "organization_type": organization_type,
        "college_branch": student.college_branch if organization_type == "college" else None,
    }
    material = json.dumps(
        {"month": month.isoformat(), "recipient": recipient, "context": context},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def enqueue_monthly_report_batch(
    *,
    created_by: User,
    month: date,
    organization_type: str,
    college_branch: str | None = None,
    group_ids: list[int] | None = None,
    student_ids: list[int] | None = None,
    confirm_retry_failed: bool = False,
) -> MonthlyStudentReportBatch:
    with transaction.atomic():
        students = StudentProfile.objects.select_for_update().filter(
            archived_at__isnull=True,
            group__archived_at__isnull=True,
            organization_type=organization_type,
        ).select_related("group")
        if college_branch is not None:
            students = students.filter(college_branch=college_branch)
        if group_ids:
            students = students.filter(group_id__in=group_ids)
        if student_ids:
            students = students.filter(pk__in=student_ids)
        students_to_queue = list(students.order_by("group__course_name", "user__full_name", "pk"))
        student_ids_to_queue = [student.pk for student in students_to_queue]
        existing_dispatches = {
            dispatch.student_id: dispatch
            for dispatch in MonthlyStudentReportDispatch.objects.filter(
                student_id__in=student_ids_to_queue,
                month=month,
            )
        }
        active_items = {
            item.student_id: item.batch_id
            for item in MonthlyStudentReportBatchItem.objects.filter(
                student_id__in=student_ids_to_queue,
                month=month,
                status__in=MonthlyStudentReportBatchItem.ACTIVE_STATUSES,
            ).only("student_id", "batch_id")
        }
        active_parent_items = {
            item.student_id
            for item in WahaParentReportBatchItem.objects.filter(
                student_id__in=student_ids_to_queue,
                month=month,
                status__in=WahaParentReportBatchItem.ACTIVE_STATUSES
                + (
                    WahaParentReportBatchItem.STATUS_ACCEPTED,
                    WahaParentReportBatchItem.STATUS_UNKNOWN,
                    WahaParentReportBatchItem.STATUS_FAILED,
                ),
            ).only("student_id")
        }
        waha_test_items = {
            item.student_id
            for item in WahaTestReportBatchItem.objects.filter(
                student_id__in=student_ids_to_queue,
                month=month,
                status__in=(
                    WahaTestReportBatchItem.STATUS_QUEUED,
                    WahaTestReportBatchItem.STATUS_PROCESSING,
                    WahaTestReportBatchItem.STATUS_ACCEPTED,
                    WahaTestReportBatchItem.STATUS_UNKNOWN,
                ),
            ).only("student_id")
        }
        batch = MonthlyStudentReportBatch.objects.create(
            month=month,
            organization_type=organization_type,
            created_by=created_by,
            confirm_retry_failed=confirm_retry_failed,
            requested_filters={
                "college_branch": college_branch,
                "group_ids": group_ids or [],
                "student_ids": student_ids or [],
            },
        )
        items = []
        for student in students_to_queue:
            dispatch = existing_dispatches.get(student.pk)
            item_status = MonthlyStudentReportBatchItem.STATUS_QUEUED
            error_message = ""
            dedupe_key = report_dedupe_key(student=student, month=month, organization_type=organization_type)
            if dispatch and dispatch.status in MonthlyStudentReportDispatch.SUCCESSFUL_STATUSES:
                item_status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
                error_message = "Already accepted or delivered."
            elif dispatch and dispatch.status == MonthlyStudentReportDispatch.STATUS_FAILED and not confirm_retry_failed:
                item_status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
                error_message = "Retrying a failed attempt requires explicit confirmation."
            elif dispatch and dispatch.status == MonthlyStudentReportDispatch.STATUS_PENDING and dispatch.attempts:
                item_status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
                error_message = "Another delivery attempt is pending review."
            elif student.pk in active_items:
                item_status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
                error_message = f"Already queued in active batch {active_items[student.pk]}."
            elif student.pk in active_parent_items:
                item_status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
                error_message = "A WAHA parent report is prepared, active, or requires manual review."
            elif student.pk in waha_test_items:
                item_status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
                error_message = "A WAHA test attempt exists for this student and month; review it before using Dify/Meta."

            if item_status != MonthlyStudentReportBatchItem.STATUS_QUEUED:
                dedupe_key = None
            item = MonthlyStudentReportBatchItem(
                batch=batch,
                student=student,
                month=month,
                status=item_status,
                dispatch=dispatch,
                dedupe_key=dedupe_key,
                error_message=error_message,
                finished_at=timezone.now() if item_status == MonthlyStudentReportBatchItem.STATUS_SKIPPED else None,
            )
            try:
                with transaction.atomic():
                    item.save(force_insert=True)
            except IntegrityError:
                item.pk = None
                item.dedupe_key = None
                item.status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
                item.error_message = "An identical report was queued concurrently."
                item.finished_at = timezone.now()
                item.save(force_insert=True)
            items.append(item)
        if not items or all(item.status in MonthlyStudentReportBatchItem.TERMINAL_STATUSES for item in items):
            batch.status = MonthlyStudentReportBatch.STATUS_COMPLETED
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "completed_at", "updated_at"])
    return batch


def refresh_batch_status(batch_id: int) -> None:
    with transaction.atomic():
        batch = MonthlyStudentReportBatch.objects.select_for_update().get(pk=batch_id)
        statuses = set(batch.items.values_list("status", flat=True))
        now = timezone.now()
        if not statuses or statuses.issubset(set(MonthlyStudentReportBatchItem.TERMINAL_STATUSES)):
            batch.status = (
                MonthlyStudentReportBatch.STATUS_CANCELLED
                if MonthlyStudentReportBatchItem.STATUS_CANCELLED in statuses
                else MonthlyStudentReportBatch.STATUS_COMPLETED
            )
            batch.completed_at = batch.completed_at or now
        elif statuses == {MonthlyStudentReportBatchItem.STATUS_QUEUED}:
            batch.status = MonthlyStudentReportBatch.STATUS_QUEUED
        else:
            batch.status = MonthlyStudentReportBatch.STATUS_PROCESSING
            batch.started_at = batch.started_at or now
            batch.completed_at = None
        batch.save(update_fields=["status", "started_at", "completed_at", "updated_at"])


def serialize_report_batch(batch: MonthlyStudentReportBatch) -> dict[str, Any]:
    counts = batch.items.aggregate(
        total=Count("id"),
        queued=Count("id", filter=Q(status=MonthlyStudentReportBatchItem.STATUS_QUEUED)),
        processing=Count(
            "id",
            filter=Q(status__in=(
                MonthlyStudentReportBatchItem.STATUS_PROCESSING,
                MonthlyStudentReportBatchItem.STATUS_PENDING,
            )),
        ),
        accepted=Count("id", filter=Q(status=MonthlyStudentReportBatchItem.STATUS_ACCEPTED)),
        delivered=Count("id", filter=Q(status=MonthlyStudentReportBatchItem.STATUS_DELIVERED)),
        failed=Count("id", filter=Q(status=MonthlyStudentReportBatchItem.STATUS_FAILED)),
        skipped=Count("id", filter=Q(status=MonthlyStudentReportBatchItem.STATUS_SKIPPED)),
        cancelled=Count("id", filter=Q(status=MonthlyStudentReportBatchItem.STATUS_CANCELLED)),
    )
    counts["remaining"] = counts["queued"] + counts["processing"]
    return {
        "id": batch.pk,
        "month": batch.month.strftime("%Y-%m"),
        "status": batch.status,
        "confirm_retry_failed": batch.confirm_retry_failed,
        **counts,
        "created_at": batch.created_at,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "status_url": f"/api/reports/batches/{batch.pk}/",
    }


def claim_next_report_item(
    *,
    batch_ids: list[int] | None = None,
    include_operator_review: bool = False,
    lease_seconds: int = 900,
) -> MonthlyStudentReportBatchItem | None:
    stale_before = timezone.now() - timedelta(seconds=lease_seconds)
    with transaction.atomic():
        candidates = MonthlyStudentReportBatchItem.objects.select_for_update(skip_locked=True).filter(
            Q(status=MonthlyStudentReportBatchItem.STATUS_QUEUED)
            | Q(status=MonthlyStudentReportBatchItem.STATUS_PROCESSING, claimed_at__lt=stale_before)
        )
        if batch_ids is not None:
            candidates = candidates.filter(batch_id__in=batch_ids)
        if not include_operator_review:
            candidates = candidates.filter(requires_operator_review=False)
        item = (
            candidates
            .select_related("batch", "student__user", "student__group__mentor__user")
            .order_by("created_at", "id")
            .first()
        )
        if item is None:
            return None
        token = uuid.uuid4()
        item.status = MonthlyStudentReportBatchItem.STATUS_PROCESSING
        item.worker_token = token
        item.claimed_at = timezone.now()
        item.error_message = ""
        item.save(update_fields=["status", "worker_token", "claimed_at", "error_message", "updated_at"])
        batch = item.batch
        batch.status = MonthlyStudentReportBatch.STATUS_PROCESSING
        batch.started_at = batch.started_at or timezone.now()
        batch.completed_at = None
        batch.save(update_fields=["status", "started_at", "completed_at", "updated_at"])
        item.worker_token = token
        return item


def _finish_item(item: MonthlyStudentReportBatchItem, status: str, error_message: str = "") -> None:
    item.status = status
    item.error_message = error_message
    item.finished_at = timezone.now() if status in MonthlyStudentReportBatchItem.TERMINAL_STATUSES else None
    item.worker_token = None
    item.save(update_fields=["status", "error_message", "finished_at", "worker_token", "updated_at"])
    refresh_batch_status(item.batch_id)


def process_claimed_report_item(item_id: int, worker_token: uuid.UUID) -> dict[str, Any]:
    from .report import send_student_month_report

    item = MonthlyStudentReportBatchItem.objects.select_related(
        "batch", "student__user", "student__group__mentor__user", "attempt", "dispatch"
    ).get(pk=item_id)
    if item.status != MonthlyStudentReportBatchItem.STATUS_PROCESSING or item.worker_token != worker_token:
        return {"status": "skipped", "reason": "claim_lost", "item_id": item.pk}

    if item.attempt_id:
        if item.attempt.status in MonthlyStudentReportDispatch.SUCCESSFUL_STATUSES:
            mapped = (
                MonthlyStudentReportBatchItem.STATUS_DELIVERED
                if item.attempt.status == MonthlyStudentReportDispatch.STATUS_DELIVERED
                else MonthlyStudentReportBatchItem.STATUS_ACCEPTED
            )
            _finish_item(item, mapped)
            return {"status": mapped, "reason": "already_completed", "item_id": item.pk}
        _finish_item(
            item,
            MonthlyStudentReportBatchItem.STATUS_FAILED,
            "Worker stopped after a delivery attempt started; manual review is required before retry.",
        )
        return {"status": "failed", "reason": "interrupted_attempt_requires_review", "item_id": item.pk}

    existing = MonthlyStudentReportDispatch.objects.filter(student=item.student, month=item.month).first()
    if existing and existing.status in MonthlyStudentReportDispatch.SUCCESSFUL_STATUSES:
        item.dispatch = existing
        item.save(update_fields=["dispatch", "updated_at"])
        _finish_item(item, MonthlyStudentReportBatchItem.STATUS_SKIPPED, "Already accepted or delivered.")
        return {"status": "skipped", "reason": "already_sent", "item_id": item.pk}
    if existing and existing.status == MonthlyStudentReportDispatch.STATUS_FAILED and not item.batch.confirm_retry_failed:
        item.dispatch = existing
        item.save(update_fields=["dispatch", "updated_at"])
        _finish_item(item, MonthlyStudentReportBatchItem.STATUS_SKIPPED, "Retrying a failed attempt requires explicit confirmation.")
        return {"status": "skipped", "reason": "failed_retry_not_confirmed", "item_id": item.pk}
    if existing and existing.status == MonthlyStudentReportDispatch.STATUS_PENDING and existing.attempts:
        item.dispatch = existing
        item.save(update_fields=["dispatch", "updated_at"])
        _finish_item(item, MonthlyStudentReportBatchItem.STATUS_SKIPPED, "Another delivery attempt is pending review.")
        return {"status": "skipped", "reason": "send_already_in_progress", "item_id": item.pk}

    result = send_student_month_report(
        item.student,
        run_date=timezone.localdate(),
        month_start=item.month,
        force=item.batch.confirm_retry_failed,
        bypass_schedule=True,
        resend_succeeded=False,
        batch_item=item,
        retry_failed_confirmed=item.batch.confirm_retry_failed,
    )
    item.refresh_from_db()
    if item.status in (MonthlyStudentReportBatchItem.STATUS_ACCEPTED, MonthlyStudentReportBatchItem.STATUS_DELIVERED):
        _finish_item(item, item.status)
    elif result.get("status") == "failed":
        _finish_item(item, MonthlyStudentReportBatchItem.STATUS_FAILED, str(result.get("reason") or "Delivery failed."))
    elif result.get("status") == "skipped":
        _finish_item(item, MonthlyStudentReportBatchItem.STATUS_SKIPPED, str(result.get("reason") or "Skipped."))
    else:
        _finish_item(item, MonthlyStudentReportBatchItem.STATUS_PENDING)
    return {**result, "item_id": item.pk}


def inspect_report_batch_cancellation(batch_ids: list[int], *, lock: bool = False) -> dict[str, Any]:
    requested_ids = sorted(set(batch_ids))
    queryset = MonthlyStudentReportBatch.objects.filter(pk__in=requested_ids).order_by("pk")
    if lock:
        queryset = queryset.select_for_update()
    batches = list(queryset)
    found_ids = {batch.pk for batch in batches}
    missing_ids = [batch_id for batch_id in requested_ids if batch_id not in found_ids]
    summaries = []
    for batch in batches:
        counts = batch.items.aggregate(
            total=Count("id"),
            queued=Count("id", filter=Q(status=MonthlyStudentReportBatchItem.STATUS_QUEUED)),
            processing=Count(
                "id",
                filter=Q(status__in=(
                    MonthlyStudentReportBatchItem.STATUS_PROCESSING,
                    MonthlyStudentReportBatchItem.STATUS_PENDING,
                )),
            ),
            terminal=Count("id", filter=Q(status__in=MonthlyStudentReportBatchItem.TERMINAL_STATUSES)),
        )
        summaries.append({
            "id": batch.pk,
            "month": batch.month.strftime("%Y-%m"),
            "organization_type": batch.organization_type,
            "status": batch.status,
            **counts,
            "will_cancel": counts["queued"],
            "will_preserve": counts["processing"] + counts["terminal"],
        })
    return {"batch_ids": requested_ids, "missing_ids": missing_ids, "batches": summaries}


def cancel_report_batches(batch_ids: list[int]) -> dict[str, Any]:
    with transaction.atomic():
        # Match the worker's item-then-batch lock order so cancellation cannot
        # race a claim into a send or introduce a lock-order deadlock.
        list(
            MonthlyStudentReportBatchItem.objects.select_for_update()
            .filter(batch_id__in=batch_ids)
            .order_by("batch_id", "id")
            .values_list("id", flat=True)
        )
        inspection = inspect_report_batch_cancellation(batch_ids, lock=True)
        if inspection["missing_ids"]:
            raise ValueError(f"Unknown batch IDs: {inspection['missing_ids']}")
        now = timezone.now()
        for summary in inspection["batches"]:
            batch = MonthlyStudentReportBatch.objects.get(pk=summary["id"])
            cancelled_now = batch.items.filter(status=MonthlyStudentReportBatchItem.STATUS_QUEUED).update(
                status=MonthlyStudentReportBatchItem.STATUS_CANCELLED,
                finished_at=now,
                worker_token=None,
                error_message="Cancelled by an explicit operator action before processing.",
                updated_at=now,
            )
            summary["cancelled_now"] = cancelled_now
            refresh_batch_status(batch.pk)
        inspection["applied"] = True
        return inspection
