from __future__ import annotations

import json
import logging
import os
import re
import time
from copy import deepcopy
from datetime import date, timedelta
from typing import Any
from urllib import error, request
from urllib.parse import quote

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    MonthlyStudentReportBatchItem,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
    WahaParentReportBatch,
    WahaParentReportBatchItem,
    WahaTestReportBatchItem,
)
from .report import (
    build_student_month_report,
    get_group_last_lesson_date,
    normalize_month_start,
)
from .report_delivery import build_report_message_text


logger = logging.getLogger("tabel_app.waha_parent_reports")
MAX_PARENT_REPORT_BATCH_SIZE = 1000
WAHA_TEST_BLOCKING_STATUSES = (
    WahaTestReportBatchItem.STATUS_QUEUED,
    WahaTestReportBatchItem.STATUS_PROCESSING,
    WahaTestReportBatchItem.STATUS_ACCEPTED,
    WahaTestReportBatchItem.STATUS_UNKNOWN,
)
class WahaParentConfigurationError(Exception):
    pass


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_phone(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"\+?[1-9]\d{7,14}", normalized):
        raise ValueError("Parent phone is not a valid international phone number.")
    return f"+{normalized.lstrip('+')}"


def _mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"***{digits[-4:]}" if digits else ""


def get_waha_parent_configuration() -> dict[str, Any]:
    api_configured = (
        bool(os.getenv("WAHA_PARENT_CLIENT_API_KEY", "").strip())
        or _enabled("WAHA_PARENT_CLIENT_API_KEY_CONFIGURED")
    ) and _enabled("WAHA_PARENT_SERVER_API_KEY_CONFIGURED")
    enabled = _enabled("WAHA_PARENT_REPORTS_ENABLED")
    worker_enabled = _enabled("WAHA_PARENT_WORKER_ENABLED")
    return {
        "enabled": enabled,
        "worker_enabled": worker_enabled,
        "ready": enabled and worker_enabled and api_configured,
        "api_configured": api_configured,
        "max_batch_size": MAX_PARENT_REPORT_BATCH_SIZE,
    }


def _cross_channel_conflicts(
    student_ids: list[int],
    month: date,
) -> dict[int, str]:
    conflicts: dict[int, str] = {}
    sources = (
        (
            MonthlyStudentReportDispatch.objects.filter(student_id__in=student_ids, month=month),
            "A Dify/Meta dispatch already exists for this student and month; review it before using WAHA.",
        ),
        (
            MonthlyStudentReportBatchItem.objects.filter(
                student_id__in=student_ids,
                month=month,
                status__in=MonthlyStudentReportBatchItem.ACTIVE_STATUSES
                + (
                    MonthlyStudentReportBatchItem.STATUS_ACCEPTED,
                    MonthlyStudentReportBatchItem.STATUS_DELIVERED,
                ),
            ),
            "A Dify/Meta report is queued or already accepted for this student and month.",
        ),
        (
            WahaTestReportBatchItem.objects.filter(
                student_id__in=student_ids,
                month=month,
                status__in=WAHA_TEST_BLOCKING_STATUSES,
            ),
            "A WAHA test attempt exists for this student and month; review it before using the parent channel.",
        ),
    )
    for queryset, reason in sources:
        for student_id in queryset.values_list("student_id", flat=True).distinct():
            conflicts.setdefault(student_id, reason)
    return conflicts


def _cached_group_last_lesson_date(
    student: StudentProfile,
    month: date,
    cache: dict[int, date | None],
) -> date | None:
    if student.group_id not in cache:
        cache[student.group_id] = get_group_last_lesson_date(student.group, month)
    return cache[student.group_id]


def _safe_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe_payload = deepcopy(payload)
    safe_payload["student"].pop("parent_phone", None)
    return safe_payload


def _report_snapshot_signature(payload: dict[str, Any]) -> str:
    snapshot = _safe_report_payload(payload)
    snapshot.get("period", {}).pop("generated_at", None)
    return json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _eligibility_error(
    student: StudentProfile,
    month: date,
    *,
    payload: dict[str, Any] | None = None,
    trigger_date: date | None = None,
    last_lesson_cache: dict[int, date | None] | None = None,
) -> str:
    if student.archived_at is not None or student.group.archived_at is not None:
        return "Student or group is archived."
    try:
        _normalize_phone(str(student.parent_phone or ""))
    except ValueError:
        return "Parent phone is missing or invalid."
    if trigger_date is None:
        trigger_date = (
            _cached_group_last_lesson_date(student, month, last_lesson_cache)
            if last_lesson_cache is not None
            else get_group_last_lesson_date(student.group, month)
        )
    if payload is None:
        payload = build_student_month_report(
            student,
            month_start=month,
            trigger_date=trigger_date,
        )
    if payload.get("status") == "skipped":
        return "Student or group is archived."
    if not payload.get("lessons"):
        return "No lessons exist for this student in the report month."
    if not payload.get("summary", {}).get("marked_lessons_count"):
        return "No marked lesson records exist for this report month."
    if trigger_date is None:
        return "No lessons exist in the student's group for this report month."
    return ""


def prepare_waha_parent_batch(
    *,
    created_by: User,
    month: date,
    organization_type: str,
    college_branch: str | None = None,
    students: list[StudentProfile],
    requested_filters: dict[str, Any],
) -> WahaParentReportBatch:
    if not students:
        raise ValueError("No active students match the selected filters.")
    if len(students) > MAX_PARENT_REPORT_BATCH_SIZE:
        raise ValueError(f"Parent report batches are limited to {MAX_PARENT_REPORT_BATCH_SIZE} students.")
    month_start = normalize_month_start(month)
    with transaction.atomic():
        batch = WahaParentReportBatch.objects.create(
            month=month_start,
            organization_type=organization_type,
            college_branch=college_branch or "",
            requested_filters=requested_filters,
            created_by=created_by,
        )
        requested_student_ids = sorted({student.pk for student in students})
        locked_students = list(
            StudentProfile.objects.select_for_update().filter(pk__in=requested_student_ids).select_related(
                "user", "group", "group__mentor__user"
            ).order_by("group__course_name", "user__full_name", "pk")
        )
        if len(locked_students) != len(requested_student_ids):
            raise ValueError("One or more students no longer exist.")
        conflicts = _cross_channel_conflicts(requested_student_ids, month_start)
        last_lesson_cache: dict[int, date | None] = {}
        for locked_student in locked_students:
            error_message = conflicts.get(locked_student.pk, "")
            payload = None
            trigger_date = _cached_group_last_lesson_date(locked_student, month_start, last_lesson_cache)
            if not error_message:
                try:
                    _normalize_phone(str(locked_student.parent_phone or ""))
                except ValueError:
                    error_message = "Parent phone is missing or invalid."
            if not error_message:
                payload = build_student_month_report(
                    locked_student,
                    month_start=month_start,
                    trigger_date=trigger_date,
                )
                error_message = _eligibility_error(
                    locked_student,
                    month_start,
                    payload=payload,
                    trigger_date=trigger_date,
                    last_lesson_cache=last_lesson_cache,
                )
            if error_message:
                WahaParentReportBatchItem.objects.create(
                    batch=batch,
                    student=locked_student,
                    month=month_start,
                    recipient_phone="",
                    status=WahaParentReportBatchItem.STATUS_SKIPPED,
                    error_message=error_message,
                    finished_at=timezone.now(),
                )
                continue

            payload = _safe_report_payload(payload)
            item = WahaParentReportBatchItem(
                batch=batch,
                student=locked_student,
                month=month_start,
                recipient_phone=_normalize_phone(str(locked_student.parent_phone)),
                report_payload=payload,
                message_text=build_report_message_text(payload),
                status=WahaParentReportBatchItem.STATUS_DRAFT,
            )
            try:
                with transaction.atomic():
                    item.save(force_insert=True)
            except IntegrityError:
                WahaParentReportBatchItem.objects.create(
                    batch=batch,
                    student=locked_student,
                    month=month_start,
                    recipient_phone="",
                    status=WahaParentReportBatchItem.STATUS_SKIPPED,
                    error_message="A report for this student and month is already prepared.",
                    finished_at=timezone.now(),
                )
        _refresh_batch(batch.pk)
    return batch


def confirm_waha_parent_batch(batch_id: int) -> WahaParentReportBatch:
    configuration = get_waha_parent_configuration()
    if not configuration["ready"]:
        raise WahaParentConfigurationError("Parent-report WAHA sending is disabled or incomplete.")
    with transaction.atomic():
        batch = WahaParentReportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != WahaParentReportBatch.STATUS_DRAFT:
            raise ValueError("Only draft batches can be confirmed.")
        items = list(
            batch.items.select_for_update()
            .filter(status=WahaParentReportBatchItem.STATUS_DRAFT)
            .select_related("student__user", "student__group", "student__group__mentor__user")
            .order_by("student__group__course_name", "student__user__full_name", "student_id")
        )
        student_ids = [item.student_id for item in items]
        students = list(
            StudentProfile.objects.select_for_update()
            .filter(pk__in=student_ids)
            .select_related("user", "group", "group__mentor__user")
            .order_by("group__course_name", "user__full_name", "pk")
        )
        students_by_id = {student.pk: student for student in students}
        conflicts = _cross_channel_conflicts(
            student_ids,
            batch.month,
        )
        last_lesson_cache: dict[int, date | None] = {}
        for item in items:
            student = students_by_id[item.student_id]
            trigger_date = _cached_group_last_lesson_date(student, batch.month, last_lesson_cache)
            fresh_payload = build_student_month_report(
                student,
                month_start=batch.month,
                trigger_date=trigger_date,
            )
            error_message = _eligibility_error(
                student,
                batch.month,
                payload=fresh_payload,
                trigger_date=trigger_date,
                last_lesson_cache=last_lesson_cache,
            )
            if not error_message and _normalize_phone(str(student.parent_phone)) != str(item.recipient_phone):
                error_message = "Parent phone changed after preparation; prepare a new batch."
            if not error_message:
                error_message = conflicts.get(student.pk, "")
            if not error_message and _report_snapshot_signature(fresh_payload) != _report_snapshot_signature(item.report_payload):
                error_message = "Report data changed after preparation; prepare and review a new draft."
            if error_message:
                item.status = WahaParentReportBatchItem.STATUS_SKIPPED
                item.error_message = error_message
                item.finished_at = timezone.now()
                item.dedupe_key = None
            else:
                item.status = WahaParentReportBatchItem.STATUS_QUEUED
            item.save(update_fields=["status", "error_message", "finished_at", "dedupe_key", "updated_at"])
        batch.confirmed_at = timezone.now()
        batch.status = (
            WahaParentReportBatch.STATUS_QUEUED
            if batch.items.filter(status=WahaParentReportBatchItem.STATUS_QUEUED).exists()
            else WahaParentReportBatch.STATUS_COMPLETED
        )
        if batch.status == WahaParentReportBatch.STATUS_COMPLETED:
            batch.completed_at = timezone.now()
        batch.save(update_fields=["confirmed_at", "status", "completed_at", "updated_at"])
    return batch


def cancel_waha_parent_batch(batch_id: int) -> WahaParentReportBatch:
    with transaction.atomic():
        batch = WahaParentReportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != WahaParentReportBatch.STATUS_DRAFT:
            raise ValueError("Only draft batches can be cancelled.")
        now = timezone.now()
        batch.items.filter(status=WahaParentReportBatchItem.STATUS_DRAFT).update(
            status=WahaParentReportBatchItem.STATUS_CANCELLED,
            finished_at=now,
            dedupe_key=None,
            updated_at=now,
        )
        batch.status = WahaParentReportBatch.STATUS_CANCELLED
        batch.completed_at = now
        batch.save(update_fields=["status", "completed_at", "updated_at"])
    return batch


def _refresh_batch(batch_id: int) -> None:
    with transaction.atomic():
        batch = WahaParentReportBatch.objects.select_for_update().get(pk=batch_id)
        statuses = set(batch.items.values_list("status", flat=True))
        if not statuses or statuses.issubset(set(WahaParentReportBatchItem.TERMINAL_STATUSES)):
            batch.status = WahaParentReportBatch.STATUS_COMPLETED
            batch.completed_at = batch.completed_at or timezone.now()
        elif WahaParentReportBatchItem.STATUS_PROCESSING in statuses:
            batch.status = WahaParentReportBatch.STATUS_PROCESSING
            batch.started_at = batch.started_at or timezone.now()
        batch.save(update_fields=["status", "started_at", "completed_at", "updated_at"])


def serialize_waha_parent_batch(
    batch: WahaParentReportBatch,
    *,
    include_message_text: bool = False,
    include_items: bool = True,
) -> dict[str, Any]:
    counts = batch.items.aggregate(
        total=Count("id"),
        draft=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_DRAFT)),
        queued=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_QUEUED)),
        processing=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_PROCESSING)),
        accepted=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_ACCEPTED)),
        failed=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_FAILED)),
        unknown=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_UNKNOWN)),
        skipped=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_SKIPPED)),
        cancelled=Count("id", filter=Q(status=WahaParentReportBatchItem.STATUS_CANCELLED)),
    )
    counts["remaining"] = counts["draft"] + counts["queued"] + counts["processing"]
    return {
        "id": batch.pk,
        "month": batch.month.strftime("%Y-%m"),
        "status": batch.status,
        "status_url": f"/api/reports/waha-parent/batches/{batch.pk}/",
        "confirmed_at": batch.confirmed_at,
        "created_at": batch.created_at,
        **counts,
        "remaining": counts["draft"] + counts["queued"] + counts["processing"],
        "items": [
            {
                "id": item.pk,
                "student_id": item.student_id,
                "student_name": item.student.user.full_name,
                "group_name": item.student.group.course_name,
                "status": item.status,
                "error_message": item.error_message,
                "recipient_masked": _mask_phone(str(item.recipient_phone)),
                **({"message_text": item.message_text} if include_message_text else {}),
            }
            for item in batch.items.select_related("student__user", "student__group").order_by("id")
        ] if include_items else None,
    }


def claim_next_waha_parent_item() -> WahaParentReportBatchItem | None:
    stale_seconds = max(60, int(os.getenv("WAHA_UNKNOWN_AFTER_SECONDS", "300")))
    stale_before = timezone.now() - timedelta(seconds=stale_seconds)
    with transaction.atomic():
        stale = list(
            WahaParentReportBatchItem.objects.select_for_update()
            .filter(status=WahaParentReportBatchItem.STATUS_PROCESSING, started_at__lt=stale_before)
            .values_list("pk", "batch_id")
        )
        if stale:
            now = timezone.now()
            ids = [item_id for item_id, _batch_id in stale]
            WahaParentReportBatchItem.objects.filter(
                pk__in=ids,
                status=WahaParentReportBatchItem.STATUS_PROCESSING,
            ).update(
                status=WahaParentReportBatchItem.STATUS_UNKNOWN,
                error_message="Worker stopped before confirming the result; manual review is required.",
                finished_at=now,
                updated_at=now,
            )
            for batch_id in {batch_id for _item_id, batch_id in stale}:
                _refresh_batch(batch_id)
    with transaction.atomic():
        item = (
            WahaParentReportBatchItem.objects.select_for_update(skip_locked=True)
            .filter(status=WahaParentReportBatchItem.STATUS_QUEUED)
            .select_related("batch")
            .order_by("created_at", "id")
            .first()
        )
        if item is None:
            return None
        item.status = WahaParentReportBatchItem.STATUS_PROCESSING
        item.started_at = timezone.now()
        item.save(update_fields=["status", "started_at", "updated_at"])
        WahaParentReportBatch.objects.filter(pk=item.batch_id).update(
            status=WahaParentReportBatch.STATUS_PROCESSING,
            started_at=timezone.now(),
        )
        return item


def process_waha_parent_item(item_id: int) -> dict[str, Any]:
    if not get_waha_parent_configuration()["ready"]:
        raise WahaParentConfigurationError("Parent-report WAHA sending is disabled or incomplete.")
    api_key = os.getenv("WAHA_PARENT_CLIENT_API_KEY", "").strip()
    try:
        timeout = max(1, int(os.getenv("WAHA_TIMEOUT_SECONDS", "30")))
    except ValueError as exc:
        raise WahaParentConfigurationError("WAHA_TIMEOUT_SECONDS must be an integer.") from exc
    item = WahaParentReportBatchItem.objects.get(pk=item_id)
    if item.status != WahaParentReportBatchItem.STATUS_PROCESSING:
        return {"status": "skipped", "reason": "item_not_claimed", "item_id": item.pk}
    chat_id = re.sub(r"\D", "", str(item.recipient_phone)) + "@c.us"
    payload = json.dumps({
        "chatId": chat_id,
        "text": item.message_text,
        "session": os.getenv("WAHA_SESSION", "default").strip() or "default",
    }).encode("utf-8")
    http_request = request.Request(
        os.getenv("WAHA_API_URL", "http://waha-test:3000").rstrip("/") + "/api/sendText",
        data=payload,
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    status_value = WahaParentReportBatchItem.STATUS_UNKNOWN
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
        status_value = WahaParentReportBatchItem.STATUS_ACCEPTED
    except error.HTTPError as exc:
        response_payload = {"http_status": exc.code, "response": exc.read().decode("utf-8", errors="replace")[:2000]}
        if exc.code < 500:
            status_value = WahaParentReportBatchItem.STATUS_FAILED
            error_message = f"WAHA rejected the request with HTTP {exc.code}."
        else:
            error_message = f"WAHA returned HTTP {exc.code}; delivery result is unknown."
    except (error.URLError, TimeoutError, OSError) as exc:
        error_message = f"Could not confirm the WAHA response ({type(exc).__name__}); delivery result is unknown."
    with transaction.atomic():
        locked = WahaParentReportBatchItem.objects.select_for_update().get(pk=item_id)
        if locked.status != WahaParentReportBatchItem.STATUS_PROCESSING:
            return {"status": "skipped", "reason": "item_state_changed", "item_id": item_id}
        locked.status = status_value
        locked.response_payload = response_payload
        locked.error_message = error_message
        locked.finished_at = timezone.now()
        locked.save(update_fields=["status", "response_payload", "error_message", "finished_at", "updated_at"])
    _refresh_batch(item.batch_id)
    logger.info(
        "WAHA parent report processed: item_id=%s student_id=%s month=%s recipient=%s status=%s",
        item.pk,
        item.student_id,
        item.month.strftime("%Y-%m"),
        _mask_phone(str(item.recipient_phone)),
        status_value,
    )
    return {"item_id": item.pk, "status": status_value, "error_message": error_message}


def _waha_parent_get_json(path: str, api_key: str, timeout: int) -> dict[str, Any] | None:
    url = os.getenv("WAHA_API_URL", "http://waha-parent:3000").rstrip("/") + path
    http_request = request.Request(url, headers={"X-Api-Key": api_key}, method="GET")
    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code in (401, 403):
            raise WahaParentConfigurationError("WAHA rejected production API authentication.") from exc
        logger.warning("WAHA readiness endpoint returned HTTP %s.", exc.code)
        return None
    except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("WAHA readiness check failed (%s).", type(exc).__name__)
        return None
    return decoded if isinstance(decoded, dict) else None


def _waha_parent_readiness(api_key: str, timeout: int) -> tuple[bool, str, float | None]:
    session = quote(os.getenv("WAHA_SESSION", "default").strip() or "default", safe="")
    session_data = _waha_parent_get_json(f"/api/sessions/{session}", api_key, timeout)
    if not session_data or str(session_data.get("status", "")).upper() != "WORKING":
        return False, "WAHA session is not WORKING.", None

    timelock = _waha_parent_get_json(f"/api/sessions/{session}/timelock", api_key, timeout)
    if not timelock or not isinstance(timelock.get("isActive"), bool):
        return False, "WAHA reachout-timelock state is unavailable.", None
    if timelock["isActive"]:
        ends_at = timelock.get("timeEnforcementEnds")
        wait_seconds = (
            max(1.0, float(ends_at) - time.time())
            if isinstance(ends_at, (int, float))
            else None
        )
        return False, "WhatsApp reachout timelock is active.", wait_seconds
    return True, "", None


def run_waha_parent_worker(*, once: bool = False, poll_interval: float = 2.0) -> None:
    if not get_waha_parent_configuration()["ready"]:
        raise WahaParentConfigurationError("Set WAHA_PARENT_REPORTS_ENABLED and WAHA_PARENT_WORKER_ENABLED to true.")
    try:
        send_interval = max(2.0, float(os.getenv("WAHA_SEND_INTERVAL_SECONDS", "2")))
        timeout = max(1, int(os.getenv("WAHA_TIMEOUT_SECONDS", "30")))
    except ValueError as exc:
        raise WahaParentConfigurationError("WAHA_SEND_INTERVAL_SECONDS and WAHA_TIMEOUT_SECONDS must be numeric.") from exc
    api_key = os.getenv("WAHA_PARENT_CLIENT_API_KEY", "").strip()
    while True:
        ready, reason, wait_seconds = _waha_parent_readiness(api_key, timeout)
        if not ready:
            if once:
                raise WahaParentConfigurationError(reason)
            logger.warning("Parent queue paused: %s", reason)
            retry_after = max(15.0, poll_interval)
            if wait_seconds is not None:
                retry_after = min(retry_after, wait_seconds)
            time.sleep(retry_after)
            continue
        item = claim_next_waha_parent_item()
        if item is None:
            if once:
                return
            time.sleep(max(0.1, poll_interval))
            continue
        process_waha_parent_item(item.pk)
        time.sleep(send_interval)
