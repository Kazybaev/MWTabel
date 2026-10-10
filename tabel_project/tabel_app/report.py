from __future__ import annotations
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib import error, request

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MonthlyStudentReportAttempt,
    MonthlyStudentReportDispatch,
    ORGANIZATION_ACADEMY,
    ORGANIZATION_COLLEGE,
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
REPORT_DISPATCH_DELAY_STATUSES = {"sent", "failed", "pending"}


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


def get_report_destination(organization_type: str) -> str:
    if organization_type == ORGANIZATION_ACADEMY:
        return "kuwait"
    if organization_type == ORGANIZATION_COLLEGE:
        return "agrarian"
    raise ReportConfigurationError("Unknown report organization.")


def get_dify_setting(name: str, organization_type: str, default: str = "") -> str:
    destination = get_report_destination(organization_type).upper()
    scoped = os.getenv(f"DIFY_{destination}_{name}", "").strip()
    if scoped:
        return scoped
    # Only Kuwait keeps the original integration. Agrarian must never use its key.
    if organization_type == ORGANIZATION_ACADEMY:
        return os.getenv(f"DIFY_{name}", default).strip()
    return default


def get_report_callback_token(organization_type: str) -> str:
    destination = get_report_destination(organization_type).upper()
    token = os.getenv(f"BACKEND_{destination}_REPORT_CALLBACK_TOKEN", "").strip()
    if token or organization_type == ORGANIZATION_COLLEGE:
        return token
    return os.getenv("BACKEND_REPORT_CALLBACK_TOKEN", "").strip()


def accepts_partial_dify_success(organization_type: str = ORGANIZATION_ACADEMY) -> bool:
    return get_dify_setting("ACCEPT_PARTIAL_SUCCESS", organization_type, "False").lower() in {
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


def get_group_last_lesson_date(group: Group, month_start: date) -> date | None:
    month_start, month_end = month_bounds(month_start)
    return (
        group.lessons.filter(lesson_date__gte=month_start, lesson_date__lte=month_end)
        .order_by("-lesson_date", "-id")
        .values_list("lesson_date", flat=True)
        .first()
    )


def get_student_report_groups(student: StudentProfile):
    scope = Q(pk=student.group_id)
    if student.organization_type == ORGANIZATION_COLLEGE:
        scope |= Q(college_students=student)
    return Group.objects.filter(
        scope, organization_type=student.organization_type,
    ).select_related("mentor__user").distinct().order_by("course_name", "pk")


def get_student_trigger_lesson(student: StudentProfile, month_start: date) -> Lesson | None:
    month_start, month_end = month_bounds(month_start)
    return (
        Lesson.objects.filter(
            group__in=get_student_report_groups(student),
            lesson_date__range=(month_start, month_end),
        )
        .order_by("-lesson_date", "-id")
        .first()
    )


def has_student_trigger_lesson_record(student: StudentProfile, trigger_lesson: Lesson) -> bool:
    return LessonRecord.objects.filter(
        student=student, lesson=trigger_lesson,
        grade__in=[grade for grade, _ in LessonRecord.GRADE_CHOICES],
    ).exists()


def get_month_lessons_for_student(student: StudentProfile, month_start: date) -> list[Lesson]:
    month_start, month_end = month_bounds(month_start)
    return list(
        Lesson.objects.filter(
            group__in=get_student_report_groups(student),
            lesson_date__gte=month_start,
            lesson_date__lte=month_end,
        ).select_related("group__mentor__user").order_by("lesson_date", "id")
    )


def get_month_records_for_student(student: StudentProfile, month_start: date) -> list[LessonRecord]:
    month_start, month_end = month_bounds(month_start)
    return list(
        LessonRecord.objects.filter(
            student=student,
            lesson__group__in=get_student_report_groups(student),
            lesson__lesson_date__gte=month_start,
            lesson__lesson_date__lte=month_end,
        )
        .select_related("lesson")
        .order_by("lesson__lesson_date", "lesson_id")
    )


def summarize_report_lessons(lessons: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_grades = [int(row["grade"]) for row in lessons if row["grade"] in {"2", "3", "4", "5"}]
    attendance_count = sum(row["status"] == "attended" for row in lessons)
    absence_count = sum(row["status"] == "absent" for row in lessons)
    marked_count = attendance_count + absence_count
    return {
        "total_lessons": len(lessons),
        "marked_lessons_count": marked_count,
        "attendance_count": attendance_count,
        "absence_count": absence_count,
        "unmarked_count": len(lessons) - marked_count,
        "attendance_rate": round(attendance_count / len(lessons) * 100, 1) if lessons else 0,
        "numeric_grades_count": len(numeric_grades),
        "average_grade": round(sum(numeric_grades) / len(numeric_grades), 1) if numeric_grades else 0,
        **{key: sum(row["grade"] == grade for row in lessons) for grade, key in (
            ("5", "total_five"), ("4", "total_four"), ("3", "total_three"), ("2", "total_two"),
        )},
        "grades": [row["grade"] for row in lessons if row["grade"]],
    }


def build_multisubject_month_report(
    student: StudentProfile,
    month_start: date | datetime | None = None,
    trigger_date: date | None = None,
) -> dict[str, Any]:
    month_start, month_end = month_bounds(normalize_month_start(month_start))
    groups = list(get_student_report_groups(student))
    lessons = get_month_lessons_for_student(student, month_start)
    records = {record.lesson_id: record for record in get_month_records_for_student(student, month_start)}
    trigger_date = trigger_date or (lessons[-1].lesson_date if lessons else None)
    valid_grades = {grade for grade, _ in LessonRecord.GRADE_CHOICES}
    lesson_rows = []
    for lesson in lessons:
        record = records.get(lesson.pk)
        grade = (record.grade or "").strip() if record else ""
        if grade not in valid_grades:
            grade = ""
        lesson_rows.append({
            "lesson_id": lesson.pk,
            "group_id": lesson.group_id,
            "subject": lesson.group.course_name,
            "date": lesson.lesson_date.isoformat(),
            "topic": lesson.topic,
            "grade": grade,
            "comment": record.comment if record else "",
            "status": "absent" if is_absence_grade(grade) else "attended" if grade else "unmarked",
        })

    subjects = []
    for group in groups:
        subject_lessons = [row for row in lesson_rows if row["group_id"] == group.pk]
        subjects.append({
            "group_id": group.pk,
            "subject": group.course_name,
            "mentor": {"id": group.mentor_id, "full_name": group.mentor.user.full_name},
            "last_lesson_date": subject_lessons[-1]["date"] if subject_lessons else None,
            "summary": summarize_report_lessons(subject_lessons),
            "lessons": subject_lessons,
        })
    mentor_user = student.group.mentor.user
    return {
        "organization_type": student.organization_type,
        "student": {
            "id": student.pk,
            "user_id": student.user_id,
            "full_name": student.user.full_name,
            "username": student.user.username,
            "parent_name": student.parent_name,
            "parent_phone": str(student.parent_phone),
            "college_course": student.college_course,
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
        "summary": summarize_report_lessons(lesson_rows),
        "subjects": subjects,
        "lessons": lesson_rows,
    }


def build_student_month_report(
    student: StudentProfile,
    month_start: date | datetime | None = None,
    trigger_date: date | None = None,
) -> dict[str, Any]:
    if student.organization_type == ORGANIZATION_COLLEGE:
        from .college_reports.payload import build_agrarian_month_report
        return build_agrarian_month_report(student, month_start, trigger_date)
    if student.organization_type == ORGANIZATION_ACADEMY:
        from .kuwait_reports import build_kuwait_month_report
        return build_kuwait_month_report(student, month_start, trigger_date)
    raise ReportConfigurationError("Unknown report organization.")


def build_legacy_dify_inputs(report_payload: dict[str, Any]) -> dict[str, Any]:
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


def build_dify_inputs(report_payload: dict[str, Any]) -> dict[str, Any]:
    if report_payload.get("organization_type") == ORGANIZATION_COLLEGE:
        from .college_reports.payload import build_agrarian_dify_inputs
        return build_agrarian_dify_inputs(report_payload)
    from .kuwait_reports import build_kuwait_dify_inputs
    return build_kuwait_dify_inputs(report_payload)


def get_dify_run_url(organization_type: str = ORGANIZATION_ACADEMY) -> str:
    destination = get_report_destination(organization_type).upper()
    scoped_url = (
        os.getenv(f"DIFY_{destination}_WORKFLOW_RUN_URL", "").strip()
        or os.getenv(f"DIFY_{destination}_API_URL", "").strip()
    )
    if scoped_url:
        return scoped_url
    scoped_base = os.getenv(f"DIFY_{destination}_BASE_URL", "").strip().rstrip("/")
    if scoped_base:
        return f"{scoped_base}/workflows/run"
    if organization_type == ORGANIZATION_COLLEGE:
        raise ReportConfigurationError("DIFY_AGRARIAN_BASE_URL or DIFY_AGRARIAN_WORKFLOW_RUN_URL must be configured.")
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
    organization_type = inputs.get("report", {}).get("organization_type", ORGANIZATION_ACADEMY)
    api_key = get_dify_setting("API_KEY", organization_type)
    if not api_key:
        key_name = "DIFY_AGRARIAN_API_KEY" if organization_type == ORGANIZATION_COLLEGE else "DIFY_KUWAIT_API_KEY or DIFY_API_KEY"
        raise ReportConfigurationError(f"{key_name} must be configured.")

    response_mode = get_dify_setting("RESPONSE_MODE", organization_type, "blocking") or "blocking"
    timeout_seconds = int(get_dify_setting("TIMEOUT_SECONDS", organization_type, "30"))
    url = get_dify_run_url(organization_type)
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
) -> dict[str, Any]:
    # The legacy force argument never bypasses schedule, success, or an active attempt.
    run_date = normalize_run_date(run_date)
    month_start = normalize_month_start(month_start or run_date)
    base_result = {"student_id": student.pk, "student_name": student.user.full_name}
    if student.archived_at is not None or not student.user.is_active:
        return {**base_result, "status": "skipped", "reason": "inactive_student"}
    trigger_lesson = get_student_trigger_lesson(student, month_start)
    if trigger_lesson is None:
        return {**base_result, "status": "skipped", "reason": "no_lessons_in_month"}
    trigger_date = trigger_lesson.lesson_date
    base_result["trigger_date"] = trigger_date.isoformat()
    if run_date != trigger_date:
        return {**base_result, "status": "skipped", "reason": "not_due_today"}

    lessons = get_month_lessons_for_student(student, month_start)
    last_by_group = {lesson.group_id: lesson for lesson in lessons}
    missing_groups = [group_id for group_id, lesson in last_by_group.items()
                      if not has_student_trigger_lesson_record(student, lesson)]
    if missing_groups:
        return {**base_result, "status": "skipped", "reason": "trigger_lesson_not_marked",
                "unmarked_group_ids": missing_groups}

    report_payload = build_student_month_report(student, month_start, trigger_date)
    if dry_run:
        return {**base_result, "status": "dry_run", "payload": report_payload}

    try:
        with transaction.atomic():
            # Serialize even the first dispatch for a student on PostgreSQL.
            StudentProfile.objects.select_for_update().get(pk=student.pk)
            dispatch, _ = MonthlyStudentReportDispatch.objects.select_for_update().get_or_create(
                student=student, month=month_start, defaults={"trigger_date": trigger_date},
            )
            if dispatch.status == MonthlyStudentReportDispatch.STATUS_SUCCEEDED:
                return {**base_result, "status": "skipped", "reason": "already_sent", "dispatch_id": dispatch.pk}
            if dispatch.status == MonthlyStudentReportDispatch.STATUS_PENDING and dispatch.attempts > 0:
                return {**base_result, "status": "skipped", "reason": "send_already_in_progress", "dispatch_id": dispatch.pk}
            dispatch.trigger_date = trigger_date
            dispatch.status = MonthlyStudentReportDispatch.STATUS_PENDING
            dispatch.attempts += 1
            report_payload["dispatch"] = {"id": dispatch.pk, "attempt_number": dispatch.attempts}
            dispatch.payload = report_payload
            dispatch.error_message = ""
            dispatch.response_payload = {}
            dispatch.workflow_run_id = ""
            dispatch.sent_at = None
            dispatch.save()
            delivery_attempt = MonthlyStudentReportAttempt.objects.create(
                dispatch=dispatch, attempt_number=dispatch.attempts,
                status=dispatch.status, payload=report_payload,
            )
    except IntegrityError:
        dispatch = MonthlyStudentReportDispatch.objects.get(student=student, month=month_start)
        return {**base_result, "status": "skipped", "reason": "send_already_in_progress", "dispatch_id": dispatch.pk}

    delivery_error = ""
    try:
        response_payload = run_dify_workflow(build_dify_inputs(report_payload), build_dispatch_user_key(student, month_start))
    except Exception as exc:
        logger.exception("Report attempt failed: student_id=%s month=%s", student.pk, month_start)
        delivery_error = str(exc)
        response_payload = {}

    # A callback can arrive while the HTTP request is running. Preserve its result
    # and lock the dispatch until both the dispatch and attempt are updated.
    with transaction.atomic():
        dispatch = MonthlyStudentReportDispatch.objects.select_for_update().get(pk=dispatch.pk)
        stored_response = dict(dispatch.response_payload) if isinstance(dispatch.response_payload, dict) else {}
        meta = stored_response.get("meta")
        if isinstance(meta, dict) and meta.get("callback_received"):
            stored_response["dify"] = response_payload
            if delivery_error:
                stored_response["workflow_error"] = delivery_error
            dispatch.response_payload = stored_response
        else:
            workflow_status = get_dify_workflow_status(response_payload)
            workflow_failed = workflow_status in {"failed", "stopped"} or (
                workflow_status == "partial-succeeded" and not accepts_partial_dify_success(student.organization_type)
            )
            dispatch.status = MonthlyStudentReportDispatch.STATUS_FAILED if delivery_error or workflow_failed else MonthlyStudentReportDispatch.STATUS_PENDING
            dispatch.response_payload = response_payload
            dispatch.error_message = delivery_error or (
                f"Workflow finished with status '{workflow_status}'." if workflow_failed else ""
            )
            # Completion of the workflow alone does not confirm a message to the parent.
            dispatch.sent_at = None
        data = response_payload.get("data")
        dispatch.workflow_run_id = str(response_payload.get("workflow_run_id") or (
            data.get("id", "") if isinstance(data, dict) else ""
        ))
        dispatch.save(update_fields=["status", "response_payload", "workflow_run_id", "sent_at", "error_message", "updated_at"])
        delivery_attempt.status = dispatch.status
        delivery_attempt.response_payload = dispatch.response_payload
        delivery_attempt.workflow_run_id = dispatch.workflow_run_id
        delivery_attempt.error_message = dispatch.error_message
        delivery_attempt.sent_at = dispatch.sent_at
        delivery_attempt.save(update_fields=["status", "response_payload", "workflow_run_id", "error_message", "sent_at", "updated_at"])

    result = {**base_result, "dispatch_id": dispatch.pk, "workflow_run_id": dispatch.workflow_run_id}
    if dispatch.status == MonthlyStudentReportDispatch.STATUS_FAILED:
        return {**result, "status": "failed", "reason": dispatch.error_message}
    if dispatch.status == MonthlyStudentReportDispatch.STATUS_PENDING:
        return {**result, "status": "pending", "reason": "awaiting_delivery_confirmation"}
    logger.info("Report confirmed: student_id=%s month=%s dispatch_id=%s", student.pk, month_start, dispatch.pk)
    return {**result, "status": "sent"}


def force_send_all_monthly_reports(
    run_date: date | datetime | None = None,
    month_start: date | datetime | None = None,
    organization_type: str | None = None,
) -> list[dict[str, Any]]:
    """Admin action using the same schedule and duplicate protection as individual sends."""
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
            force=False,
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

    students = StudentProfile.objects.select_related(
        "user",
        "group",
        "group__mentor__user",
    ).filter(
        archived_at__isnull=True,
    ).filter(user__is_active=True).distinct()
    if organization_type:
        students = students.filter(organization_type=organization_type)

    if student_id is not None:
        students = students.filter(pk=student_id)
    if group_id is not None:
        students = students.filter(Q(group_id=group_id) | Q(organization_type=ORGANIZATION_COLLEGE, college_groups__id=group_id)).distinct()

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
