from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from phonenumber_field.modelfields import PhoneNumberField

ORGANIZATION_ACADEMY = "academy"
ORGANIZATION_COLLEGE = "college"
ORGANIZATION_CHOICES = ((ORGANIZATION_ACADEMY, "Академия"), (ORGANIZATION_COLLEGE, "Колледж"))
COLLEGE_COURSE_CHOICES = (("1", "1 курс"), ("2", "2 курс"), ("3", "3 курс"), ("4", "4 курс"))
COLLEGE_BRANCH_KUWAIT = "kuwait"
COLLEGE_BRANCH_AGRARIAN = "agrarian"
COLLEGE_BRANCH_CHOICES = (
    (COLLEGE_BRANCH_KUWAIT, "Кувейтский колледж"),
    (COLLEGE_BRANCH_AGRARIAN, "Аграрный колледж"),
)


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


class CollegeGroup(models.Model):
    name = models.CharField(max_length=100)
    college_branch = models.CharField(
        max_length=16,
        choices=COLLEGE_BRANCH_CHOICES,
        default=COLLEGE_BRANCH_KUWAIT,
        db_index=True,
    )

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("college_branch", "name"),
                name="unique_college_group_name_per_branch",
            )
        ]

    def __str__(self):
        return self.name


class Group(models.Model):
    MON_WED_SAT = "MON_WED_SAT"
    TUE_THU_SUN = "TUE_THU_SUN"
    MON_FRI = "MON_FRI"
    STUDY_DAYS_CHOICES = (
        (MON_WED_SAT, "Пн • Ср • Сб"),
        (TUE_THU_SUN, "Вт • Чт • Вс"),
    )

    STUDY_DAYS_CHOICES += ((MON_FRI, "Пн • Вт • Ср • Чт • Пт"),)

    main_group = models.ForeignKey(
        CollegeGroup, null=True, blank=True, on_delete=models.PROTECT, related_name="subgroups",
    )
    course_name = models.CharField(max_length=100)
    mentor = models.ForeignKey(MentorProfile, on_delete=models.CASCADE, related_name="groups")
    study_days = models.CharField(max_length=32, choices=STUDY_DAYS_CHOICES)
    description = models.TextField(blank=True)
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, default=ORGANIZATION_ACADEMY, db_index=True)
    college_course = models.CharField(max_length=1, choices=COLLEGE_COURSE_CHOICES, blank=True)
    college_branch = models.CharField(
        max_length=16,
        choices=COLLEGE_BRANCH_CHOICES,
        default=COLLEGE_BRANCH_KUWAIT,
        db_index=True,
    )
    archived_at = models.DateTimeField(null=True, blank=True)

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
    parent_name = models.CharField(max_length=100, blank=True)
    parent_phone = PhoneNumberField()
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="students")
    archived_at = models.DateTimeField(null=True, blank=True)
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, default=ORGANIZATION_ACADEMY, db_index=True)
    college_groups = models.ManyToManyField(Group, blank=True, related_name="college_students")
    college_course = models.CharField(max_length=1, choices=COLLEGE_COURSE_CHOICES, blank=True)
    college_branch = models.CharField(
        max_length=16,
        choices=COLLEGE_BRANCH_CHOICES,
        default=COLLEGE_BRANCH_KUWAIT,
        db_index=True,
    )

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
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="authored_lesson_records",
    )
    sequence = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("student__user__full_name", "lesson__lesson_date", "sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("student", "lesson", "sequence"),
                name="unique_student_lesson_record_sequence",
            )
        ]

    def __str__(self):
        return f"{self.student.user.full_name}: {self.grade}"


class Badge(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    icon = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "name", "id")

    def __str__(self):
        return f"{self.icon} {self.name}"


class StudentBadge(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="badges")
    badge = models.ForeignKey(Badge, on_delete=models.PROTECT, related_name="awards")
    group = models.ForeignKey(Group, on_delete=models.PROTECT, related_name="student_badges")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="awarded_student_badges",
    )
    comment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.student}: {self.badge}"


class MonthlyStudentReportDispatch(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DELIVERED = "delivered"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted by Meta"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_SUCCEEDED, "Succeeded (legacy)"),
        (STATUS_FAILED, "Failed"),
    )
    SUCCESSFUL_STATUSES = (STATUS_ACCEPTED, STATUS_DELIVERED, STATUS_SUCCEEDED)

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
    meta_message_id = models.CharField(max_length=512, null=True, blank=True, unique=True)
    message_status = models.CharField(max_length=32, blank=True)
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


class MonthlyStudentReportBatch(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    month = models.DateField(help_text="First day of the reporting month.")
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    confirm_retry_failed = models.BooleanField(default=False)
    requested_filters = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="monthly_report_batches",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")


class MonthlyStudentReportBatchItem(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_PENDING, "Pending callback"),
        (STATUS_ACCEPTED, "Accepted by Meta"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_CANCELLED, "Cancelled"),
    )
    TERMINAL_STATUSES = (STATUS_ACCEPTED, STATUS_DELIVERED, STATUS_FAILED, STATUS_SKIPPED, STATUS_CANCELLED)
    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_PROCESSING, STATUS_PENDING)

    batch = models.ForeignKey(
        MonthlyStudentReportBatch,
        on_delete=models.CASCADE,
        related_name="items",
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.PROTECT,
        related_name="monthly_report_batch_items",
    )
    month = models.DateField(help_text="First day of the reporting month.")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    dispatch = models.ForeignKey(
        MonthlyStudentReportDispatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="batch_items",
    )
    attempt = models.OneToOneField(
        MonthlyStudentReportAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="batch_item",
    )
    worker_token = models.UUIDField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    dedupe_key = models.CharField(max_length=64, null=True, blank=True)
    requires_operator_review = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("batch_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "student", "month"),
                name="unique_monthly_report_batch_student_month",
            ),
            models.UniqueConstraint(
                fields=("dedupe_key",),
                condition=models.Q(
                    dedupe_key__isnull=False,
                    status__in=("queued", "processing", "pending"),
                ),
                name="unique_active_monthly_report_context",
            ),
        ]


class WahaTestReportBatch(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = (
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
    )

    month = models.DateField(help_text="First day of the reporting month.")
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="waha_test_report_batches",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")


class WahaTestReportBatchItem(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_ACCEPTED = "accepted"
    STATUS_FAILED = "failed"
    STATUS_UNKNOWN = "unknown"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = (
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_ACCEPTED, "Accepted by WAHA"),
        (STATUS_FAILED, "Failed"),
        (STATUS_UNKNOWN, "Delivery result unknown"),
        (STATUS_SKIPPED, "Skipped"),
    )
    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_PROCESSING)
    TERMINAL_STATUSES = (STATUS_ACCEPTED, STATUS_FAILED, STATUS_UNKNOWN, STATUS_SKIPPED)

    batch = models.ForeignKey(WahaTestReportBatch, on_delete=models.CASCADE, related_name="items")
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.PROTECT,
        related_name="waha_test_report_items",
    )
    month = models.DateField(help_text="First day of the reporting month.")
    recipient_phone = PhoneNumberField()
    report_payload = models.JSONField(default=dict, blank=True)
    message_text = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    dedupe_key = models.CharField(max_length=64, null=True, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("batch_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "student", "month"),
                name="unique_waha_test_batch_student_month",
            ),
            models.UniqueConstraint(
                fields=("dedupe_key",),
                condition=models.Q(
                    dedupe_key__isnull=False,
                    status__in=("queued", "processing"),
                ),
                name="unique_active_waha_test_report_context",
            ),
        ]


class WahaParentReportBatch(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    month = models.DateField(help_text="First day of the reporting month.")
    organization_type = models.CharField(max_length=16, choices=ORGANIZATION_CHOICES, db_index=True)
    college_branch = models.CharField(
        max_length=16,
        choices=COLLEGE_BRANCH_CHOICES,
        blank=True,
        db_index=True,
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    requested_filters = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="waha_parent_report_batches",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")


class WahaParentReportBatchItem(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_ACCEPTED = "accepted"
    STATUS_FAILED = "failed"
    STATUS_UNKNOWN = "unknown"
    STATUS_SKIPPED = "skipped"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_ACCEPTED, "Accepted by WAHA"),
        (STATUS_FAILED, "Failed"),
        (STATUS_UNKNOWN, "Delivery result unknown"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_CANCELLED, "Cancelled"),
    )
    ACTIVE_STATUSES = (STATUS_DRAFT, STATUS_QUEUED, STATUS_PROCESSING)
    TERMINAL_STATUSES = (STATUS_ACCEPTED, STATUS_FAILED, STATUS_UNKNOWN, STATUS_SKIPPED, STATUS_CANCELLED)

    batch = models.ForeignKey(WahaParentReportBatch, on_delete=models.CASCADE, related_name="items")
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.PROTECT,
        related_name="waha_parent_report_items",
    )
    month = models.DateField(help_text="First day of the reporting month.")
    recipient_phone = PhoneNumberField()
    report_payload = models.JSONField(default=dict, blank=True)
    message_text = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    dedupe_key = models.CharField(max_length=64, null=True, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("batch_id", "id")
        indexes = [
            models.Index(
                fields=("student", "month", "status"),
                name="waha_parent_stu_month_st_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "student", "month"),
                name="unique_waha_parent_batch_student_month",
            ),
            models.UniqueConstraint(
                fields=("dedupe_key",),
                condition=models.Q(
                    dedupe_key__isnull=False,
                    status__in=("draft", "queued", "processing"),
                ),
                name="unique_active_waha_parent_report_context",
            ),
        ]


class ImportedGradeCell(models.Model):
    """Immutable source evidence, including cells resolved into LessonRecord."""
    source_id = models.CharField(max_length=255)
    source_class = models.CharField(max_length=255)
    source_row = models.PositiveIntegerField()
    source_column = models.CharField(max_length=64)
    original_value = models.JSONField(null=True, blank=True)
    original_header = models.JSONField(null=True, blank=True)
    content_sha256 = models.CharField(max_length=64)
    student = models.ForeignKey(StudentProfile, null=True, blank=True, on_delete=models.SET_NULL)
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL)
    lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['source_id', 'source_class', 'source_row', 'source_column'],
            name='unique_imported_grade_cell')]
