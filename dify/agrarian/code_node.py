"""Pure, local formatter proposal for the existing agrarian report JSON contract."""

import json
import re
from collections import Counter
from datetime import date

MONTHS = ("", "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
BODY = "Саламатсызбы!\n\n{{1}} студентинин {{2}} тобу боюнча {{3}} айындагы окуу отчёту.\n\nПредметтер жана баалар: {{4}}\n\nКатышуу: {{5}}"
BODY_LIMIT = 1024
SUBJECT_LIMIT = 12


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _required(value, field):
    result = normalize(value)
    if not result:
        raise ValueError(f"Missing {field}")
    return result


def calculate(report):
    """Classify each unique lesson and count every numeric LessonRecord."""
    if not isinstance(report, dict) or (report.get("organization"), report.get("college_branch"), report.get("workflow_route")) != ("college", "agrarian", "agrarian"):
        raise ValueError("Wrong report route")
    period = report["period"]
    month = _required(period["month"], "period.month")
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise ValueError("Invalid period.month") from exc
    groups = report["groups"]
    if not isinstance(groups, list) or not groups:
        raise ValueError("Missing subject groups")
    subjects = []
    by_group = {}
    for group in groups:
        group_id = group["id"]
        if group_id in by_group:
            raise ValueError("Duplicate subject group")
        item = {"group_id": group_id, "name": _required(group["course_name"], "course_name"), "grades": Counter(), "lessons": Counter(), "lesson_details": []}
        subjects.append(item)
        by_group[group_id] = item
    by_lesson = {}
    for row in report["lessons"]:
        lesson_id, group_id = row["lesson_id"], row["group_id"]
        if group_id not in by_group:
            raise ValueError("Lesson outside subject groups")
        day = date.fromisoformat(row["date"])
        if day.year != start.year or day.month != start.month:
            raise ValueError("Lesson outside period")
        key = (group_id, lesson_id)
        lesson = by_lesson.setdefault(key, {"lesson_id": lesson_id, "group_id": group_id, "date": day.isoformat(), "grades": []})
        if lesson["date"] != day.isoformat():
            raise ValueError("Conflicting lesson date")
        grade = normalize(row["grade"])
        if grade and grade not in ("2", "3", "4", "5", "Н"):
            raise ValueError("Unsupported grade")
        if grade:
            lesson["grades"].append(grade)
    totals = Counter()
    for lesson in sorted(by_lesson.values(), key=lambda item: (item["date"], str(item["group_id"]), str(item["lesson_id"]))):
        numeric = [grade for grade in lesson["grades"] if grade in ("2", "3", "4", "5")]
        absent = "Н" in lesson["grades"]
        category = "mixed" if numeric and absent else "graded" if numeric else "absent" if absent else "unmarked"
        subject = by_group[lesson["group_id"]]
        subject["grades"].update(numeric)
        subject["lessons"][category] += 1
        subject["lesson_details"].append({"lesson_id": lesson["lesson_id"], "date": lesson["date"], "category": category, "grades": lesson["grades"]})
        totals[category] += 1
    return {"month": month, "student_name": _required(report["student"]["full_name"], "student.full_name"), "group_name": _required(report["main_group"].get("name") or report["group"]["course_name"], "group name"), "subjects": subjects, "lessons": totals}


def render_meta(calculation):
    """Present calculated data in five single-line parameters; fail closed on overflow."""
    subjects = calculation["subjects"]
    if len(subjects) > SUBJECT_LIMIT:
        raise ValueError("Subject capacity exceeded")
    month = date.fromisoformat(calculation["month"] + "-01")
    subject_parts = []
    for subject in subjects:
        counts = subject["grades"]
        if counts:
            grades = ", ".join(f"{grade}: {counts[grade]}" for grade in ("5", "4", "3", "2") if counts[grade])
        else:
            grades = "баа коюлган эмес"
        subject_parts.append(f"{subject['name']} — {grades}")
    lessons = calculation["lessons"]
    attendance = "; ".join((
        f"бааланып катышкан сабактар {lessons['graded']}",
        f"сабактан калгандар {lessons['absent']}",
        f"аралаш белгилер (баа жана Н) {lessons['mixed']}",
        f"белгиленбеген сабактар {lessons['unmarked']}",
    ))
    params = [calculation["student_name"], calculation["group_name"], f"{month.year}-жылдын {MONTHS[month.month]}", "; ".join(subject_parts), attendance]
    params = [normalize(value) for value in params]
    if any(not value for value in params):
        raise ValueError("Empty Meta parameter")
    preview = BODY
    for index, value in enumerate(params, 1):
        preview = preview.replace("{{" + str(index) + "}}", value)
    if len(preview) > BODY_LIMIT:
        raise ValueError("Meta BODY capacity exceeded")
    return {"parameters": params, "preview": preview, "characters": len(preview)}


def format_report(report):
    if isinstance(report, str):
        report = json.loads(report)
    return render_meta(calculate(report))


# Dify Code node entry point. The source above is embedded, not imported.
TEMPLATE_NAME = "AGRARIAN_TEMPLATE_NOT_CREATED"

def main(report, student_name="", recipient_name="", recipient_phone="", group_name="", month="", send_enabled="false"):
    if str(send_enabled).strip().lower() != "true":
        raise ValueError("AGRARIAN_SEND_ENABLED=false: no external HTTP request is allowed")
    if isinstance(report, str):
        report = json.loads(report)
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object")
    for label, supplied, expected in (
        ("student_name", student_name, report["student"]["full_name"]),
        ("recipient_phone", recipient_phone, report["student"]["parent_phone"]),
        ("month", month, report["period"]["month"]),
    ):
        if normalize(supplied) != normalize(expected):
            raise ValueError(label + " differs from report")
    expected_group = report.get("main_group", {}).get("name") or report["group"]["course_name"]
    if normalize(group_name) != normalize(expected_group):
        raise ValueError("group_name differs from report")
    phone = "".join(char for char in normalize(recipient_phone) if char.isdigit())
    if not 8 <= len(phone) <= 15:
        raise ValueError("Invalid recipient_phone")
    calculated = calculate(report)
    rendered = render_meta(calculated)
    whatsapp = {
        "messaging_product": "whatsapp", "to": phone, "type": "template",
        "template": {"name": TEMPLATE_NAME, "language": {"code": "ky_KG"},
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": value} for value in rendered["parameters"]
            ]}]},
    }
    backend = {
        "event": "student_monthly_report_result", "channel": "meta_whatsapp",
        "report": report, "meta_request": whatsapp,
        "rendered_text": rendered["preview"],
    }
    return {
        "whatsapp_payload": json.dumps(whatsapp, ensure_ascii=False),
        "backend_payload": json.dumps(backend, ensure_ascii=False),
        **{"parameter_" + str(index): value for index, value in enumerate(rendered["parameters"], 1)},
    }
