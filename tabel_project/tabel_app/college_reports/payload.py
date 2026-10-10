"""Agrarian college: all assigned subjects and all lesson marks in one report."""

from tabel_app.models import ORGANIZATION_COLLEGE


def build_agrarian_month_report(student, month_start=None, trigger_date=None):
    if student.organization_type != ORGANIZATION_COLLEGE or student.group.organization_type != ORGANIZATION_COLLEGE:
        raise ValueError("Agrarian reports only accept college students.")
    from tabel_app.report import build_multisubject_month_report
    return build_multisubject_month_report(student, month_start, trigger_date)


def build_agrarian_dify_inputs(report_payload):
    from tabel_app.report import build_legacy_dify_inputs
    if report_payload.get("organization_type") != "college":
        raise ValueError("Agrarian Dify inputs require a college report.")
    return {
        **build_legacy_dify_inputs(report_payload),
        "report_type": "agrarian_monthly_v1",
        "organization_type": "college",
        "college_course": report_payload["student"]["college_course"],
        "subjects_count": len(report_payload["subjects"]),
        "subjects": report_payload["subjects"],
        "summary": report_payload["summary"],
    }
