from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any
from urllib import error, request

from django.utils import timezone

from .models import Group, Lesson, LessonRecord, MonthlyStudentReportDispatch, StudentProfile


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


class ReportConfigurationError(Exception):
    pass


class ReportDeliveryError(Exception):
    pass


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


def get_group_last_lesson_date(group: Group, month_start: date) -> date | None:
    month_start, month_end = month_bounds(month_start)
    return (
        group.lessons.filter(lesson_date__gte=month_start, lesson_date__lte=month_end)
        .order_by("-lesson_date", "-id")
        .values_list("lesson_date", flat=True)
        .first()
    )


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
            "total_absence": grade_totals["Н"],
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
        "total_absence": summary["total_absence"],
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
        inputs.get("recipient_phone", ""),
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
        "Dify response for student='%s', month='%s': %s",
        inputs.get("student_name", ""),
        inputs.get("month", ""),
        response_payload,
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
) -> dict[str, Any]:
    run_date = normalize_run_date(run_date)
    month_start = normalize_month_start(month_start or run_date)
    trigger_date = get_group_last_lesson_date(student.group, month_start)

    if trigger_date is None:
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

    if not force and run_date != trigger_date:
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "not_due_today",
            "trigger_date": trigger_date.isoformat(),
        }

    dispatch = MonthlyStudentReportDispatch.objects.filter(student=student, month=month_start).first()
    if dispatch and dispatch.status == MonthlyStudentReportDispatch.STATUS_SUCCEEDED and not force:
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

    report_payload = build_student_month_report(student, month_start=month_start, trigger_date=trigger_date)

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

    if dispatch is None:
        dispatch = MonthlyStudentReportDispatch(student=student, month=month_start)

    dispatch.trigger_date = trigger_date
    dispatch.status = MonthlyStudentReportDispatch.STATUS_PENDING
    dispatch.payload = report_payload
    dispatch.error_message = ""
    dispatch.response_payload = {}
    dispatch.workflow_run_id = ""
    dispatch.attempts += 1
    dispatch.save()

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
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "failed",
            "reason": str(exc),
            "dispatch_id": dispatch.pk,
        }

    dispatch.status = MonthlyStudentReportDispatch.STATUS_SUCCEEDED
    dispatch.response_payload = response_payload
    dispatch.workflow_run_id = (
        str(response_payload.get("workflow_run_id", ""))
        or str(response_payload.get("data", {}).get("id", ""))
    )
    dispatch.sent_at = timezone.now()
    dispatch.save(
        update_fields=[
            "trigger_date",
            "status",
            "payload",
            "response_payload",
            "workflow_run_id",
            "attempts",
            "sent_at",
            "updated_at",
        ]
    )
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
        "trigger_date": trigger_date.isoformat(),
    }


def send_due_monthly_reports(
    run_date: date | datetime | None = None,
    month_start: date | datetime | None = None,
    student_id: int | None = None,
    group_id: int | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> list[dict[str, Any]]:
    run_date = normalize_run_date(run_date)
    month_start = normalize_month_start(month_start or run_date)
    month_start, month_end = month_bounds(month_start)

    students = StudentProfile.objects.select_related(
        "user",
        "group",
        "group__mentor__user",
    ).filter(
        group__lessons__lesson_date__gte=month_start,
        group__lessons__lesson_date__lte=month_end,
    ).distinct()

    if student_id is not None:
        students = students.filter(pk=student_id)
    if group_id is not None:
        students = students.filter(group_id=group_id)

    results = []
    for student in students.order_by("group__course_name", "user__full_name"):
        results.append(
            send_student_month_report(
                student,
                run_date=run_date,
                month_start=month_start,
                dry_run=dry_run,
                force=force,
            )
        )
    return results
