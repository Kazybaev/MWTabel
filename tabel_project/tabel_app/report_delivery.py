from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import MonthlyStudentReportAttempt, MonthlyStudentReportDispatch


logger = logging.getLogger("tabel_app.reports")


def build_report_message_text(payload: dict[str, Any]) -> str:
    student = payload.get("student", {})
    group = payload.get("group", {})
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
        f"Сизге {group.get('course_name', '')}-группанын студенти "
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
    received_at = timezone.now()

    with transaction.atomic():
        dispatch = (
            MonthlyStudentReportDispatch.objects.select_for_update()
            .select_related("student__user")
            .get(student_id=student_id, month=month)
        )
        stored_response = dispatch.response_payload if isinstance(dispatch.response_payload, dict) else {}
        previous_meta = stored_response.get("meta") if isinstance(stored_response.get("meta"), dict) else {}
        duplicate = (
            previous_meta.get("status_code") == meta_status_code
            and previous_meta.get("response") == meta_response
        )

        response_payload = dict(stored_response)
        response_payload["meta"] = {
            "callback_received": True,
            "channel": delivery.get("channel", "meta_whatsapp"),
            "status_code": meta_status_code,
            "request": delivery.get("meta_request", {}),
            "response": meta_response,
            "rendered_text": delivery.get("rendered_text") or build_report_message_text(report_payload),
            "received_at": received_at.isoformat(),
        }

        succeeded = 200 <= meta_status_code < 300
        dispatch.response_payload = response_payload
        dispatch.status = (
            MonthlyStudentReportDispatch.STATUS_SUCCEEDED
            if succeeded
            else MonthlyStudentReportDispatch.STATUS_FAILED
        )
        dispatch.error_message = "" if succeeded else f"Meta returned HTTP {meta_status_code}."
        if succeeded and dispatch.sent_at is None:
            dispatch.sent_at = received_at
        dispatch.save(update_fields=["status", "response_payload", "error_message", "sent_at", "updated_at"])
        attempt = dispatch.delivery_attempts.order_by("-attempt_number", "-id").first()
        if attempt is not None:
            attempt.response_payload = response_payload
            attempt.status = dispatch.status
            attempt.error_message = dispatch.error_message
            attempt.sent_at = dispatch.sent_at
            attempt.save(
                update_fields=["status", "response_payload", "error_message", "sent_at", "updated_at"]
            )

    logger.info(
        "Meta callback stored: dispatch_id=%s student_id=%s month=%s status=%s duplicate=%s",
        dispatch.pk,
        student_id,
        month.strftime("%Y-%m"),
        meta_status_code,
        duplicate,
    )
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


def build_report_conversations(organization_type: str | None = None) -> list[dict[str, Any]]:
    attempts_queryset = MonthlyStudentReportAttempt.objects.select_related(
            "dispatch__student__user",
            "dispatch__student__group",
        )
    if organization_type:
        attempts_queryset = attempts_queryset.filter(dispatch__student__organization_type=organization_type)
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
    return conversations
