from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField

ORGANIZATION_ACADEMY = "academy"
ORGANIZATION_COLLEGE = "college"
ORGANIZATION_CHOICES = ((ORGANIZATION_ACADEMY, "Академия"), (ORGANIZATION_COLLEGE, "Колледж"))
COLLEGE_COURSE_CHOICES = (("1", "1 курс"), ("2", "2 курс"), ("3", "3 курс"), ("4", "4 курс"))


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
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, default=ORGANIZATION_ACADEMY, db_index=True)

    class Meta:
        ordering = ("user__full_name",)

    def __str__(self):
        return self.user.full_name


class Group(models.Model):
    MON_WED_SAT = "MON_WED_SAT"
    TUE_THU_SUN = "TUE_THU_SUN"
    MON_FRI = "MON_FRI"
    STUDY_DAYS_CHOICES = (
        (MON_WED_SAT, "Пн • Ср • Сб"),
        (TUE_THU_SUN, "Вт • Чт • Вс"),
    )

    STUDY_DAYS_CHOICES += ((MON_FRI, "Пн • Вт • Ср • Чт • Пт"),)

    course_name = models.CharField(max_length=100)
    mentor = models.ForeignKey(MentorProfile, on_delete=models.CASCADE, related_name="groups")
    study_days = models.CharField(max_length=32, choices=STUDY_DAYS_CHOICES)
    description = models.TextField(blank=True)
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, default=ORGANIZATION_ACADEMY, db_index=True)
    college_course = models.CharField(max_length=1, choices=COLLEGE_COURSE_CHOICES, blank=True)

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
    archived_at = models.DateTimeField(null=True, blank=True)
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, default=ORGANIZATION_ACADEMY, db_index=True)
    college_groups = models.ManyToManyField(Group, blank=True, related_name="college_students")
    college_course = models.CharField(max_length=1, choices=COLLEGE_COURSE_CHOICES, blank=True)

    class Meta:
        ordering = ("user__full_name",)

    def __str__(self):
        return self.user.full_name


class UserOrganizationAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_accesses")
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, default=ORGANIZATION_ACADEMY)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("user", "organization_type"), name="unique_user_organization_access")]


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


class MonthlyStudentReportAttempt(models.Model):
    dispatch = models.ForeignKey(
        MonthlyStudentReportDispatch,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
    )
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=MonthlyStudentReportDispatch.STATUS_CHOICES,
        default=MonthlyStudentReportDispatch.STATUS_PENDING,
    )
    payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    workflow_run_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("dispatch", "attempt_number"),
                name="unique_monthly_report_delivery_attempt",
            )
        ]

    def __str__(self):
        return f"{self.dispatch} / attempt {self.attempt_number}"
