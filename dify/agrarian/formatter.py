"""Pure, local formatter proposal for the existing agrarian report JSON contract."""

import json
import re
from collections import Counter
from datetime import date

MONTHS = ("", "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
BODY = 'Саламатсызбы!\n\nМен Motion Web IT академиясынан байланышып жатам ✅\n\nСизге *{{1}}* группасынын окуучусу *{{2}}* боюнча {{3}} мезгилиндеги окуу жыйынтыктары тууралуу маалымат бере кетейин:\n\n📊 Сабактар боюнча баалары:\n\n• *{{4}}* сабагы —\n\n“5”тен {{5}} даана\n“4”төн {{6}} даана\n“3”төн {{7}} даана\n“2”ден {{8}} даана\n\n• *{{9}}* сабагы —\n\n“5”тен {{10}} даана\n“4”төн {{11}} даана\n“3”төн {{12}} даана\n“2”ден {{13}} даана\n\n• *{{14}}* сабагы —\n\n“5”тен {{15}} даана\n“4”төн {{16}} даана\n“3”төн {{17}} даана\n“2”ден {{18}} даана\n\n• *{{19}}* сабагы —\n\n“5”тен {{20}} даана\n“4”төн {{21}} даана\n“3”төн {{22}} даана\n“2”ден {{23}} даана\n\n📌 Сабактан калуулар:\n\n• {{24}}\n\nСаламатта калыныз!\n'
BODY_LIMIT = 1024
SUBJECT_LIMIT = 4


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
    """Render the exact Kuwait BODY with 24 single-line parameters."""
    subjects = calculation["subjects"]
    if len(subjects) > SUBJECT_LIMIT:
        raise ValueError("Subject capacity exceeded: template has four subject blocks")
    month = date.fromisoformat(calculation["month"] + "-01")
    params = [calculation["group_name"], calculation["student_name"], f"{month.year}-жылдын {MONTHS[month.month]}"]
    for subject in subjects:
        counts = subject["grades"]
        params.extend([subject["name"], *(str(counts[grade]) for grade in ("5", "4", "3", "2"))])
    for _ in range(SUBJECT_LIMIT - len(subjects)):
        params.extend(["—"] * 5)
    lessons = calculation["lessons"]
    params.append("; ".join((
        f"Н гана белгиленген сабактар: {lessons['absent']}",
        f"аралаш белгилер (баа жана Н, пропуск катары эсептелбейт): {lessons['mixed']}",
        f"белгиленбеген сабактар (пропуск катары эсептелбейт): {lessons['unmarked']}",
        "— менен толтурулган предмет блоктору: бул орунда предмет жок" if len(subjects) < SUBJECT_LIMIT else "бардык предметтер көрсөтүлдү",
    )))
    params = [normalize(value) for value in params]
    if len(params) != 24 or any(not value for value in params):
        raise ValueError("Invalid Meta parameter count or empty value")
    preview = BODY
    for index, value in enumerate(params, 1):
        preview = preview.replace("{{" + str(index) + "}}", value)
    if len(preview) > BODY_LIMIT:
        raise ValueError("Meta BODY capacity exceeded")
    return {"parameters": params, "preview": preview, "characters": len(preview), "snapshot": calculation}


def main(report):
    if isinstance(report, str):
        report = json.loads(report)
    return render_meta(calculate(report))
