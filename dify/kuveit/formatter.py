import json
import re
from datetime import datetime


TEMPLATE_NAME = "student_monthsly_send_v5"
THREE_SUBJECT_NOTE = "Бул отчетто 3 сабак бар; төртүнчү орундагы «—» сабак жок экенин билдирет."


MONTH_NAMES = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}


def safe_text(value, default="—"):
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return value


def grade_count(value):
    """Keep missing grade data distinct from an explicit count of zero."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректное количество оценок.") from exc
    if not number.is_integer() or number < 0:
        raise ValueError("Некорректное количество оценок.")
    return int(number)


def parse_date(value):
    try:
        return datetime.strptime(
            str(value)[:10],
            "%Y-%m-%d"
        ).date()
    except (TypeError, ValueError):
        return None


def collect_absence_dates(report, subjects):
    """
    Собираем даты одновременно из:
    1. report.absence_dates
    2. subjects[].absence_dates

    Это важно, потому что в показанном JSON
    общий absence_dates не содержит июньские даты.
    """

    raw_dates = []

    raw_dates.extend(
        report.get("absence_dates") or []
    )

    for subject in subjects:
        raw_dates.extend(
            subject.get("absence_dates") or []
        )

    parsed_dates = []

    for value in raw_dates:
        parsed = parse_date(value)

        if parsed is not None:
            parsed_dates.append(parsed)

    # Удаляем дубликаты и сортируем
    return sorted(set(parsed_dates))


def format_absence_text(absence_dates):
    """
    Получаем:

    17-18-19-20-26-28-май жана
    2-3-4-июнь күндөрү сабактан калган
    """

    if not absence_dates:
        return "Отчёттук мезгилде сабактан калган жок"

    dates_by_month = {}

    for absence_date in absence_dates:
        key = (
            absence_date.year,
            absence_date.month
        )

        dates_by_month.setdefault(
            key,
            []
        ).append(absence_date.day)

    month_parts = []

    for (_, month_number), days in dates_by_month.items():
        days_text = "-".join(
            str(day)
            for day in sorted(set(days))
        )

        month_name = MONTH_NAMES.get(
            month_number,
            str(month_number)
        )

        month_parts.append(
            f"{days_text}-{month_name}"
        )

    if len(month_parts) == 1:
        dates_text = month_parts[0]
    else:
        dates_text = (
            ", ".join(month_parts[:-1])
            + " жана "
            + month_parts[-1]
        )

    return (
        f"{dates_text} күндөрү "
        f"сабактан калган"
    )


def format_period(report, absence_dates):
    """
    Сначала пытаемся взять период из backend.

    Если периода нет, определяем его
    по минимальной и максимальной дате пропуска.
    """

    period = report.get("period") or {}

    explicit_label = (
        report.get("period_label")
        or period.get("period_label")
        or period.get("label")
    )

    if explicit_label:
        return safe_text(explicit_label)

    month_start = (
        period.get("month_start")
        or period.get("start")
    )

    month_end = (
        period.get("month_end")
        or period.get("end")
    )

    start_date = parse_date(month_start)
    end_date = parse_date(month_end)

    if start_date and end_date:
        start_month = MONTH_NAMES.get(
            start_date.month,
            str(start_date.month)
        )

        end_month = MONTH_NAMES.get(
            end_date.month,
            str(end_date.month)
        )

        if (
            start_date.year == end_date.year
            and start_date.month == end_date.month
        ):
            return start_month

        return f"{start_month}–{end_month}"

    raw_month = (
        report.get("month")
        or period.get("month")
        or ""
    )

    match = re.fullmatch(
        r"(\d{4})-(\d{2})",
        str(raw_month).strip()
    )

    if match:
        month_number = int(match.group(2))

        return MONTH_NAMES.get(
            month_number,
            str(raw_month)
        )

    # Резервный вариант:
    # определяем период по датам пропусков
    if absence_dates:
        first_date = absence_dates[0]
        last_date = absence_dates[-1]

        first_month = MONTH_NAMES.get(
            first_date.month,
            str(first_date.month)
        )

        last_month = MONTH_NAMES.get(
            last_date.month,
            str(last_date.month)
        )

        if (
            first_date.year == last_date.year
            and first_date.month == last_date.month
        ):
            return first_month

        return f"{first_month}–{last_month}"

    raise ValueError(
        "Не удалось определить период отчёта. "
        "Backend должен передать report.period "
        "или report.period_label."
    )


def main(report: dict = None) -> dict:
    report = report or {}

    student = report.get("student") or {}
    main_group = report.get("main_group") or {}
    subjects = report.get("subjects") or []

    # -----------------------------
    # 1. Основные данные
    # -----------------------------

    student_name = safe_text(
        student.get("full_name"),
        ""
    )

    recipient_name = safe_text(
        student.get("parent_name"),
        ""
    )

    recipient_phone = (
        student.get("parent_phone")
        or ""
    )

    main_group_name = safe_text(
        main_group.get("name"),
        ""
    )

    clean_phone = "".join(
        re.findall(
            r"\d",
            str(recipient_phone)
        )
    )

    if not student_name:
        raise ValueError(
            "В report.student отсутствует full_name."
        )

    if not clean_phone:
        raise ValueError(
            "В report.student отсутствует parent_phone."
        )

    if not main_group_name:
        raise ValueError(
            "В report.main_group отсутствует name."
        )

    # -----------------------------
    # 2. Проверяем число предметов, не обрезая назначенные предметы
    # -----------------------------

    if not isinstance(subjects, list):
        raise ValueError(
            "report.subjects должен быть массивом."
        )

    if not 1 <= len(subjects) <= 4:
        raise ValueError(
            "Шаблон Meta рассчитан на 1–4 предмета, "
            f"получено: {len(subjects)}."
        )

    # -----------------------------
    # 3. Готовим статистику
    # -----------------------------

    course_statistics = []

    for subject in subjects:
        grade_counts = (
            subject.get("grade_counts")
            or {}
        )

        course_statistics.append({
            "group_id": subject.get("group_id"),

            "course_name": safe_text(
                subject.get("name"),
                "Предмет көрсөтүлгөн эмес"
            ),

            "total_five": grade_count(
                grade_counts.get("5")
            ),

            "total_four": grade_count(
                grade_counts.get("4")
            ),

            "total_three": grade_count(
                grade_counts.get("3")
            ),

            "total_two": grade_count(
                grade_counts.get("2")
            ),

            "absence_dates": (
                subject.get("absence_dates")
                or []
            )
        })

    # -----------------------------
    # 4. Пропуски и период
    # -----------------------------

    absence_dates = collect_absence_dates(
        report=report,
        subjects=subjects
    )

    absence_text = format_absence_text(
        absence_dates
    )
    template_absence_text = absence_text
    if len(course_statistics) == 3:
        template_absence_text = f"{absence_text}\n{THREE_SUBJECT_NOTE}"

    period_text = format_period(
        report=report,
        absence_dates=absence_dates
    )

    # -----------------------------
    # 5. Создаём 24 переменные Meta
    # -----------------------------

    template_values = [
        main_group_name,   # {{1}}
        student_name,      # {{2}}
        period_text,       # {{3}}
    ]

    for course in course_statistics:
        template_values.extend([
            course["course_name"],
            str(course["total_five"]),
            str(course["total_four"]),
            str(course["total_three"]),
            str(course["total_two"])
        ])

    # Незанятый слот шаблона не представляет предмет и не содержит оценок.
    # Все пять параметров такого слота явно обозначаем как отсутствующие.
    for _ in range(4 - len(course_statistics)):
        template_values.extend(["—", "—", "—", "—", "—"])

    # Последняя переменная
    template_values.append(
        template_absence_text
    )                      # {{24}}

    if len(template_values) != 24:
        raise ValueError(
            "Ошибка формирования Meta-параметров: "
            f"ожидалось 24, получено "
            f"{len(template_values)}."
        )

    # -----------------------------
    # 6. Payload для Meta
    # -----------------------------

    whatsapp_payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {
                "code": "ky_KG"
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            # Meta template parameters must be a single line.
                            # Normalize after the absence note is appended.
                            "text": " ".join(safe_text(value).split())
                        }
                        for value in template_values
                    ]
                }
            ]
        }
    }

    # -----------------------------
    # 7. Payload для backend-лога
    # -----------------------------

    backend_payload = {
        "event": "student_monthly_report_sent",
        "channel": "meta_whatsapp",

        "student": {
            "id": student.get("id"),
            "user_id": student.get("user_id"),
            "full_name": student_name,
            "username": student.get("username")
        },

        "main_group": {
            "id": main_group.get("id"),
            "name": main_group_name
        },

        "recipient_name": recipient_name,
        "recipient_phone": clean_phone,

        "period_text": period_text,

        "course_statistics": course_statistics,

        "absence_dates": [
            value.isoformat()
            for value in absence_dates
        ],

        "absence_text": absence_text,

        "report": report,
        "meta_request": whatsapp_payload
    }

    return {
        "clean_phone": clean_phone,
        "student_name": student_name,
        "main_group_name": main_group_name,
        "period_text": period_text,
        "subjects_count": len(course_statistics),
        "absence_text": absence_text,

        "whatsapp_payload": json.dumps(
            whatsapp_payload,
            ensure_ascii=False
        ),

        "backend_payload": json.dumps(
            backend_payload,
            ensure_ascii=False
        )
    }
