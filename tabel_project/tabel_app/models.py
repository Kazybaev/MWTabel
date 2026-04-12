from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField


class User(AbstractUser):
    ROLE_ADMIN = "ADMIN"
    ROLE_MENTOR = "MENTOR"
    ROLE_STUDENT = "STUDENT"
    ROLE_CHOICES = (
        (ROLE_ADMIN, "Admin"),
        (ROLE_MENTOR, "Mentor"),
        (ROLE_STUDENT, "Student"),
    )

    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_STUDENT)

    class Meta:
        ordering = ("full_name", "username")

    def save(self, *args, **kwargs):
        if self.role == self.ROLE_ADMIN:
            self.is_staff = True
        if self.full_name and not self.first_name:
            name_parts = self.full_name.split(maxsplit=1)
            self.first_name = name_parts[0]
            self.last_name = name_parts[1] if len(name_parts) > 1 else ""
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name or self.username


class MentorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mentor_profile",
    )

    class Meta:
        ordering = ("user__full_name",)

    def __str__(self):
        return self.user.full_name


class Group(models.Model):
    MON_WED_SAT = "MON_WED_SAT"
    TUE_THU_SUN = "TUE_THU_SUN"
    STUDY_DAYS_CHOICES = (
        (MON_WED_SAT, "Пн • Ср • Сб"),
        (TUE_THU_SUN, "Вт • Чт • Вс"),
    )

    course_name = models.CharField(max_length=100)
    mentor = models.ForeignKey(MentorProfile, on_delete=models.CASCADE, related_name="groups")
    study_days = models.CharField(max_length=32, choices=STUDY_DAYS_CHOICES)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("course_name",)

    def __str__(self):
        return self.course_name


class StudentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_profile",
    )
    parent_name = models.CharField(max_length=100)
    parent_phone = PhoneNumberField()
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="students")

    class Meta:
        ordering = ("user__full_name",)

    def __str__(self):
        return self.user.full_name


class Lesson(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons")
    lesson_date = models.DateField(default=timezone.localdate)
    topic = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ("-lesson_date", "group__course_name")

    def __str__(self):
        topic = f" - {self.topic}" if self.topic else ""
        return f"{self.group.course_name} ({self.lesson_date}){topic}"


class LessonRecord(models.Model):
    GRADE_CHOICES = (
        ("5", "5"),
        ("4", "4"),
        ("3", "3"),
        ("2", "2"),
        ("Н", "Н"),
    )

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="lesson_records")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="records")
    grade = models.CharField(max_length=2, choices=GRADE_CHOICES)
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("student__user__full_name",)
        unique_together = ("student", "lesson")

    def __str__(self):
        return f"{self.student.user.full_name}: {self.grade}"


class MonthlyStudentReportDispatch(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    )

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="monthly_report_dispatches",
    )
    month = models.DateField(help_text="First day of the reporting month.")
    trigger_date = models.DateField(help_text="Last lesson date in the reporting month.")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    workflow_run_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-month", "student__user__full_name")
        constraints = [
            models.UniqueConstraint(
                fields=("student", "month"),
                name="unique_monthly_student_report_dispatch",
            )
        ]

    def __str__(self):
        return f"{self.student.user.full_name} - {self.month:%Y-%m}"
