"""Student leaderboard ("Рейтинг").

Points accumulate per grade record: good grades (5, 4) immediately move a
student up the ladder, while 3, 2 and absences pull them down. Each organization
scope is ranked separately: academy students only compete with academy
students, and each college branch (agrarian / kuwait) has its own ladder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from django.utils import timezone

from .models import ORGANIZATION_COLLEGE, COLLEGE_BRANCH_CHOICES, LessonRecord, StudentProfile
from .report import is_absence_grade, month_bounds

# 5 and 4 move a student up; 3, 2 and absences move them down.
GRADE_POINTS = {"5": 5, "4": 4, "3": -1, "2": -2}
ABSENCE_PENALTY = -3
RATING_LIMIT = 100

PERIOD_MONTH = "month"
PERIOD_ALL = "all"
VALID_PERIODS = {PERIOD_MONTH, PERIOD_ALL}

MONTH_NAMES = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)


def grade_points(grade: str | None) -> int:
    normalized = (grade or "").strip()
    if is_absence_grade(normalized):
        return ABSENCE_PENALTY
    return GRADE_POINTS.get(normalized, 0)


@dataclass
class _Score:
    points: int = 0
    grades: list[int] = field(default_factory=list)
    absences: int = 0

    def add(self, grade: str) -> None:
        normalized = (grade or "").strip()
        self.points += grade_points(normalized)
        if is_absence_grade(normalized):
            self.absences += 1
        elif normalized.isdigit():
            self.grades.append(int(normalized))

    @property
    def average(self) -> float | None:
        marked = len(self.grades) + self.absences
        if not marked:
            return None
        return round(sum(self.grades) / marked, 1)


def _sort_key(student: StudentProfile, score: _Score):
    average = score.average
    return (
        -score.points,
        -(average if average is not None else -1),
        score.absences,
        (student.user.full_name or student.user.username).lower(),
        student.pk,
    )


def _rank(students: list[StudentProfile], scores: dict[int, _Score]) -> list[StudentProfile]:
    return sorted(students, key=lambda student: _sort_key(student, scores[student.pk]))


def _group_label(student: StudentProfile) -> str:
    group = student.group
    if group.main_group_id:
        return group.main_group.name
    return group.course_name


def scope_label(organization_type: str, college_branch: str | None) -> str:
    if organization_type == ORGANIZATION_COLLEGE:
        return dict(COLLEGE_BRANCH_CHOICES).get(college_branch, "Колледж")
    return "Академия"


def build_student_rating(
    student: StudentProfile,
    organization_type: str,
    college_branch: str | None,
    period: str = PERIOD_MONTH,
    today: date | None = None,
) -> dict:
    today = today or timezone.localdate()
    if period not in VALID_PERIODS:
        period = PERIOD_MONTH

    participants_queryset = StudentProfile.objects.filter(
        organization_type=organization_type,
        archived_at__isnull=True,
        group__archived_at__isnull=True,
        user__is_active=True,
    ).select_related("user", "group", "group__main_group")
    records_queryset = LessonRecord.objects.filter(
        student__organization_type=organization_type,
        student__archived_at__isnull=True,
        lesson__group__organization_type=organization_type,
    )
    if organization_type == ORGANIZATION_COLLEGE:
        participants_queryset = participants_queryset.filter(college_branch=college_branch)
        records_queryset = records_queryset.filter(
            student__college_branch=college_branch,
            lesson__group__college_branch=college_branch,
        )

    if period == PERIOD_MONTH:
        month_start, month_end = month_bounds(today.replace(day=1))
        records_queryset = records_queryset.filter(lesson__lesson_date__range=(month_start, month_end))
        period_label = f"{MONTH_NAMES[today.month - 1]} {today.year}"
    else:
        period_label = "За всё время"

    participants = list(participants_queryset)
    current_scores = {participant.pk: _Score() for participant in participants}
    previous_scores = {participant.pk: _Score() for participant in participants}
    # Grades recorded before today form "yesterday's" ladder, used for the ↑/↓ movement.
    day_start = timezone.make_aware(datetime.combine(today, time.min))

    for student_id, grade, created_at in records_queryset.values_list("student_id", "grade", "created_at"):
        if student_id not in current_scores:
            continue
        current_scores[student_id].add(grade)
        if created_at < day_start:
            previous_scores[student_id].add(grade)

    ranking = _rank(participants, current_scores)
    previous_positions = {
        participant.pk: position
        for position, participant in enumerate(_rank(participants, previous_scores), start=1)
    }

    def serialize(position: int, participant: StudentProfile) -> dict:
        score = current_scores[participant.pk]
        return {
            "rank": position,
            "rank_change": previous_positions[participant.pk] - position,
            "full_name": participant.user.full_name or participant.user.username,
            "group_name": _group_label(participant),
            "points": score.points,
            "grades_count": len(score.grades),
            "absences_count": score.absences,
            "average_grade": score.average,
            "is_me": participant.pk == student.pk,
        }

    top = [serialize(position, participant) for position, participant in enumerate(ranking[:RATING_LIMIT], start=1)]
    me = next(
        (serialize(position, participant) for position, participant in enumerate(ranking, start=1) if participant.pk == student.pk),
        None,
    )

    return {
        "period": period,
        "period_label": period_label,
        "scope_label": scope_label(organization_type, college_branch),
        "participants_count": len(participants),
        "scoring": {
            "grades": [{"grade": grade, "points": points} for grade, points in GRADE_POINTS.items()],
            "absence": ABSENCE_PENALTY,
        },
        "top": top,
        "me": me,
    }
