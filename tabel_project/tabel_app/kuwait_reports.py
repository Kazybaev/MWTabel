"""Kuwait: original single-group report and original Dify input contract."""

from copy import deepcopy

from .models import ORGANIZATION_ACADEMY


def build_kuwait_month_report(student, month_start=None, trigger_date=None):
    if student.organization_type != ORGANIZATION_ACADEMY:
        raise ValueError("Kuwait reports only accept academy students.")
    from .report import build_multisubject_month_report
    report = build_multisubject_month_report(student, month_start, trigger_date)
    report.pop("organization_type")
    report.pop("subjects")
    report["student"].pop("college_course")
    for lesson in report["lessons"]:
        lesson.pop("group_id")
        lesson.pop("subject")
    return report


def build_kuwait_dify_inputs(report_payload):
    from .report import build_legacy_dify_inputs
    if report_payload.get("organization_type", ORGANIZATION_ACADEMY) != ORGANIZATION_ACADEMY:
        raise ValueError("Kuwait Dify inputs cannot contain another organization's report.")
    # Internal attempt metadata must not change the old workflow's JSON schema.
    report = deepcopy(report_payload)
    report.pop("dispatch", None)
    return build_legacy_dify_inputs(report)


def send_kuwait_student_month_report(student, **kwargs):
    from .report import send_student_month_report
    if student.organization_type != ORGANIZATION_ACADEMY:
        return {"student_id": student.pk, "student_name": student.user.full_name,
                "status": "skipped", "reason": "not_kuwait_student"}
    return send_student_month_report(student, **kwargs)


def send_due_kuwait_monthly_reports(**kwargs):
    from .report import send_due_monthly_reports
    return send_due_monthly_reports(organization_type=ORGANIZATION_ACADEMY, **kwargs)


def send_all_kuwait_monthly_reports(**kwargs):
    from .report import force_send_all_monthly_reports
    return force_send_all_monthly_reports(organization_type=ORGANIZATION_ACADEMY, **kwargs)
