from datetime import date, datetime, timedelta
from mimetypes import guess_type
from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Group, Lesson, LessonRecord, MentorProfile, StudentProfile, User
from .serializers import (
    GroupDetailSerializer,
    GroupListSerializer,
    GroupWriteSerializer,
    LessonSerializer,
    LoginSerializer,
    MentorProfileSerializer,
    StudentProfileSerializer,
    UserSerializer,
)


FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def groups_for_user(user):
    queryset = Group.objects.select_related("mentor__user").prefetch_related("students__user", "lessons")
    if user.role == User.ROLE_ADMIN:
        return queryset
    if user.role == User.ROLE_MENTOR and hasattr(user, "mentor_profile"):
        return queryset.filter(mentor=user.mentor_profile)
    if user.role == User.ROLE_STUDENT and hasattr(user, "student_profile"):
        return queryset.filter(pk=user.student_profile.group_id)
    return queryset.none()


def students_for_user(user):
    queryset = StudentProfile.objects.select_related("user", "group", "group__mentor__user")
    if user.role == User.ROLE_ADMIN:
        return queryset
    if user.role == User.ROLE_MENTOR and hasattr(user, "mentor_profile"):
        return queryset.filter(group__mentor=user.mentor_profile)
    if user.role == User.ROLE_STUDENT and hasattr(user, "student_profile"):
        return queryset.filter(pk=user.student_profile.pk)
    return queryset.none()


def lessons_for_user(user):
    queryset = Lesson.objects.select_related("group", "group__mentor__user").prefetch_related("records__student__user")
    if user.role == User.ROLE_ADMIN:
        return queryset
    if user.role == User.ROLE_MENTOR and hasattr(user, "mentor_profile"):
        return queryset.filter(group__mentor=user.mentor_profile)
    if user.role == User.ROLE_STUDENT and hasattr(user, "student_profile"):
        return queryset.filter(group=user.student_profile.group)
    return queryset.none()


def manageable_groups_for_user(user):
    if user.role == User.ROLE_ADMIN:
        return Group.objects.select_related("mentor__user")
    if user.role == User.ROLE_MENTOR and hasattr(user, "mentor_profile"):
        return Group.objects.select_related("mentor__user").filter(mentor=user.mentor_profile)
    return Group.objects.none()


def get_manageable_group(user, group_id):
    return get_object_or_404(manageable_groups_for_user(user), pk=group_id)


def build_student_average(records):
    numeric_grades = [int(record.grade) for record in records if record.grade.isdigit()]
    if not numeric_grades:
        return None
    return round(sum(numeric_grades) / len(numeric_grades), 1)


def parse_month_value(month_value):
    if not month_value:
        return None

    try:
        return datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
    except ValueError:
        return None


def get_selected_month(request):
    return parse_month_value(request.GET.get("month")) or timezone.localdate().replace(day=1)


def month_bounds(current_month):
    next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return current_month, next_month - timedelta(days=1)


def month_navigation(current_month):
    previous_month = (current_month - timedelta(days=1)).replace(day=1)
    next_month = (current_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return previous_month, next_month


def build_month_days(current_month):
    month_start, month_end = month_bounds(current_month)
    days_total = (month_end - month_start).days + 1
    return [month_start + timedelta(days=offset) for offset in range(days_total)]


def get_group_study_weekdays(group):
    if group.study_days == Group.MON_WED_SAT:
        return {0, 2, 5}
    if group.study_days == Group.TUE_THU_SUN:
        return {1, 3, 6}
    return set()


def grade_tone(grade):
    return {
        "5": "excellent",
        "4": "good",
        "3": "warning",
        "2": "danger",
        "Н": "absence",
        "н": "absence",
    }.get(grade, "empty")


def build_gradebook_rows(group, students, month_days, lessons_by_date):
    lesson_ids = [lesson.pk for lesson in lessons_by_date.values()]
    student_ids = [student.pk for student in students]
    records = LessonRecord.objects.filter(
        lesson_id__in=lesson_ids,
        student_id__in=student_ids,
    ).select_related("lesson", "student__user")
    record_map = {(record.student_id, record.lesson.lesson_date): record for record in records}
    study_weekdays = get_group_study_weekdays(group)
    rows = []

    for index, student in enumerate(students, start=1):
        numeric_grades = []
        attendance_count = 0
        cells = []
        for day in month_days:
            lesson = lessons_by_date.get(day)
            record = record_map.get((student.pk, day))
            grade = record.grade if record else ""
            if grade.isdigit():
                numeric_grades.append(int(grade))
            if grade and grade not in {"Рќ", "РЅ"}:
                attendance_count += 1
            cells.append(
                {
                    "date": day,
                    "lesson": lesson,
                    "record": record,
                    "grade": grade,
                    "tone": grade_tone(grade),
                    "is_today": day == timezone.localdate(),
                    "is_weekend": day.weekday() >= 5,
                    "is_study_day": day.weekday() in study_weekdays,
                }
            )

        total_points = sum(numeric_grades) if numeric_grades else None
        average_grade = round(total_points / len(numeric_grades), 1) if numeric_grades else None
        rows.append(
            {
                "index": index,
                "student": student,
                "cells": cells,
                "filled_count": len(numeric_grades),
                "attendance_count": attendance_count,
                "total_points": total_points,
                "average_grade": average_grade,
            }
        )

    return rows


def serialize_choice_pairs(choices):
    return [{"value": value, "label": label} for value, label in choices]


def build_gradebook_payload(group, user, selected_month):
    can_edit = user.role in {User.ROLE_ADMIN, User.ROLE_MENTOR}
    previous_month, next_month = month_navigation(selected_month)
    month_days = build_month_days(selected_month)
    month_start, month_end = month_bounds(selected_month)
    study_weekdays = get_group_study_weekdays(group)

    if can_edit:
        students = list(group.students.select_related("user"))
    elif hasattr(user, "student_profile") and user.student_profile.group_id == group.pk:
        students = [user.student_profile]
    else:
        raise PermissionDenied

    lessons_by_date = {}
    for lesson in (
        group.lessons.filter(lesson_date__gte=month_start, lesson_date__lte=month_end)
        .order_by("lesson_date", "id")
    ):
        lessons_by_date.setdefault(lesson.lesson_date, lesson)

    month_columns = [
        {
            "date": day.isoformat(),
            "label": f"{day.day:02d}",
            "weekday_label": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()],
            "is_weekend": day.weekday() >= 5,
            "is_today": day == timezone.localdate(),
            "is_study_day": day.weekday() in study_weekdays,
            "has_lesson": day in lessons_by_date,
        }
        for day in month_days
    ]

    rows = build_gradebook_rows(group, students, month_days, lessons_by_date)
    serialized_rows = []
    for row in rows:
        serialized_rows.append(
            {
                "index": row["index"],
                "student": {
                    "id": row["student"].pk,
                    "user_id": row["student"].user_id,
                    "full_name": row["student"].user.full_name,
                    "parent_name": row["student"].parent_name,
                    "group_id": row["student"].group_id,
                },
                "filled_count": row["filled_count"],
                "attendance_count": row["attendance_count"],
                "total_points": row["total_points"],
                "average_grade": row["average_grade"],
                "cells": [
                    {
                        "date": cell["date"].isoformat(),
                        "grade": cell["grade"],
                        "tone": cell["tone"],
                        "lesson_id": cell["lesson"].pk if cell["lesson"] else None,
                        "is_today": cell["is_today"],
                        "is_weekend": cell["is_weekend"],
                        "is_study_day": cell["is_study_day"],
                    }
                    for cell in row["cells"]
                ],
            }
        )

    payload = {
        "group": GroupListSerializer(group).data,
        "month_value": f"{selected_month:%Y-%m}",
        "previous_month_value": f"{previous_month:%Y-%m}",
        "next_month_value": f"{next_month:%Y-%m}",
        "month_columns": month_columns,
        "rows": serialized_rows,
        "grade_choices": serialize_choice_pairs(LessonRecord.GRADE_CHOICES),
        "can_edit": can_edit,
        "student_only": not can_edit,
        "filled_days_count": len(lessons_by_date),
        "page_title": "Табель группы" if can_edit else "Мой табель",
        "page_copy": (
            "Весь месяц открыт сразу: ставьте оценки на любые даты прямо в матрице."
            if can_edit
            else "Вы видите только свои оценки за выбранный месяц."
        ),
    }
    return payload, students, month_days, lessons_by_date


def save_gradebook_entries(group, students, month_days, lessons_by_date, entries):
    valid_grades = {choice[0] for choice in LessonRecord.GRADE_CHOICES}
    allowed_dates = set(month_days)
    students_by_id = {student.pk: student for student in students}
    grades_map = {}

    for entry in entries:
        student_id = entry.get("student")
        raw_date = entry.get("date")
        grade = str(entry.get("grade", "")).strip()

        if student_id not in students_by_id:
            raise ValidationError({"entries": "Передан студент вне выбранной группы."})

        try:
            lesson_date = date.fromisoformat(raw_date)
        except (TypeError, ValueError):
            raise ValidationError({"entries": "Одна из дат табеля имеет неверный формат."}) from None

        if lesson_date not in allowed_dates:
            raise ValidationError({"entries": "Одна из дат не входит в выбранный месяц."})

        if grade and grade not in valid_grades:
            raise ValidationError({"entries": f"Недопустимая оценка: {grade}"})

        if grade:
            grades_map[(student_id, lesson_date)] = grade

    lesson_ids = [lesson.pk for lesson in lessons_by_date.values()]
    student_ids = list(students_by_id)
    existing_records = {
        (record.student_id, record.lesson.lesson_date): record
        for record in LessonRecord.objects.filter(lesson_id__in=lesson_ids, student_id__in=student_ids)
        .select_related("lesson")
    }

    for day in month_days:
        lesson = lessons_by_date.get(day)
        day_has_any_grade = False

        for student in students:
            grade = grades_map.get((student.pk, day), "")
            current_record = existing_records.get((student.pk, day))

            if grade:
                day_has_any_grade = True
                if lesson is None:
                    lesson = Lesson.objects.create(group=group, lesson_date=day)
                    lessons_by_date[day] = lesson
                defaults = {"grade": grade}
                if current_record:
                    defaults["comment"] = current_record.comment
                LessonRecord.objects.update_or_create(
                    student=student,
                    lesson=lesson,
                    defaults=defaults,
                )
            elif current_record:
                current_record.delete()

        if lesson and not day_has_any_grade and not lesson.topic and not lesson.records.exists():
            lesson.delete()
            lessons_by_date.pop(day, None)


def build_dashboard_payload(user):
    if user.role == User.ROLE_ADMIN:
        groups = groups_for_user(user).annotate(students_count=Count("students"))
        mentors = MentorProfile.objects.select_related("user").annotate(groups_count=Count("groups"))
        students = students_for_user(user)
        lessons = lessons_for_user(user)
        return {
            "dashboard_title": "Панель администратора",
            "dashboard_copy": "Управляйте группами, менторами, студентами и следите за учебным потоком.",
            "summary_cards": [
                {"label": "Группы", "value": groups.count(), "tone": "teal"},
                {"label": "Менторы", "value": mentors.count(), "tone": "orange"},
                {"label": "Студенты", "value": students.count(), "tone": "blue"},
                {"label": "Уроки", "value": lessons.count(), "tone": "sand"},
            ],
            "groups": GroupListSerializer(groups[:6], many=True).data,
            "mentors": MentorProfileSerializer(mentors[:6], many=True).data,
            "students": StudentProfileSerializer(students[:8], many=True).data,
            "recent_lessons": LessonSerializer(lessons[:8], many=True).data,
        }

    if user.role == User.ROLE_MENTOR and hasattr(user, "mentor_profile"):
        groups = groups_for_user(user).annotate(students_count=Count("students"))
        students = students_for_user(user)
        lessons = lessons_for_user(user)
        return {
            "dashboard_title": "Кабинет ментора",
            "dashboard_copy": "Следите за своими группами и сразу переходите к месячному табелю.",
            "summary_cards": [
                {"label": "Мои группы", "value": groups.count(), "tone": "teal"},
                {"label": "Мои студенты", "value": students.count(), "tone": "orange"},
                {"label": "Уроки", "value": lessons.count(), "tone": "blue"},
            ],
            "groups": GroupListSerializer(groups[:6], many=True).data,
            "students": StudentProfileSerializer(students[:8], many=True).data,
            "recent_lessons": LessonSerializer(lessons[:8], many=True).data,
        }

    student_profile = getattr(user, "student_profile", None)
    records = (
        LessonRecord.objects.select_related("lesson", "lesson__group")
        .filter(student=student_profile)
        .order_by("-lesson__lesson_date")
        if student_profile
        else LessonRecord.objects.none()
    )
    grades_count = records.count()
    attendance_count = records.exclude(grade="Н").exclude(grade="н").count()
    average_grade = build_student_average(records) or "—"
    group_name = student_profile.group.course_name if student_profile else "Не назначена"
    mentor_name = student_profile.group.mentor.user.full_name if student_profile else "Не назначен"
    return {
        "dashboard_title": "Кабинет студента",
        "dashboard_copy": "Здесь собрана короткая сводка по вашей группе, ментору и текущей успеваемости.",
        "summary_cards": [
            {"label": "Оценок", "value": grades_count, "tone": "orange"},
            {"label": "Посещений", "value": attendance_count, "tone": "teal"},
            {"label": "Средний балл", "value": average_grade, "tone": "blue"},
        ],
        "student_overview": {
            "group_name": group_name,
            "mentor_name": mentor_name,
            "grades_count": grades_count,
            "attendance_count": attendance_count,
            "average_grade": average_grade,
        },
    }


def frontend_app_view(request, path=""):
    requested_path = (path or "").lstrip("/")
    if requested_path:
        candidate_path = (FRONTEND_DIST_DIR / requested_path).resolve()
        if FRONTEND_DIST_DIR.resolve() not in candidate_path.parents and candidate_path != FRONTEND_DIST_DIR.resolve():
            raise Http404
        if candidate_path.exists() and candidate_path.is_file():
            content_type, _ = guess_type(candidate_path.name)
            return FileResponse(candidate_path.open("rb"), content_type=content_type or "application/octet-stream")
        if requested_path.startswith("assets/") or "." in Path(requested_path).name:
            raise Http404

    index_path = FRONTEND_DIST_DIR / "index.html"
    if not index_path.exists():
        return HttpResponse(
            "React build not found. Run 'cd d:\\Tabel\\frontend && npm run build' first.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    return FileResponse(index_path.open("rb"), content_type="text/html; charset=utf-8")


class ApiRootAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        return Response(
            {
                "name": "Tabel API",
                "backend": "Django REST Framework",
                "frontend": "React app is located in /frontend",
                "api_base": "/api/",
                "auth": {
                    "login": "/api/auth/login/",
                    "refresh": "/api/auth/refresh/",
                    "logout": "/api/auth/logout/",
                },
            }
        )


class CustomLoginView(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutAPIView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"detail": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response(status=status.HTTP_205_RESET_CONTENT)


class CurrentUserAPIView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class DashboardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(build_dashboard_payload(request.user))


class AppMetaAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(
            {
                "study_day_choices": serialize_choice_pairs(Group.STUDY_DAYS_CHOICES),
                "grade_choices": serialize_choice_pairs(LessonRecord.GRADE_CHOICES),
            }
        )


class MentorProfileViewSet(viewsets.ModelViewSet):
    serializer_class = MentorProfileSerializer

    def get_queryset(self):
        queryset = MentorProfile.objects.select_related("user").annotate(groups_count=Count("groups"))
        if self.request.user.role == User.ROLE_ADMIN:
            return queryset
        if self.request.user.role == User.ROLE_MENTOR and hasattr(self.request.user, "mentor_profile"):
            return queryset.filter(pk=self.request.user.mentor_profile.pk)
        return queryset.none()

    def create(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        instance = self.get_object()
        instance.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentProfileViewSet(viewsets.ModelViewSet):
    serializer_class = StudentProfileSerializer

    def get_queryset(self):
        return students_for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        instance = self.get_object()
        instance.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return groups_for_user(self.request.user).annotate(students_count=Count("students"))

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return GroupWriteSerializer
        if self.action == "retrieve":
            return GroupDetailSerializer
        return GroupListSerializer

    def create(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != User.ROLE_ADMIN:
            raise PermissionDenied
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get", "post"])
    def gradebook(self, request, pk=None):
        group = self.get_object()

        if request.method == "GET":
            selected_month = get_selected_month(request)
            payload, _, _, _ = build_gradebook_payload(group, request.user, selected_month)
            return Response(payload)

        if request.user.role not in {User.ROLE_ADMIN, User.ROLE_MENTOR}:
            raise PermissionDenied

        selected_month = parse_month_value(request.data.get("month"))
        if selected_month is None:
            raise ValidationError({"month": "Неверный формат месяца. Используйте YYYY-MM."})

        entries = request.data.get("entries", [])
        if not isinstance(entries, list):
            raise ValidationError({"entries": "Список оценок должен быть массивом."})

        _, students, month_days, lessons_by_date = build_gradebook_payload(group, request.user, selected_month)
        save_gradebook_entries(group, students, month_days, lessons_by_date, entries)
        payload, _, _, _ = build_gradebook_payload(group, request.user, selected_month)
        return Response(payload, status=status.HTTP_200_OK)


class LessonViewSet(viewsets.ModelViewSet):
    serializer_class = LessonSerializer

    def get_queryset(self):
        return lessons_for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        if request.user.role not in {User.ROLE_ADMIN, User.ROLE_MENTOR}:
            raise PermissionDenied
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = serializer.validated_data["group"]
        get_manageable_group(request.user, group.pk)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        if request.user.role not in {User.ROLE_ADMIN, User.ROLE_MENTOR}:
            raise PermissionDenied
        return self._update_lesson(request, partial=False)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role not in {User.ROLE_ADMIN, User.ROLE_MENTOR}:
            raise PermissionDenied
        return self._update_lesson(request, partial=True)

    def destroy(self, request, *args, **kwargs):
        if request.user.role not in {User.ROLE_ADMIN, User.ROLE_MENTOR}:
            raise PermissionDenied
        lesson = self.get_object()
        get_manageable_group(request.user, lesson.group_id)
        return super().destroy(request, *args, **kwargs)

    def _update_lesson(self, request, partial):
        lesson = self.get_object()
        get_manageable_group(request.user, lesson.group_id)
        serializer = self.get_serializer(lesson, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        group = serializer.validated_data.get("group", lesson.group)
        get_manageable_group(request.user, group.pk)
        self.perform_update(serializer)
        return Response(serializer.data)
