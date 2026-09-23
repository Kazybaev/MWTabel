from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Badge,
    CollegeGroup,
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    ORGANIZATION_CHOICES,
    StudentProfile,
    StudentBadge,
    User,
    UserOrganizationAccess,
)
from .organization import allowed_organizations_for_user, college_branch_for_request, organization_for_request, require_agrarian_college


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            username=attrs["username"],
            password=attrs["password"],
        )
        if user and user.is_active:
            attrs["user"] = user
            return attrs
        raise serializers.ValidationError("Неверные учетные данные")

    def to_representation(self, instance):
        user = instance["user"]
        refresh = RefreshToken.for_user(user)
        return {
            "user": UserSerializer(user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


def move_student_records_to_group(student, old_group, new_group):
    if old_group == new_group:
        return

    records = list(
        LessonRecord.objects.select_related("lesson")
        .filter(student=student, lesson__group=old_group)
        .order_by("lesson__lesson_date", "lesson_id")
    )

    for record in records:
        source_lesson = record.lesson
        target_lesson = (
            Lesson.objects.filter(group=new_group, lesson_date=source_lesson.lesson_date)
            .order_by("id")
            .first()
        )
        if target_lesson is None:
            target_lesson = Lesson.objects.create(
                group=new_group,
                lesson_date=source_lesson.lesson_date,
                topic=source_lesson.topic,
            )

        target_record, _ = LessonRecord.objects.update_or_create(
            student=student,
            lesson=target_lesson,
            sequence=record.sequence,
            defaults={
                "grade": record.grade,
                "comment": record.comment,
                "author": record.author,
            },
        )
        if target_record.pk != record.pk:
            record.delete()


class ReportDispatchRequestSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    month = serializers.RegexField(regex=r"^\d{4}-\d{2}$", required=False)
    run_date = serializers.DateField(required=False)
    dry_run = serializers.BooleanField(required=False, default=False)
    force = serializers.BooleanField(required=False, default=False)


class ReportBulkDispatchRequestSerializer(serializers.Serializer):
    month = serializers.RegexField(regex=r"^\d{4}-\d{2}$", required=False)
    group_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=False)
    student_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=False)


class ReportDeliveryCallbackSerializer(serializers.Serializer):
    delivery = serializers.JSONField()
    meta_status_code = serializers.IntegerField(min_value=100, max_value=599)
    meta_response = serializers.JSONField()

    def validate_delivery(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("delivery must be a JSON object.")

        report = value.get("report")
        student = report.get("student") if isinstance(report, dict) else None
        period = report.get("period") if isinstance(report, dict) else None
        if not isinstance(student, dict) or not student.get("id"):
            raise serializers.ValidationError("delivery.report.student.id is required.")
        if not isinstance(period, dict) or not period.get("month"):
            raise serializers.ValidationError("delivery.report.period.month is required.")
        return value


class UserSerializer(serializers.ModelSerializer):
    mentor_profile_id = serializers.SerializerMethodField()
    student_profile_id = serializers.SerializerMethodField()
    group_id = serializers.SerializerMethodField()
    organizations = serializers.SerializerMethodField()
    college_branch = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "email",
            "role",
            "mentor_profile_id",
            "student_profile_id",
            "group_id",
            "organizations",
            "college_branch",
        ]

    def get_mentor_profile_id(self, obj):
        mentor_profile = getattr(obj, "mentor_profile", None)
        return mentor_profile.pk if mentor_profile else None

    def get_student_profile_id(self, obj):
        student_profile = getattr(obj, "student_profile", None)
        return student_profile.pk if student_profile else None

    def get_group_id(self, obj):
        student_profile = getattr(obj, "student_profile", None)
        return student_profile.group_id if student_profile else None

    def get_organizations(self, obj):
        return allowed_organizations_for_user(obj)

    def get_college_branch(self, obj):
        student_profile = getattr(obj, "student_profile", None)
        return student_profile.college_branch if student_profile and student_profile.organization_type == "college" else None


class MentorProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    full_name = serializers.CharField(source="user.full_name")
    username = serializers.CharField(source="user.username")
    email = serializers.EmailField(source="user.email", allow_blank=True, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, style={"input_type": "password"})
    groups_count = serializers.SerializerMethodField()
    organizations = serializers.ListField(
        child=serializers.ChoiceField(choices=ORGANIZATION_CHOICES),
        allow_empty=False,
        required=False,
    )

    class Meta:
        model = MentorProfile
        fields = ["id", "user_id", "full_name", "username", "email", "password", "groups_count", "organization_type", "organizations"]
        read_only_fields = ["organization_type"]

    def get_groups_count(self, obj):
        annotated_count = getattr(obj, "groups_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.groups.count()

    def validate_username(self, value):
        queryset = User.objects.filter(username=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.user_id)
        if queryset.exists():
            raise serializers.ValidationError("Пользователь с таким логином уже существует.")
        return value

    def validate_organizations(self, value):
        organizations = list(dict.fromkeys(value))
        if self.instance:
            assigned = set(self.instance.groups.values_list("organization_type", flat=True))
            missing = assigned.difference(organizations)
            if missing:
                labels = dict(ORGANIZATION_CHOICES)
                names = ", ".join(labels[item] for item in sorted(missing))
                raise serializers.ValidationError(
                    f"Нельзя убрать доступ: у ментора остались группы в разделе {names}."
                )
        return organizations

    def validate(self, attrs):
        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Пароль обязателен для нового ментора."})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["organizations"] = allowed_organizations_for_user(instance.user)
        return data

    @staticmethod
    def sync_organizations(user, organizations):
        UserOrganizationAccess.objects.filter(user=user).exclude(
            organization_type__in=organizations
        ).delete()
        UserOrganizationAccess.objects.bulk_create(
            [
                UserOrganizationAccess(user=user, organization_type=organization)
                for organization in organizations
            ],
            ignore_conflicts=True,
        )

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        user_data = validated_data.pop("user")
        organizations = validated_data.pop("organizations", [validated_data.get("organization_type", "academy")])
        user = User.objects.create_user(
            username=user_data["username"],
            password=password,
            full_name=user_data["full_name"],
            email=user_data.get("email", ""),
            role=User.ROLE_MENTOR,
        )
        mentor = MentorProfile.objects.create(user=user, **validated_data)
        self.sync_organizations(user, organizations)
        return mentor

    @transaction.atomic
    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        user_data = validated_data.pop("user", {})
        organizations = validated_data.pop("organizations", None)
        user = instance.user
        user.full_name = user_data.get("full_name", user.full_name)
        user.username = user_data.get("username", user.username)
        user.email = user_data.get("email", user.email)
        user.role = User.ROLE_MENTOR
        if password:
            user.set_password(password)
        user.save()
        if organizations is not None:
            self.sync_organizations(user, organizations)
        return instance


class CollegeGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollegeGroup
        fields = ["id", "name", "college_branch"]
        read_only_fields = ["college_branch"]
        validators = []

    def validate_name(self, value):
        request = self.context.get("request")
        branch = college_branch_for_request(request) if request else "kuwait"
        queryset = CollegeGroup.objects.filter(college_branch=branch, name=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("Основная группа с таким названием уже существует в этом колледже.")
        return value


class StudentProfileSerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    full_name = serializers.CharField(source="user.full_name")
    username = serializers.CharField(source="user.username")
    email = serializers.EmailField(source="user.email", allow_blank=True, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, style={"input_type": "password"})
    main_group = serializers.IntegerField(source="group.main_group_id", read_only=True)
    main_group_name = serializers.CharField(source="group.main_group.name", read_only=True, default="")
    group_name = serializers.CharField(source="group.course_name", read_only=True)
    is_archived = serializers.SerializerMethodField()

    class Meta:
        model = StudentProfile
        fields = [
            "id",
            "user_id",
            "full_name",
            "username",
            "email",
            "password",
            "parent_name",
            "parent_phone",
            "group",
            "group_name",
            "main_group",
            "main_group_name",
            "archived_at",
            "is_archived",
            "organization_type",
            "college_course",
            "college_branch",
            "college_groups",
        ]
        read_only_fields = ["archived_at", "organization_type", "college_branch"]

    def get_is_archived(self, obj):
        return obj.archived_at is not None

    def validate_username(self, value):
        queryset = User.objects.filter(username=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.user_id)
        if queryset.exists():
            raise serializers.ValidationError("Пользователь с таким логином уже существует.")
        return value

    def validate(self, attrs):
        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Пароль обязателен для нового студента."})
        request = self.context.get("request")
        organization = organization_for_request(request) if request else "academy"
        college_branch = college_branch_for_request(request) if request and organization == "college" else None
        group = attrs.get("group", self.instance.group if self.instance else None)
        if group and group.organization_type != organization:
            raise serializers.ValidationError({"group": "Группа относится к другой организации."})
        if group and group.archived_at is not None:
            raise serializers.ValidationError({"group": "Нельзя назначить студента в архивную группу."})
        college_groups = attrs.get("college_groups", list(self.instance.college_groups.all()) if self.instance else [])
        if organization == "college" and not college_groups:
            raise serializers.ValidationError({"college_groups": "Выберите хотя бы одну группу."})
        if any(item.organization_type != organization for item in college_groups):
            raise serializers.ValidationError({"college_groups": "Все предметы должны относиться к текущей организации."})
        if any(item.archived_at is not None for item in college_groups):
            raise serializers.ValidationError({"college_groups": "Нельзя выбрать архивную группу."})
        if organization == "college" and college_groups:
            if any(item.college_branch != college_branch for item in college_groups):
                raise serializers.ValidationError({"college_groups": "Все группы должны относиться к выбранному колледжу."})
            if len({item.main_group_id for item in college_groups}) > 1:
                raise serializers.ValidationError({"college_groups": "Подгруппы должны принадлежать одной основной группе."})
            if group not in college_groups:
                raise serializers.ValidationError({"group": "Выберите одну из назначенных подгрупп."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        user_data = validated_data.pop("user")
        college_groups = validated_data.pop("college_groups", [])
        user = User.objects.create_user(
            username=user_data["username"],
            password=password,
            full_name=user_data["full_name"],
            email=user_data.get("email", ""),
            role=User.ROLE_STUDENT,
        )
        student = StudentProfile.objects.create(user=user, **validated_data)
        if student.organization_type == "college":
            student.college_groups.set(college_groups or [student.group])
        return student

    def update(self, instance, validated_data):
        with transaction.atomic():
            password = validated_data.pop("password", "")
            user_data = validated_data.pop("user", {})
            old_group = instance.group
            new_group = validated_data.get("group", instance.group)
            user = instance.user
            user.full_name = user_data.get("full_name", user.full_name)
            user.username = user_data.get("username", user.username)
            user.email = user_data.get("email", user.email)
            user.role = User.ROLE_STUDENT
            if instance.archived_at is None:
                user.is_active = True
            if password:
                user.set_password(password)
            user.save()

            instance.parent_name = validated_data.get("parent_name", instance.parent_name)
            instance.parent_phone = validated_data.get("parent_phone", instance.parent_phone)
            instance.group = new_group
            instance.college_course = validated_data.get("college_course", instance.college_course)
            instance.save()
            if "college_groups" in validated_data:
                instance.college_groups.set(validated_data["college_groups"])
            if instance.organization_type != "college":
                move_student_records_to_group(instance, old_group, new_group)
        return instance


class LessonRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.full_name", read_only=True)
    author_name = serializers.CharField(source="author.full_name", read_only=True, default="")

    class Meta:
        model = LessonRecord
        fields = ["id", "student", "student_name", "grade", "comment", "author", "author_name", "sequence", "created_at", "updated_at"]


class AgrarianGradeRecordSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all(), required=False)
    student_name = serializers.CharField(source="student.user.full_name", read_only=True)
    group = serializers.PrimaryKeyRelatedField(queryset=Group.objects.all(), required=False)
    group_name = serializers.CharField(source="lesson.group.course_name", read_only=True)
    date = serializers.DateField(required=False)
    score = serializers.ChoiceField(choices=LessonRecord.GRADE_CHOICES, source="grade", required=False)
    comment = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    teacher = serializers.IntegerField(source="author_id", read_only=True)
    teacher_name = serializers.CharField(source="author.full_name", read_only=True, default="")
    sequence = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["group"] = instance.lesson.group_id
        data["date"] = instance.lesson.lesson_date.isoformat()
        return data

    def validate(self, attrs):
        request = self.context["request"]
        require_agrarian_college(request)
        if self.instance:
            forbidden = {"student", "group", "date"}.intersection(self.initial_data)
            if forbidden:
                raise serializers.ValidationError("Студента, группу и дату существующей оценки изменять нельзя.")
            return attrs

        missing = [field for field in ("student", "group", "date", "grade") if field not in attrs]
        if missing:
            raise serializers.ValidationError("Укажите студента, группу, дату и оценку.")
        student = attrs["student"]
        group = attrs["group"]
        if group.organization_type != "college" or group.college_branch != "agrarian" or group.archived_at is not None:
            raise serializers.ValidationError({"group": "Группа должна относиться к активному Аграрному колледжу."})
        if student.organization_type != "college" or student.college_branch != "agrarian" or student.archived_at is not None:
            raise serializers.ValidationError({"student": "Студент должен относиться к активному Аграрному колледжу."})
        if not student.college_groups.filter(pk=group.pk).exists() and student.group_id != group.pk:
            raise serializers.ValidationError({"student": "Студент не состоит в выбранной группе."})
        if request.user.role == User.ROLE_MENTOR and group.mentor.user_id != request.user.id:
            raise serializers.ValidationError({"group": "Ментор может работать только со своими группами."})
        return attrs


class BadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = ["id", "name", "description", "icon", "is_active", "sort_order", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class StudentBadgeSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.full_name", read_only=True)
    badge_name = serializers.CharField(source="badge.name", read_only=True)
    badge_icon = serializers.CharField(source="badge.icon", read_only=True)
    group_name = serializers.CharField(source="group.course_name", read_only=True)
    teacher_name = serializers.CharField(source="teacher.full_name", read_only=True, default="")

    class Meta:
        model = StudentBadge
        fields = [
            "id", "student", "student_name", "badge", "badge_name", "badge_icon",
            "group", "group_name", "teacher", "teacher_name", "comment", "created_at", "updated_at",
        ]
        read_only_fields = ["teacher", "created_at", "updated_at"]

    def validate(self, attrs):
        request = self.context["request"]
        require_agrarian_college(request)
        if self.instance:
            forbidden = {"student", "badge", "group"}.intersection(self.initial_data)
            if forbidden:
                raise serializers.ValidationError("Студента, значок и группу существующей выдачи изменять нельзя.")
            return attrs

        student = attrs.get("student")
        badge = attrs.get("badge")
        group = attrs.get("group")
        if not student or not badge or not group:
            raise serializers.ValidationError("Укажите студента, значок и группу.")
        if not badge.is_active:
            raise serializers.ValidationError({"badge": "Этот значок больше не используется."})
        if group.organization_type != "college" or group.college_branch != "agrarian" or group.archived_at is not None:
            raise serializers.ValidationError({"group": "Группа должна относиться к активному Аграрному колледжу."})
        if student.organization_type != "college" or student.college_branch != "agrarian" or student.archived_at is not None:
            raise serializers.ValidationError({"student": "Студент должен относиться к активному Аграрному колледжу."})
        if not student.college_groups.filter(pk=group.pk).exists() and student.group_id != group.pk:
            raise serializers.ValidationError({"student": "Студент не состоит в выбранной группе."})
        if request.user.role == User.ROLE_MENTOR and group.mentor.user_id != request.user.id:
            raise serializers.ValidationError({"group": "Ментор может работать только со своими группами."})
        return attrs


class LessonSerializer(serializers.ModelSerializer):
    records = serializers.SerializerMethodField()
    group_name = serializers.CharField(source="group.course_name", read_only=True)

    class Meta:
        model = Lesson
        fields = ["id", "lesson_date", "topic", "group", "group_name", "records"]

    def get_records(self, obj):
        request = self.context.get("request")
        queryset = obj.records.select_related("student__user")
        if request and request.user.role == User.ROLE_STUDENT and hasattr(request.user, "student_profile"):
            queryset = queryset.filter(student=request.user.student_profile)
        return LessonRecordSerializer(queryset, many=True).data

    def validate_group(self, group):
        request = self.context.get("request")
        if request and group.organization_type != organization_for_request(request):
            raise serializers.ValidationError("Группа относится к другой организации.")
        if request and group.organization_type == "college" and group.college_branch != college_branch_for_request(request):
            raise serializers.ValidationError("Группа относится к другому колледжу.")
        if group.archived_at is not None:
            raise serializers.ValidationError("Нельзя назначить студента в архивную группу.")
        return group


class GroupListSerializer(serializers.ModelSerializer):
    main_group_name = serializers.CharField(source="main_group.name", read_only=True, default="")
    mentor_name = serializers.CharField(source="mentor.user.full_name", read_only=True)
    study_days_label = serializers.CharField(source="get_study_days_display", read_only=True)
    students_count = serializers.SerializerMethodField()
    is_archived = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "course_name",
            "main_group",
            "main_group_name",
            "study_days",
            "study_days_label",
            "description",
            "mentor",
            "mentor_name",
            "students_count",
            "organization_type",
            "college_course",
            "college_branch",
            "archived_at",
            "is_archived",
        ]

    def get_is_archived(self, obj):
        return obj.archived_at is not None

    def get_students_count(self, obj):
        if obj.archived_at is not None:
            return obj.college_students.count() if obj.organization_type == "college" else obj.students.count()
        annotated_count = getattr(obj, "students_count", None)
        if annotated_count is not None:
            return annotated_count
        if obj.organization_type == "college":
            return obj.college_students.filter(archived_at__isnull=True).count()
        return obj.students.filter(archived_at__isnull=True).count()


class GroupWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "course_name", "mentor", "study_days", "description", "organization_type", "college_course", "college_branch", "main_group"]
        read_only_fields = ["organization_type", "college_branch"]

    def validate(self, attrs):
        request = self.context.get("request")
        organization = organization_for_request(request) if request else "academy"
        main_group = attrs.get("main_group", self.instance.main_group if self.instance else None)
        if main_group and organization != "college":
            raise serializers.ValidationError({"main_group": "Основные группы доступны только в колледже."})
        if main_group and main_group.college_branch != college_branch_for_request(request):
            raise serializers.ValidationError({"main_group": "Основная группа относится к другому колледжу."})
        if self.instance and main_group != self.instance.main_group:
            students = self.instance.college_students.all()
            if Group.objects.filter(college_students__in=students).exclude(pk=self.instance.pk).exclude(main_group__isnull=True).exclude(main_group=main_group).exists():
                raise serializers.ValidationError({"main_group": "Сначала измените состав студентов: у них есть подгруппы другой основной группы."})
        return attrs

    def validate_mentor(self, mentor):
        request = self.context.get("request")
        if request and organization_for_request(request) not in allowed_organizations_for_user(mentor.user):
            raise serializers.ValidationError("Ментор относится к другой организации.")
        return mentor


class GroupDetailSerializer(serializers.ModelSerializer):
    main_group_name = serializers.CharField(source="main_group.name", read_only=True, default="")
    mentor = MentorProfileSerializer(read_only=True)
    mentor_name = serializers.CharField(source="mentor.user.full_name", read_only=True)
    study_days_label = serializers.CharField(source="get_study_days_display", read_only=True)
    students_count = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()
    lessons = serializers.SerializerMethodField()
    is_archived = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "course_name",
            "main_group",
            "main_group_name",
            "study_days",
            "study_days_label",
            "description",
            "mentor",
            "mentor_name",
            "students_count",
            "students",
            "lessons",
            "organization_type",
            "college_course",
            "college_branch",
            "archived_at",
            "is_archived",
        ]

    def get_is_archived(self, obj):
        return obj.archived_at is not None

    def get_students_count(self, obj):
        if obj.archived_at is not None:
            return obj.college_students.count() if obj.organization_type == "college" else obj.students.count()
        annotated_count = getattr(obj, "students_count", None)
        if annotated_count is not None:
            return annotated_count
        if obj.organization_type == "college":
            return obj.college_students.filter(archived_at__isnull=True).count()
        return obj.students.filter(archived_at__isnull=True).count()

    def get_students(self, obj):
        request = self.context.get("request")
        if request and request.user.role == User.ROLE_STUDENT:
            return []
        relation = obj.college_students if obj.organization_type == "college" else obj.students
        queryset = (relation if obj.archived_at is not None else relation.filter(archived_at__isnull=True)).select_related("user")
        return StudentProfileSerializer(queryset, many=True).data

    def get_lessons(self, obj):
        queryset = obj.lessons.order_by("-lesson_date", "group__course_name")
        return LessonSerializer(queryset, many=True, context=self.context).data
