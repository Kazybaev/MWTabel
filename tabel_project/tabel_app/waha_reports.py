from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import date, timedelta
from typing import Any
from urllib import error, request

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    StudentProfile,
    User,
    WahaTestReportBatch,
    WahaTestReportBatchItem,
)
from .report import (
    build_student_month_report,
    get_group_last_lesson_date,
    normalize_month_start,
)
from .report_delivery import build_report_message_text


logger = logging.getLogger("tabel_app.waha_test_reports")
MAX_WAHA_TEST_BATCH_SIZE = 10


class WahaTestConfigurationError(Exception):
    pass


def _is_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_test_recipient(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"\+?[1-9]\d{7,14}", normalized):
        raise WahaTestConfigurationError("WAHA_TEST_RECIPIENT must be an international phone number.")
    return f"+{normalized.lstrip('+')}"


def get_waha_test_configuration() -> dict[str, Any]:
    enabled = _is_enabled("WAHA_TEST_MODE_ENABLED")
    worker_enabled = _is_enabled("WAHA_WORKER_ENABLED")
    recipient = os.getenv("WAHA_TEST_RECIPIENT", "").strip()
    recipient_valid = False
    masked_recipient = ""
    if recipient:
        try:
            normalized = _normalize_test_recipient(recipient)
        except WahaTestConfigurationError:
            pass
        else:
            digits = re.sub(r"\D", "", normalized)
            masked_recipient = f"***{digits[-4:]}"
            recipient_valid = True
    ready = (
        enabled
        and worker_enabled
        and recipient_valid
        and _is_enabled("WAHA_SERVER_API_KEY_CONFIGURED")
        and (
            bool(os.getenv("WAHA_CLIENT_API_KEY", "").strip())
            or _is_enabled("WAHA_CLIENT_API_KEY_CONFIGURED")
        )
        and bool(os.getenv("WAHA_API_URL", "http://waha:3000").strip())
    )
    return {
        "enabled": enabled,
        "worker_enabled": worker_enabled,
        "ready": ready,
        "recipient_masked": masked_recipient,
        "max_batch_size": MAX_WAHA_TEST_BATCH_SIZE,
    }


def _waha_test_recipient() -> str:
    if not _is_enabled("WAHA_TEST_MODE_ENABLED"):
        raise WahaTestConfigurationError("WAHA test mode is disabled.")
    recipient = os.getenv("WAHA_TEST_RECIPIENT", "").strip()
    if not recipient:
        raise WahaTestConfigurationError("WAHA_TEST_RECIPIENT is not configured.")
    return _normalize_test_recipient(recipient)


def _dedupe_key(student: StudentProfile, month: date, recipient: str) -> str:
    material = json.dumps(
        {
            "student_id": student.pk,
            "month": month.isoformat(),
            "organization_type": student.organization_type,
            "college_branch": student.college_branch if student.organization_type == "college" else None,
            "recipient": re.sub(r"\D", "", recipient),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def serialize_waha_test_batch(batch: WahaTestReportBatch) -> dict[str, Any]:
    counts = batch.items.aggregate(
        total=Count("id"),
        queued=Count("id", filter=Q(status=WahaTestReportBatchItem.STATUS_QUEUED)),
        processing=Count("id", filter=Q(status=WahaTestReportBatchItem.STATUS_PROCESSING)),
        accepted=Count("id", filter=Q(status=WahaTestReportBatchItem.STATUS_ACCEPTED)),
        failed=Count("id", filter=Q(status=WahaTestReportBatchItem.STATUS_FAILED)),
        unknown=Count("id", filter=Q(status=WahaTestReportBatchItem.STATUS_UNKNOWN)),
        skipped=Count("id", filter=Q(status=WahaTestReportBatchItem.STATUS_SKIPPED)),
    )
    counts["remaining"] = counts["queued"] + counts["processing"]
    return {
        "id": batch.pk,
        "month": batch.month.strftime("%Y-%m"),
        "status": batch.status,
        "status_url": f"/api/reports/waha-test/batches/{batch.pk}/",
        **counts,
        "items": [
            {
                "id": item.pk,
                "student_id": item.student_id,
                "student_name": item.student.user.full_name,
                "status": item.status,
                "error_message": item.error_message,
                "recipient_masked": _mask_phone(str(item.recipient_phone)),
                "created_at": item.created_at,
                "finished_at": item.finished_at,
            }
            for item in batch.items.select_related("student__user").order_by("id")
        ],
    }


def _mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"***{digits[-4:]}" if digits else ""


def enqueue_waha_test_batch(
    *,
    created_by: User,
    students: list[StudentProfile],
    month: date,
    organization_type: str,
) -> WahaTestReportBatch:
    if not students:
        raise ValueError("Select at least one student.")
    if len(students) > MAX_WAHA_TEST_BATCH_SIZE:
        raise ValueError(f"Test batches are limited to {MAX_WAHA_TEST_BATCH_SIZE} students.")

    recipient = _waha_test_recipient()
    month_start = normalize_month_start(month)
    with transaction.atomic():
        batch = WahaTestReportBatch.objects.create(
            month=month_start,
            organization_type=organization_type,
            created_by=created_by,
        )
        for student in students:
            payload = build_student_month_report(student, month_start=month_start)
            skip_reason = ""
            if payload.get("status") == "skipped":
                skip_reason = "Student or group is archived."
            else:
                trigger_date = get_group_last_lesson_date(student.group, month_start)
                if trigger_date is None:
                    skip_reason = "No lessons exist in the student's group for this report month."
                elif timezone.localdate() != trigger_date:
                    skip_reason = (
                        "Reports can only be sent on the group's last lesson date "
                        f"({trigger_date.isoformat()})."
                    )
                elif not payload.get("lessons") or not payload.get("summary", {}).get("marked_lessons_count"):
                    skip_reason = "No marked lesson records exist for this report month."

            if skip_reason:
                item = WahaTestReportBatchItem(
                    batch=batch,
                    student=student,
                    month=month_start,
                    recipient_phone=recipient,
                    report_payload=payload,
                    message_text="",
                    status=WahaTestReportBatchItem.STATUS_SKIPPED,
                    error_message=skip_reason,
                    finished_at=timezone.now(),
                )
                item.save()
                continue

            message_text = build_report_message_text(payload)
            payload = dict(payload)
            payload["student"] = dict(payload["student"])
            payload["student"].pop("parent_phone", None)
            key = _dedupe_key(student, month_start, recipient)
            previous = WahaTestReportBatchItem.objects.filter(
                student=student,
                month=month_start,
                recipient_phone=recipient,
                status__in=(
                    WahaTestReportBatchItem.STATUS_ACCEPTED,
                    WahaTestReportBatchItem.STATUS_UNKNOWN,
                    WahaTestReportBatchItem.STATUS_QUEUED,
                    WahaTestReportBatchItem.STATUS_PROCESSING,
                ),
            ).order_by("-created_at").first()
            if previous:
                status_value = WahaTestReportBatchItem.STATUS_SKIPPED
                error_message = (
                    "Previous delivery result is unknown; manual review is required."
                    if previous.status == WahaTestReportBatchItem.STATUS_UNKNOWN
                    else "A report for this student and month was already accepted or is active."
                )
                key = None
            else:
                status_value = WahaTestReportBatchItem.STATUS_QUEUED
                error_message = ""

            item = WahaTestReportBatchItem(
                batch=batch,
                student=student,
                month=month_start,
                recipient_phone=recipient,
                report_payload=payload,
                message_text=message_text,
                status=status_value,
                dedupe_key=key,
                error_message=error_message,
                finished_at=timezone.now() if status_value == WahaTestReportBatchItem.STATUS_SKIPPED else None,
            )
            try:
                with transaction.atomic():
                    item.save(force_insert=True)
            except IntegrityError:
                item.pk = None
                item.dedupe_key = None
                item.status = WahaTestReportBatchItem.STATUS_SKIPPED
                item.error_message = "An identical test report was queued concurrently."
                item.finished_at = timezone.now()
                item.save(force_insert=True)

        _refresh_waha_test_batch(batch.pk)
    return batch


def _refresh_waha_test_batch(batch_id: int) -> None:
    with transaction.atomic():
        batch = WahaTestReportBatch.objects.select_for_update().get(pk=batch_id)
        statuses = set(batch.items.values_list("status", flat=True))
        now = timezone.now()
        if not statuses or statuses.issubset(set(WahaTestReportBatchItem.TERMINAL_STATUSES)):
            batch.status = WahaTestReportBatch.STATUS_COMPLETED
            batch.completed_at = batch.completed_at or now
        elif WahaTestReportBatchItem.STATUS_PROCESSING in statuses:
            batch.status = WahaTestReportBatch.STATUS_PROCESSING
            batch.started_at = batch.started_at or now
        batch.save(update_fields=["status", "started_at", "completed_at", "updated_at"])


def claim_next_waha_test_item() -> WahaTestReportBatchItem | None:
    stale_seconds = max(60, int(os.getenv("WAHA_UNKNOWN_AFTER_SECONDS", "300")))
    stale_before = timezone.now() - timedelta(seconds=stale_seconds)
    with transaction.atomic():
        stale_items = list(
            WahaTestReportBatchItem.objects.select_for_update()
            .filter(
                status=WahaTestReportBatchItem.STATUS_PROCESSING,
                started_at__lt=stale_before,
            )
            .values_list("pk", "batch_id")
        )
        if stale_items:
            now = timezone.now()
            stale_ids = [item_id for item_id, _batch_id in stale_items]
            WahaTestReportBatchItem.objects.filter(
                pk__in=stale_ids,
                status=WahaTestReportBatchItem.STATUS_PROCESSING,
            ).update(
                status=WahaTestReportBatchItem.STATUS_UNKNOWN,
                error_message="Worker stopped before confirming the result; manual review is required.",
                finished_at=now,
                updated_at=now,
            )
            for batch_id in {batch_id for _item_id, batch_id in stale_items}:
                _refresh_waha_test_batch(batch_id)

    with transaction.atomic():
        item = (
            WahaTestReportBatchItem.objects.select_for_update(skip_locked=True)
            .filter(status=WahaTestReportBatchItem.STATUS_QUEUED)
            .select_related("batch")
            .order_by("created_at", "id")
            .first()
        )
        if item is None:
            return None
        item.status = WahaTestReportBatchItem.STATUS_PROCESSING
        item.started_at = timezone.now()
        item.save(update_fields=["status", "started_at", "updated_at"])
        batch = item.batch
        batch.status = WahaTestReportBatch.STATUS_PROCESSING
        batch.started_at = batch.started_at or timezone.now()
        batch.save(update_fields=["status", "started_at", "updated_at"])
        return item


def _waha_send_url() -> str:
    base_url = os.getenv("WAHA_API_URL", "http://waha:3000").strip().rstrip("/")
    if not base_url:
        raise WahaTestConfigurationError("WAHA_API_URL must be configured.")
    return f"{base_url}/api/sendText"


def process_waha_test_item(item_id: int) -> dict[str, Any]:
    if not _is_enabled("WAHA_TEST_MODE_ENABLED") or not _is_enabled("WAHA_WORKER_ENABLED"):
        raise WahaTestConfigurationError("WAHA test mode and worker must both be enabled.")
    api_key = os.getenv("WAHA_CLIENT_API_KEY", "").strip()
    if not api_key:
        raise WahaTestConfigurationError("WAHA_CLIENT_API_KEY must be configured.")
    try:
        timeout = max(1, int(os.getenv("WAHA_TIMEOUT_SECONDS", "30")))
    except ValueError as exc:
        raise WahaTestConfigurationError("WAHA_TIMEOUT_SECONDS must be an integer.") from exc

    item = WahaTestReportBatchItem.objects.get(pk=item_id)
    if item.status != WahaTestReportBatchItem.STATUS_PROCESSING:
        return {"status": "skipped", "reason": "item_not_claimed", "item_id": item.pk}

    recipient_digits = re.sub(r"\D", "", str(item.recipient_phone))
    request_body = json.dumps(
        {
            "chatId": f"{recipient_digits}@c.us",
            "text": item.message_text,
            "session": os.getenv("WAHA_SESSION", "default").strip() or "default",
        }
    ).encode("utf-8")
    http_request = request.Request(
        _waha_send_url(),
        data=request_body,
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )

    status_value = WahaTestReportBatchItem.STATUS_UNKNOWN
    response_payload: dict[str, Any] = {}
    error_message = ""
    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
        if raw_body:
            try:
                decoded = json.loads(raw_body)
            except json.JSONDecodeError:
                decoded = {"raw_response": raw_body[:2000]}
            response_payload = decoded if isinstance(decoded, dict) else {"response": decoded}
        status_value = WahaTestReportBatchItem.STATUS_ACCEPTED
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        response_payload = {"http_status": exc.code, "response": raw_body[:2000]}
        if exc.code < 500:
            status_value = WahaTestReportBatchItem.STATUS_FAILED
            error_message = f"WAHA rejected the request with HTTP {exc.code}."
        else:
            error_message = f"WAHA returned HTTP {exc.code}; delivery result is unknown."
    except (error.URLError, TimeoutError, OSError) as exc:
        error_message = f"Could not confirm the WAHA response ({type(exc).__name__}); delivery result is unknown."

    with transaction.atomic():
        locked = WahaTestReportBatchItem.objects.select_for_update().get(pk=item_id)
        if locked.status != WahaTestReportBatchItem.STATUS_PROCESSING:
            return {"status": "skipped", "reason": "item_state_changed", "item_id": item_id}
        locked.status = status_value
        locked.response_payload = response_payload
        locked.error_message = error_message
        locked.finished_at = timezone.now()
        locked.save(update_fields=["status", "response_payload", "error_message", "finished_at", "updated_at"])
    _refresh_waha_test_batch(item.batch_id)
    logger.info(
        "WAHA test report processed: item_id=%s student_id=%s month=%s recipient=%s status=%s",
        item.pk,
        item.student_id,
        item.month.strftime("%Y-%m"),
        _mask_phone(str(item.recipient_phone)),
        status_value,
    )
    return {"item_id": item.pk, "status": status_value, "error_message": error_message}


def run_waha_test_worker(*, once: bool = False, poll_interval: float = 2.0) -> None:
    if not _is_enabled("WAHA_TEST_MODE_ENABLED") or not _is_enabled("WAHA_WORKER_ENABLED"):
        raise WahaTestConfigurationError("Set WAHA_TEST_MODE_ENABLED=true and WAHA_WORKER_ENABLED=true.")
    if not os.getenv("WAHA_CLIENT_API_KEY", "").strip():
        raise WahaTestConfigurationError("WAHA_CLIENT_API_KEY must be configured.")
    try:
        send_interval = max(0.2, float(os.getenv("WAHA_SEND_INTERVAL_SECONDS", "2")))
        int(os.getenv("WAHA_TIMEOUT_SECONDS", "30"))
        int(os.getenv("WAHA_UNKNOWN_AFTER_SECONDS", "300"))
    except ValueError as exc:
        raise WahaTestConfigurationError("WAHA timeout and send interval settings are invalid.") from exc
    while True:
        item = claim_next_waha_test_item()
        if item is None:
            if once:
                return
            time.sleep(max(0.2, poll_interval))
            continue
        process_waha_test_item(item.pk)
        if WahaTestReportBatchItem.objects.filter(status=WahaTestReportBatchItem.STATUS_QUEUED).exists():
            time.sleep(send_interval)
