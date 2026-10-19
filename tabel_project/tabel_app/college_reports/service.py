"""Monthly report entry points restricted to college students."""

from typing import Any

from tabel_app.models import ORGANIZATION_COLLEGE, StudentProfile
from tabel_app.report import (
    force_send_all_monthly_reports,
    send_due_monthly_reports,
    send_student_month_report,
)


def _is_college_student(student: StudentProfile) -> bool:
    return (
        student.organization_type == ORGANIZATION_COLLEGE
        and student.group.organization_type == ORGANIZATION_COLLEGE
    )


def send_college_student_month_report(
    student: StudentProfile,
    **kwargs: Any,
) -> dict[str, Any]:
    """Apply the standard monthly-report rules to one college student."""
    if not _is_college_student(student):
        return {
            "student_id": student.pk,
            "student_name": student.user.full_name,
            "status": "skipped",
            "reason": "not_college_student",
        }
    return send_student_month_report(student, **kwargs)


def force_send_all_college_monthly_reports(**kwargs: Any) -> list[dict[str, Any]]:
    """Run the standard admin report action for active college students only."""
    return force_send_all_monthly_reports(
        organization_type=ORGANIZATION_COLLEGE,
        **kwargs,
    )


def send_due_college_monthly_reports(**kwargs: Any) -> list[dict[str, Any]]:
    """Send reports that are due for active college students only."""
    return send_due_monthly_reports(
        organization_type=ORGANIZATION_COLLEGE,
        **kwargs,
    )
