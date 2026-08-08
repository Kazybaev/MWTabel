from __future__ import annotations
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib import error, request

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MonthlyStudentReportAttempt,
    MonthlyStudentReportDispatch,
    StudentProfile,
)


ABSENCE_GRADE = "\u041d"
ABSENCE_GRADE_VALUES = {ABSENCE_GRADE, ABSENCE_GRADE.lower()}

logger = logging.getLogger("tabel_app.reports")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [reports] %(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(getattr(logging, os.getenv("REPORT_LOG_LEVEL", "INFO").upper(), logging.INFO))
logger.propagate = False

REPORT_DISPATCH_DELAY_SECONDS = 10
REPORT_DISPATCH_DELAY_STATUSES = {"sent", "failed"}


class ReportConfigurationError(Exception):
    pass


class ReportDeliveryError(Exception):
    pass


def mask_phone(value: Any) -> str:
    normalized = "".join(character for character in str(value or "") if character.isdigit())
    return f"***{normalized[-4:]}" if normalized else ""


def get_dify_workflow_status(response_payload: dict[str, Any]) -> str:
    data = response_payload.get("data")
    if isinstance(data, dict) and data.get("status"):
        return str(data["status"]).strip().lower()
    return str(response_payload.get("status", "")).strip().lower()


def accepts_partial_dify_success() -> bool:
    return os.getenv("DIFY_ACCEPT_PARTIAL_SUCCESS", "False").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize_month_start(value: date | datetime | None) -> date:
    if value is None:
        return timezone.localdate().replace(day=1)
    if isinstance(value, datetime):
        value = value.date()
    return value.replace(day=1)


def normalize_run_date(value: date | datetime | None) -> date:
    if value is None:
        return timezone.localdate()
    if isinstance(value, datetime):
        return value.date()
    return value


def month_bounds(month_start: date) -> tuple[date, date]:
    month_start = normalize_month_start(month_start)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return month_start, next_month - timedelta(days=1)


def is_absence_grade(grade: str | None) -> bool:
    normalized = (grade or "").strip()
    return normalized in ABSENCE_GRADE_VALUES


def get_group_study_weekdays(group: Group) -> set[int]:
    if group.study_days == Group.MON_WED_SAT:
        return {0, 2, 5}
    if group.study_days == Group.TUE_THU_SUN:
        return {1, 3, 6}
    return set()


def get_group_last_lesson_date(group: Group, month_start: date) -> date | None:
    month_start, month_end = month_bounds(month_start)
    study_weekdays = get_group_study_weekdays(group)
    if study_weekdays:
        current_date = month_end
        while current_date >= month_start:
            if current_date.weekday() in study_weekdays:
                return current_date
            current_date -= timedelta(days=1)
        return None

    return (
        group.lessons.filter(lesson_date__gte=month_start, lesson_date__lte=month_end)
        .order_by("-lesson_date", "-id")
        .values_list("lesson_date", flat=True)
        .first()
    )


def get_student_trigger_lesson(student: StudentProfile, month_start: date) -> Lesson | None:
    trigger_date = get_group_last_lesson_date(student.group, month_start)
    if trigger_date is None:
        return None

    return (
        Lesson.objects.filter(
            group=student.group,
            lesson_date=trigger_date,
        )
        .order_by("-id")
        .first()
    )


def has_student_trigger_lesson_record(student: StudentProfile, trigger_lesson: Lesson) -> bool:
    return LessonRecord.objects.filter(student=student, lesson=trigger_lesson).exists()


def get_month_lessons_for_student(student: StudentProfile, month_start: date) -> list[Lesson]:
    month_start, month_end = month_bounds(month_start)
    return list(
        Lesson.objects.filter(
            group=student.group,
            lesson_date__gte=month_start,
            lesson_date__lte=month_end,
        ).order_by("lesson_date", "id")
    )


def get_month_records_for_student(student: StudentProfile, month_start: date) -> list[LessonRecord]:
    month_start, month_end = month_bounds(month_start)
    return list(
        LessonRecord.objects.filter(
            student=student,
            lesson__group=student.group,
            lesson__lesson_date__gte=month_start,
            lesson__lesson_date__lte=month_end,
        )
        .select_related("lesson")
        .order_by("lesson__lesson_date", "lesson_id")
    )


def build_student_month_report(
    student: StudentProfile,
    month_start: date | datetime | None = None,
    trigger_date: date | None = None,
) -> dict[str, Any]:
    month_start = normalize_month_start(month_start)
    month_start, month_end = month_bounds(month_start)
    lessons = get_month_lessons_for_student(student, month_start)
    records = get_month_records_for_student(student, month_start)
    trigger_date = trigger_date or get_group_last_lesson_date(student.group, month_start)

    records_by_lesson_id = {record.lesson_id: record for record in records}
    numeric_grades: list[int] = []
    attendance_count = 0
    absence_count = 0
    grade_totals = {
        "5": 0,
        "4": 0,
        "3": 0,
        "2": 0,
        "Н": 0,
    }
    lesson_rows: list[dict[str, Any]] = []

    for lesson in lessons:
        record = records_by_lesson_id.get(lesson.pk)
        grade = (record.grade or "").strip() if record else ""
        if grade.isdigit():
            numeric_grades.append(int(grade))
            attendance_count += 1
            if grade in grade_totals:
                grade_totals[grade] += 1
        elif grade:
            if is_absence_grade(grade):
                absence_count += 1
                grade_totals["Н"] += 1
            else:
                attendance_count += 1

        lesson_rows.append(
            {
                "lesson_id": lesson.pk,
                "date": lesson.lesson_date.isoformat(),
                "topic": lesson.topic,
                "grade": grade,
                "comment": record.comment if record else "",
                "status": (
                    "absent"
                    if is_absence_grade(grade)
                    else "attended"
                    if grade
                    else "unmarked"
                ),
            }
        )

    total_lessons = len(lessons)
    marked_lessons_count = len(records)
    unmarked_count = max(total_lessons - marked_lessons_count, 0)
    average_grade = round(sum(numeric_grades) / len(numeric_grades), 1) if numeric_grades else 0
    attendance_rate = round((attendance_count / total_lessons) * 100, 1) if total_lessons else  0

    mentor_user = student.group.mentor.user
    return {
        "student": {
            "id": student.pk,
            "user_id": student.user_id,
            "full_name": student.user.full_name,
            "username": student.user.username,
            "parent_name": student.parent_name,
            "parent_phone": str(student.parent_phone),
        },
        "group": {
            "id": student.group_id,
            "course_name": student.group.course_name,
            "study_days": student.group.study_days,
            "study_days_label": student.group.get_study_days_display(),
            "description": student.group.description,
        },
        "mentor": {
            "id": student.group.mentor_id,
            "full_name": mentor_user.full_name,
            "username": mentor_user.username,
            "email": mentor_user.email,
        },
        "period": {
            "month": month_start.strftime("%Y-%m"),
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat(),
            "last_lesson_date": trigger_date.isoformat() if trigger_date else None,
            "generated_at": timezone.now().isoformat(),
        },
        "summary": {
            "total_lessons": total_lessons,
            "marked_lessons_count": marked_lessons_count,
            "attendance_count": attendance_count,
            "absence_count": absence_count,
            "unmarked_count": unmarked_count,
            "attendance_rate": attendance_rate,
            "numeric_grades_count": len(numeric_grades),
            "average_grade": average_grade,
            "total_five": grade_totals["5"],
            "total_four": grade_totals["4"],
            "total_three": grade_totals["3"],
            "total_two": grade_totals["2"],
            "grades": [row["grade"] for row in lesson_rows if row["grade"]],
        },
        "lessons": lesson_rows,
    }


def build_dify_inputs(report_payload: dict[str, Any]) -> dict[str, Any]:
    summary = report_payload["summary"]
    return {
        "report": report_payload,
        "student_name": report_payload["student"]["full_name"],
        "recipient_name": report_payload["student"]["parent_name"] or report_payload["student"]["full_name"],
        "recipient_phone": report_payload["student"]["parent_phone"],
        "group_name": report_payload["group"]["course_name"],
        "mentor_name": report_payload["mentor"]["full_name"],
        "month": report_payload["period"]["month"],
        "average_grade": summary["average_grade"],
        "attendance_count": summary["attendance_count"],
        "absence_count": summary["absence_count"],
        "total_five": summary["total_five"],
        "total_four": summary["total_four"],
        "total_three": summary["total_three"],
        "total_two": summary["total_two"],
        "attendance_rate": summary["attendance_rate"],
    }


def get_dify_run_url() -> str:
    explicit_url = os.getenv("DIFY_WORKFLOW_RUN_URL", "").strip()
    if explicit_url:
        return explicit_url

    legacy_url = os.getenv("DIFY_API_URL", "").strip()
    if legacy_url:
        return legacy_url

    base_url = os.getenv("DIFY_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise ReportConfigurationError("DIFY_BASE_URL, DIFY_WORKFLOW_RUN_URL, or DIFY_API_URL must be configured.")
    return f"{base_url}/workflows/run"


def get_dify_user_agent() -> str:
    return os.getenv(
        "DIFY_USER_AGENT",
        "TabelBackend/1.0 (+https://tabel.local; Python urllib)",
    ).strip()


def run_dify_workflow(inputs: dict[str, Any], user_key: str) -> dict[str, Any]:
    api_key = os.getenv("DIFY_API_KEY", "").strip()
    if not api_key:
        raise ReportConfigurationError("DIFY_API_KEY must be configured.")

    response_mode = os.getenv("DIFY_RESPONSE_MODE", "blocking").strip() or "blocking"
    timeout_seconds = int(os.getenv("DIFY_TIMEOUT_SECONDS", "30"))
    url = get_dify_run_url()
    payload = {
        "inputs": inputs,
        "response_mode": response_mode,
        "user": user_key,
    }
    logger.info(
        "Sending report to Dify for student='%s', month='%s', recipient='%s', url='%s'",
        inputs.get("student_name", ""),
        inputs.get("month", ""),
        mask_phone(inputs.get("recipient_phone", "")),
        url,
    )
    encoded_payload = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=encoded_payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": get_dify_user_agent(),
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        logger.error(
            "Dify HTTP error for student='%s', month='%s': status=%s body=%s",
            inputs.get("student_name", ""),
            inputs.get("month", ""),
            exc.code,
            error_body,
        )
        raise ReportDeliveryError(f"Dify returned HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        logger.error(
            "Dify connection error for student='%s', month='%s': %s",
            inputs.get("student_name", ""),
            inputs.get("month", ""),
            exc.reason,
        )
        raise ReportDeliveryError(f"Could not reach Dify: {exc.reason}") from exc

    if not raw_body:
        logger.info(
            "Dify returned an empty body for student='%s', month='%s'",
            inputs.get("student_name", ""),
            inputs.get("month", ""),
        )
        return {}

    try:
        response_payload = json.loads(raw_body)
    except json.JSONDecodeError:
        response_payload = {"raw_response": raw_body}

    logger.info(
        "Dify response received for student='%s', month='%s', workflow_run_id='%s', status='%s'",
        inputs.get("student_name", ""),
        inputs.get("month", ""),
        response_payload.get("workflow_run_id") or response_payload.get("data", {}).get("id", ""),
        get_dify_workflow_status(response_payload),
    )
    return response_payload


def build_dispatch_user_key(student: StudentProfile, month_start: date) -> str:
    return f"report:{student.pk}:{month_start:%Y-%m}"


def send_student_month_report(
    student: StudentProfile,
    run_date: date | datetime | None = None,
    month_start: date | datetime | None = None,
    dry_run: bool = False,
    force: bool = False,
    bypass_schedule: bool = False,
    resend_succeeded: bool = False,
) -> dict[str, Any]:
    run_date = normalize_run_date(run_date)
    month_start = normalize_month_start(month_start or run_date)
    trigger_date = get_group_last_lesson_date(student.group, month_start)
    trigger_lesson = get_student_trigger_lesson(student, month_start)

    if trigger_date is None and not bypass_schedule:
        logger.info(
            "Skipping report for student='%s': no lessons in month='%s'",
            student.user.full_name,
            month_start.strftime("%Y-%m"),
        )
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "no_lessons_in_month",
        }

    if not bypass_schedule and run_date != trigger_date:
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "not_due_today",
            "trigger_date": trigger_date.isoformat(),
        }

    if not bypass_schedule and trigger_lesson is None:
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "trigger_lesson_not_created",
            "trigger_date": trigger_date.isoformat(),
        }

    if not bypass_schedule and not has_student_trigger_lesson_record(student, trigger_lesson):
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "trigger_lesson_not_marked",
            "trigger_date": trigger_date.isoformat(),
        }

    dispatch = MonthlyStudentReportDispatch.objects.filter(student=student, month=month_start).first()
    if (
        dispatch
        and dispatch.status == MonthlyStudentReportDispatch.STATUS_SUCCEEDED
        and not resend_succeeded
    ):
        logger.info(
            "Skipping report for student='%s': already sent for month='%s'",
            student.user.full_name,
            month_start.strftime("%Y-%m"),
        )
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "already_sent",
            "dispatch_id": dispatch.pk,
        }

    effective_trigger_date = trigger_date or run_date
    report_payload = build_student_month_report(
        student,
        month_start=month_start,
        trigger_date=effective_trigger_date,
    )

    if dry_run:
        logger.info(
            "Dry run report prepared for student='%s', month='%s'",
            student.user.full_name,
            month_start.strftime("%Y-%m"),
        )
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "dry_run",
            "trigger_date": trigger_date.isoformat(),
            "payload": report_payload,
        }

    try:
        with transaction.atomic():
            dispatch, _ = MonthlyStudentReportDispatch.objects.select_for_update().get_or_create(
                student=student,
                month=month_start,
                defaults={"trigger_date": effective_trigger_date},
            )

            if (
                dispatch.status == MonthlyStudentReportDispatch.STATUS_SUCCEEDED
                and not resend_succeeded
            ):
                return {
                    "student_id": student.pk,
                    "student_name": student.user.full_name,
                    "status": "skipped",
                    "reason": "already_sent",
                    "dispatch_id": dispatch.pk,
                }

            if (
                dispatch.status == MonthlyStudentReportDispatch.STATUS_PENDING
                and dispatch.attempts > 0
                and not force
            ):
                return {
                    "student_id": student.pk,
                    "student_name": student.user.full_name,
                    "status": "skipped",
                    "reason": "send_already_in_progress",
                    "dispatch_id": dispatch.pk,
                    "trigger_date": trigger_date.isoformat(),
                }

            dispatch.trigger_date = effective_trigger_date
            dispatch.status = MonthlyStudentReportDispatch.STATUS_PENDING
            dispatch.payload = report_payload
            dispatch.error_message = ""
            dispatch.response_payload = {}
            dispatch.workflow_run_id = ""
            dispatch.sent_at = None
            dispatch.attempts += 1
            dispatch.save()
            delivery_attempt = MonthlyStudentReportAttempt.objects.create(
                dispatch=dispatch,
                attempt_number=dispatch.attempts,
                status=MonthlyStudentReportDispatch.STATUS_PENDING,
                payload=report_payload,
            )
    except IntegrityError:
        dispatch = MonthlyStudentReportDispatch.objects.get(student=student, month=month_start)
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "send_already_in_progress",
            "dispatch_id": dispatch.pk,
            "trigger_date": trigger_date.isoformat(),
        }

    try:
        response_payload = run_dify_workflow(
            build_dify_inputs(report_payload),
            build_dispatch_user_key(student, month_start),
        )
    except Exception as exc:
        logger.error(
            "Report delivery failed for student='%s', month='%s': %s",
            student.user.full_name,
            month_start.strftime("%Y-%m"),
            exc,
        )
        dispatch.status = MonthlyStudentReportDispatch.STATUS_FAILED
        dispatch.error_message = str(exc)
        dispatch.save(
            update_fields=[
                "trigger_date",
                "status",
                "payload",
                "error_message",
                "response_payload",
                "workflow_run_id",
                "attempts",
                "updated_at",
            ]
        )
        delivery_attempt.status = dispatch.status
        delivery_attempt.error_message = dispatch.error_message
        delivery_attempt.save(update_fields=["status", "error_message", "updated_at"])
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "failed",
            "reason": str(exc),
            "dispatch_id": dispatch.pk,
        }

    dispatch.refresh_from_db()
    delivery_attempt.refresh_from_db()
    stored_response = dict(dispatch.response_payload) if isinstance(dispatch.response_payload, dict) else {}
    meta_result = stored_response.get("meta")
    if isinstance(meta_result, dict) and meta_result.get("callback_received"):
        stored_response["dify"] = response_payload
        dispatch.response_payload = stored_response
    else:
        workflow_status = get_dify_workflow_status(response_payload)
        workflow_failed = workflow_status in {"failed", "stopped"} or (
            workflow_status == "partial-succeeded" and not accepts_partial_dify_success()
        )
        dispatch.status = (
            MonthlyStudentReportDispatch.STATUS_FAILED
            if workflow_failed
            else MonthlyStudentReportDispatch.STATUS_SUCCEEDED
        )
        dispatch.response_payload = response_payload
        dispatch.error_message = (
            f"Dify workflow finished with status '{workflow_status}'."
            if workflow_failed
            else ""
        )
        dispatch.sent_at = None if workflow_failed else timezone.now()
    dispatch.workflow_run_id = (
        str(response_payload.get("workflow_run_id", ""))
        or str(response_payload.get("data", {}).get("id", ""))
    )
    dispatch.save(
        update_fields=[
            "trigger_date",
            "status",
            "payload",
            "response_payload",
            "workflow_run_id",
            "attempts",
            "sent_at",
            "error_message",
            "updated_at",
        ]
    )
    delivery_attempt.status = dispatch.status
    delivery_attempt.response_payload = dispatch.response_payload
    delivery_attempt.workflow_run_id = dispatch.workflow_run_id
    delivery_attempt.error_message = dispatch.error_message
    delivery_attempt.sent_at = dispatch.sent_at
    delivery_attempt.save(
        update_fields=[
            "status",
            "response_payload",
            "workflow_run_id",
            "error_message",
            "sent_at",
            "updated_at",
        ]
    )
    if dispatch.status == MonthlyStudentReportDispatch.STATUS_FAILED:
        logger.error(
            "Dify finished but Meta delivery failed for student='%s', month='%s', dispatch_id=%s",
            student.user.full_name,
            month_start.strftime("%Y-%m"),
            dispatch.pk,
        )
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "failed",
            "reason": dispatch.error_message,
            "dispatch_id": dispatch.pk,
            "workflow_run_id": dispatch.workflow_run_id,
        }
    logger.info(
        "Report sent successfully for student='%s', month='%s', dispatch_id=%s, workflow_run_id='%s'",
        student.user.full_name,
        month_start.strftime("%Y-%m"),
        dispatch.pk,
        dispatch.workflow_run_id,
    )
    return {
        "student_id": student.pk,
        "student_name": student.user.full_name,
        "status": "sent",
        "dispatch_id": dispatch.pk,
        "workflow_run_id": dispatch.workflow_run_id,
        "trigger_date": effective_trigger_date.isoformat(),
    }


def force_send_all_monthly_reports(
    run_date: date | datetime | None = None,
    month_start: date | datetime | None = None,
    organization_type: str | None = None,
) -> list[dict[str, Any]]:
    """Explicit admin action: send the selected month to every active student."""
    run_date = normalize_run_date(run_date)
    month_start = normalize_month_start(month_start or run_date)
    student_queryset = StudentProfile.objects.select_related("user", "group", "group__mentor__user").filter(archived_at__isnull=True)
    if organization_type:
        student_queryset = student_queryset.filter(organization_type=organization_type)
    students = list(
        student_queryset
        .order_by("group__course_name", "user__full_name")
    )

    results = []
    for student in students:
        result = send_student_month_report(
            student,
            run_date=run_date,
            month_start=month_start,
            force=True,
            bypass_schedule=True,
            resend_succeeded=True,
        )
        results.append(result)
    return results


def send_due_monthly_reports(
    run_date: date | datetime | None = None,
    month_start: date | datetime | None = None,
    student_id: int | None = None,
    group_id: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    organization_type: str | None = None,
) -> list[dict[str, Any]]:
    run_date = normalize_run_date(run_date)
    month_start = normalize_month_start(month_start or run_date)
    month_start, month_end = month_bounds(month_start)

    students = StudentProfile.objects.select_related(
        "user",
        "group",
        "group__mentor__user",
    ).filter(
        archived_at__isnull=True,
        group__lessons__lesson_date__gte=month_start,
        group__lessons__lesson_date__lte=month_end,
    ).distinct()
    if organization_type:
        students = students.filter(organization_type=organization_type)

    if student_id is not None:
        students = students.filter(pk=student_id)
    if group_id is not None:
        students = students.filter(group_id=group_id)

    results = []
    ordered_students = list(students.order_by("group__course_name", "user__full_name"))
    for index, student in enumerate(ordered_students):
        result = send_student_month_report(
            student,
            run_date=run_date,
            month_start=month_start,
            dry_run=dry_run,
            force=force,
        )
        results.append(result)
        if result["status"] in REPORT_DISPATCH_DELAY_STATUSES and index < len(ordered_students) - 1:
            time.sleep(REPORT_DISPATCH_DELAY_SECONDS)
    return results
