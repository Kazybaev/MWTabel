from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    MonthlyStudentReportBatch,
    MonthlyStudentReportBatchItem,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
)


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
    students = StudentProfile.objects.filter(
        archived_at__isnull=True,
        group__archived_at__isnull=True,
        organization_type=organization_type,
    )
    if college_branch is not None:
        students = students.filter(college_branch=college_branch)
    if group_ids:
        students = students.filter(group_id__in=group_ids)
    if student_ids:
        students = students.filter(pk__in=student_ids)
    student_ids_to_queue = list(students.order_by("group__course_name", "user__full_name").values_list("pk", flat=True))
    existing_dispatches = {
        dispatch.student_id: dispatch
        for dispatch in MonthlyStudentReportDispatch.objects.filter(
            student_id__in=student_ids_to_queue,
            month=month,
        )
    }

    def build_item(student_id: int) -> MonthlyStudentReportBatchItem:
        dispatch = existing_dispatches.get(student_id)
        status = MonthlyStudentReportBatchItem.STATUS_QUEUED
        error_message = ""
        if dispatch and dispatch.status in MonthlyStudentReportDispatch.SUCCESSFUL_STATUSES:
            status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
            error_message = "Already accepted or delivered."
        elif dispatch and dispatch.status == MonthlyStudentReportDispatch.STATUS_FAILED and not confirm_retry_failed:
            status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
            error_message = "Retrying a failed attempt requires explicit confirmation."
        elif dispatch and dispatch.status == MonthlyStudentReportDispatch.STATUS_PENDING and dispatch.attempts:
            status = MonthlyStudentReportBatchItem.STATUS_SKIPPED
            error_message = "Another delivery attempt is pending review."
        return MonthlyStudentReportBatchItem(
            student_id=student_id,
            month=month,
            status=status,
            dispatch=dispatch,
            error_message=error_message,
            finished_at=timezone.now() if status == MonthlyStudentReportBatchItem.STATUS_SKIPPED else None,
        )

    with transaction.atomic():
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
        items = [build_item(student_id) for student_id in student_ids_to_queue]
        for item in items:
            item.batch = batch
        MonthlyStudentReportBatchItem.objects.bulk_create(items)
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
            batch.status = MonthlyStudentReportBatch.STATUS_COMPLETED
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


def claim_next_report_item(*, lease_seconds: int = 900) -> MonthlyStudentReportBatchItem | None:
    stale_before = timezone.now() - timedelta(seconds=lease_seconds)
    with transaction.atomic():
        item = (
            MonthlyStudentReportBatchItem.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=MonthlyStudentReportBatchItem.STATUS_QUEUED)
                | Q(status=MonthlyStudentReportBatchItem.STATUS_PROCESSING, claimed_at__lt=stale_before)
            )
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
