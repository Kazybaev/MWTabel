from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Tabel", {"fields": ("full_name", "role")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Tabel", {"fields": ("full_name", "role")}),
    )
    list_display = ("username", "full_name", "role", "is_staff", "is_active")
    search_fields = ("username", "full_name", "email")


@admin.register(MentorProfile)
class MentorProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user")
    search_fields = ("user__full_name", "user__username")


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "group", "parent_name")
    search_fields = ("user__full_name", "user__username", "parent_name")
    list_filter = ("group",)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("course_name", "mentor", "study_days")
    search_fields = ("course_name", "mentor__user__full_name")
    list_filter = ("study_days",)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("group", "lesson_date", "topic")
    search_fields = ("group__course_name", "topic")
    list_filter = ("lesson_date",)


@admin.register(LessonRecord)
class LessonRecordAdmin(admin.ModelAdmin):
    list_display = ("lesson", "student", "grade")
    search_fields = ("student__user__full_name", "lesson__group__course_name", "grade")
    list_filter = ("grade",)


@admin.register(MonthlyStudentReportDispatch)
class MonthlyStudentReportDispatchAdmin(admin.ModelAdmin):
    list_display = ("student", "month", "trigger_date", "status", "attempts", "sent_at")
    search_fields = ("student__user__full_name", "student__user__username", "workflow_run_id")
    list_filter = ("status", "month", "trigger_date")
    readonly_fields = (
        "student",
        "month",
        "trigger_date",
        "status",
        "attempts",
        "sent_at",
        "workflow_run_id",
        "payload",
        "response_payload",
        "error_message",
        "created_at",
        "updated_at",
    )
