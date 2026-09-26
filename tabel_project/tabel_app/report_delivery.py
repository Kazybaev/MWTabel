from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import (
    MonthlyStudentReportAttempt,
    MonthlyStudentReportBatchItem,
    MonthlyStudentReportDispatch,
    StudentProfile,
)


logger = logging.getLogger("tabel_app.reports")


def build_report_message_text(payload: dict[str, Any]) -> str:
    if payload.get("message_text"):
        return payload["message_text"]
    student = payload.get("student", {})
    group = payload.get("group", {})
    groups = payload.get("groups") or []
    period = payload.get("period", {})
    summary = payload.get("summary", {})
    month_names = {
        "01": "Январь",
        "02": "Февраль",
        "03": "Март",
        "04": "Апрель",
        "05": "Май",
        "06": "Июнь",
        "07": "Июль",
        "08": "Август",
        "09": "Сентябрь",
        "10": "Октябрь",
        "11": "Ноябрь",
        "12": "Декабрь",
    }
    month_value = str(period.get("month", ""))
    month_label = month_names.get(month_value[-2:], month_value or "Отчёттук")
    grade_lines = []
    for grade, key in (("5", "total_five"), ("4", "total_four"), ("3", "total_three"), ("2", "total_two")):
        count = int(summary.get(key, 0) or 0)
        if count:
            grade_lines.append(f'“{grade}” – {count} даана')
    grades_text = "\n".join(grade_lines) or "Баалар коюлган жок"
    absence_count = int(summary.get("absence_count", 0) or 0)
    absence_text = (
        "1ай ичинде сабактан калган жок"
        if absence_count == 0
        else f"1ай ичинде сабактан {absence_count} жолу калды"
    )
    return (
        "Саламатсызбы!\n"
        "Сиз менен Motion Web IT академиясынан байланышып жатабыз ✅\n\n"
        f"Сизге {', '.join(item.get('course_name', '') for item in groups) or group.get('course_name', '')}-группанын студенти "
        f"{student.get('full_name', '')} окуусу тууралуу маалымат бере кетели 📊\n\n"
        f"{month_label} айындагы баалары:\n"
        f"{grades_text}\n\n"
        f"{absence_text}\n"
        "📢Эскертүү 1 ай ичинде сабактан 3 жолу калса — сабактан четтетилет!"
    )


def record_meta_delivery_callback(
    delivery: dict[str, Any],
    meta_status_code: int,
    meta_response: Any,
) -> tuple[MonthlyStudentReportDispatch, bool]:
    report_payload = delivery["report"]
    student_id = int(report_payload["student"]["id"])
    month = datetime.strptime(report_payload["period"]["month"], "%Y-%m").date().replace(day=1)
    correlation = report_payload.get("correlation")
    if not isinstance(correlation, dict):
        raise ValueError("delivery.report.correlation is required")
    dispatch_id = int(correlation["dispatch_id"])
    attempt_id = int(correlation["attempt_id"])
    batch_item_id = correlation.get("batch_item_id")
    if batch_item_id is not None:
        batch_item_id = int(batch_item_id)

    if not isinstance(meta_response, dict):
        raise TypeError("meta_response must be a JSON object")
    messages = meta_response.get("messages")
    first_message = messages[0] if isinstance(messages, list) and messages and isinstance(messages[0], dict) else {}
    meta_message_id = str(first_message.get("id") or "").strip()
    message_status = str(first_message.get("message_status") or "").strip().lower()
    if 200 <= meta_status_code < 300 and (not meta_message_id or not message_status):
        raise ValueError("Meta message id and message_status are required for a successful HTTP response")
    if not message_status:
        message_status = "failed"
    received_at = timezone.now()

    with transaction.atomic():
        attempt = (
            MonthlyStudentReportAttempt.objects.select_for_update()
            .select_related("dispatch__student__user")
            .get(pk=attempt_id, dispatch_id=dispatch_id)
        )
        dispatch = MonthlyStudentReportDispatch.objects.select_for_update().get(pk=attempt.dispatch_id)
        if dispatch.student_id != student_id or dispatch.month != month:
            raise ValueError("Callback correlation does not match student and month")
        item = None
        if batch_item_id is not None:
            item = MonthlyStudentReportBatchItem.objects.select_for_update().get(
                pk=batch_item_id,
                dispatch=dispatch,
                attempt=attempt,
                student_id=student_id,
                month=month,
            )
        elif MonthlyStudentReportBatchItem.objects.filter(attempt=attempt).exists():
            raise ValueError("Callback correlation is missing the linked batch item")
        duplicate_owner = bool(meta_message_id) and MonthlyStudentReportAttempt.objects.filter(
            meta_message_id=meta_message_id
        ).exclude(pk=attempt.pk).exists()
        if duplicate_owner:
            raise ValueError("Meta message id is already assigned to another attempt")

        stored_response = attempt.response_payload if isinstance(attempt.response_payload, dict) else {}
        previous_meta = stored_response.get("meta") if isinstance(stored_response.get("meta"), dict) else {}
        duplicate = (
            attempt.meta_message_id == meta_message_id
            and previous_meta.get("status_code") == meta_status_code
            and previous_meta.get("response") == meta_response
        )
        if previous_meta.get("callback_received") and not duplicate:
            raise ValueError("Attempt already has a different successful callback")
        if duplicate:
            return dispatch, True

        if 200 <= meta_status_code < 300 and message_status == "accepted":
            delivery_status = MonthlyStudentReportDispatch.STATUS_ACCEPTED
        elif 200 <= meta_status_code < 300 and message_status == "delivered":
            delivery_status = MonthlyStudentReportDispatch.STATUS_DELIVERED
        else:
            delivery_status = MonthlyStudentReportDispatch.STATUS_FAILED

        response_payload = dict(stored_response)
        response_payload["meta"] = {
            "callback_received": True,
            "channel": delivery.get("channel", "meta_whatsapp"),
            "status_code": meta_status_code,
            "request": delivery.get("meta_request", {}),
            "response": meta_response,
            "message_id": meta_message_id,
            "message_status": message_status,
            "rendered_text": delivery.get("rendered_text") or build_report_message_text(report_payload),
            "received_at": received_at.isoformat(),
        }

        error_message = "" if delivery_status != MonthlyStudentReportDispatch.STATUS_FAILED else (
            f"Meta returned HTTP {meta_status_code} with message_status '{message_status}'."
        )
        sent_at = received_at if delivery_status in MonthlyStudentReportDispatch.SUCCESSFUL_STATUSES else None
        attempt.response_payload = response_payload
        attempt.status = delivery_status
        attempt.error_message = error_message
        attempt.sent_at = attempt.sent_at or sent_at
        attempt.meta_message_id = meta_message_id or None
        attempt.message_status = message_status
        attempt.save(update_fields=[
            "status", "response_payload", "error_message", "sent_at", "meta_message_id", "message_status", "updated_at"
        ])

        if attempt.attempt_number == dispatch.attempts:
            dispatch.response_payload = response_payload
            dispatch.status = delivery_status
            dispatch.error_message = error_message
            dispatch.sent_at = dispatch.sent_at or sent_at
            dispatch.save(update_fields=["status", "response_payload", "error_message", "sent_at", "updated_at"])

        if item is not None:
            item.status = delivery_status
            item.error_message = error_message
            item.finished_at = received_at
            item.worker_token = None
            item.save(update_fields=["status", "error_message", "finished_at", "worker_token", "updated_at"])

    logger.info(
        "Meta callback stored: dispatch_id=%s student_id=%s month=%s status=%s duplicate=%s",
        dispatch.pk,
        student_id,
        month.strftime("%Y-%m"),
        meta_status_code,
        duplicate,
    )
    if batch_item_id is not None:
        from .report_queue import refresh_batch_status

        refresh_batch_status(item.batch_id)
    return dispatch, duplicate


def serialize_report_message(dispatch: MonthlyStudentReportDispatch) -> dict[str, Any]:
    payload = dispatch.payload if isinstance(dispatch.payload, dict) else {}
    response_payload = dispatch.response_payload if isinstance(dispatch.response_payload, dict) else {}
    meta = response_payload.get("meta", {}) if isinstance(response_payload.get("meta"), dict) else {}
    return {
        "id": dispatch.pk,
        "month": dispatch.month.strftime("%Y-%m"),
        "status": dispatch.status,
        "attempts": dispatch.attempts,
        "sent_at": dispatch.sent_at,
        "created_at": dispatch.created_at,
        "updated_at": dispatch.updated_at,
        "error_message": dispatch.error_message,
        "summary": payload.get("summary", {}),
        "lessons": payload.get("lessons", []),
        "rendered_text": meta.get("rendered_text") or build_report_message_text(payload),
        "meta": meta,
        "workflow_run_id": dispatch.workflow_run_id,
    }


def serialize_report_attempt(attempt: MonthlyStudentReportAttempt) -> dict[str, Any]:
    payload = attempt.payload if isinstance(attempt.payload, dict) else {}
    response_payload = attempt.response_payload if isinstance(attempt.response_payload, dict) else {}
    meta = response_payload.get("meta", {}) if isinstance(response_payload.get("meta"), dict) else {}
    return {
        "id": f"attempt-{attempt.pk}",
        "month": attempt.dispatch.month.strftime("%Y-%m"),
        "status": attempt.status,
        "attempts": attempt.attempt_number,
        "sent_at": attempt.sent_at,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
        "error_message": attempt.error_message,
        "summary": payload.get("summary", {}),
        "lessons": payload.get("lessons", []),
        "rendered_text": meta.get("rendered_text") or build_report_message_text(payload),
        "meta": meta,
        "workflow_run_id": attempt.workflow_run_id,
    }


def build_report_conversations(
    organization_type: str | None = None,
    college_branch: str | None = None,
) -> list[dict[str, Any]]:
    attempts_queryset = MonthlyStudentReportAttempt.objects.select_related(
            "dispatch__student__user",
            "dispatch__student__group",
        )
    if organization_type:
        attempts_queryset = attempts_queryset.filter(dispatch__student__organization_type=organization_type)
    if college_branch:
        attempts_queryset = attempts_queryset.filter(dispatch__student__college_branch=college_branch)
    attempts = list(attempts_queryset.order_by("dispatch__student_id", "-created_at", "-id"))
    message_counts = Counter(attempt.dispatch.student_id for attempt in attempts)
    conversations = []
    seen_students = set()
    for attempt in attempts:
        dispatch = attempt.dispatch
        if dispatch.student_id in seen_students:
            continue
        seen_students.add(dispatch.student_id)
        conversations.append(
            {
                "student_id": dispatch.student_id,
                "student_name": dispatch.student.user.full_name,
                "parent_name": dispatch.student.parent_name,
                "parent_phone": str(dispatch.student.parent_phone),
                "group_name": dispatch.student.group.course_name,
                "latest_status": attempt.status,
                "latest_month": dispatch.month.strftime("%Y-%m"),
                "latest_at": attempt.updated_at,
                "messages_count": message_counts[dispatch.student_id],
            }
        )
    student_queryset = StudentProfile.objects.select_related("user", "group").filter(archived_at__isnull=True)
    if organization_type:
        student_queryset = student_queryset.filter(organization_type=organization_type)
    if college_branch:
        student_queryset = student_queryset.filter(college_branch=college_branch)
    for student in student_queryset:
        if student.pk in seen_students:
            continue
        conversations.append(
            {
                "student_id": student.pk,
                "student_name": student.user.full_name,
                "parent_name": student.parent_name,
                "parent_phone": str(student.parent_phone),
                "group_name": student.group.course_name,
                "latest_status": "not_sent",
                "latest_month": None,
                "latest_at": None,
                "messages_count": 0,
            }
        )
    return conversations
