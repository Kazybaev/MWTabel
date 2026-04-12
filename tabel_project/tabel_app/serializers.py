from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Group, Lesson, LessonRecord, MentorProfile, StudentProfile, User


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


class UserSerializer(serializers.ModelSerializer):
    mentor_profile_id = serializers.SerializerMethodField()
    student_profile_id = serializers.SerializerMethodField()
    group_id = serializers.SerializerMethodField()

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


class MentorProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    full_name = serializers.CharField(source="user.full_name")
    username = serializers.CharField(source="user.username")
    email = serializers.EmailField(source="user.email", allow_blank=True, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, style={"input_type": "password"})
    groups_count = serializers.SerializerMethodField()

    class Meta:
        model = MentorProfile
        fields = ["id", "user_id", "full_name", "username", "email", "password", "groups_count"]

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

    def validate(self, attrs):
        if not self.instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Пароль обязателен для нового ментора."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user_data = validated_data.pop("user")
        user = User.objects.create_user(
            username=user_data["username"],
            password=password,
            full_name=user_data["full_name"],
            email=user_data.get("email", ""),
            role=User.ROLE_MENTOR,
        )
        return MentorProfile.objects.create(user=user)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        user_data = validated_data.pop("user", {})
        user = instance.user
        user.full_name = user_data.get("full_name", user.full_name)
        user.username = user_data.get("username", user.username)
        user.email = user_data.get("email", user.email)
        user.role = User.ROLE_MENTOR
        if password:
            user.set_password(password)
        user.save()
        return instance


class StudentProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    full_name = serializers.CharField(source="user.full_name")
    username = serializers.CharField(source="user.username")
    email = serializers.EmailField(source="user.email", allow_blank=True, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, style={"input_type": "password"})
    group_name = serializers.CharField(source="group.course_name", read_only=True)

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
        ]

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
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user_data = validated_data.pop("user")
        user = User.objects.create_user(
            username=user_data["username"],
            password=password,
            full_name=user_data["full_name"],
            email=user_data.get("email", ""),
            role=User.ROLE_STUDENT,
        )
        return StudentProfile.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        user_data = validated_data.pop("user", {})
        user = instance.user
        user.full_name = user_data.get("full_name", user.full_name)
        user.username = user_data.get("username", user.username)
        user.email = user_data.get("email", user.email)
        user.role = User.ROLE_STUDENT
        if password:
            user.set_password(password)
        user.save()

        instance.parent_name = validated_data.get("parent_name", instance.parent_name)
        instance.parent_phone = validated_data.get("parent_phone", instance.parent_phone)
        instance.group = validated_data.get("group", instance.group)
        instance.save()
        return instance


class LessonRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.user.full_name", read_only=True)

    class Meta:
        model = LessonRecord
        fields = ["id", "student", "student_name", "grade", "comment"]


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


class GroupListSerializer(serializers.ModelSerializer):
    mentor_name = serializers.CharField(source="mentor.user.full_name", read_only=True)
    study_days_label = serializers.CharField(source="get_study_days_display", read_only=True)
    students_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "course_name",
            "study_days",
            "study_days_label",
            "description",
            "mentor",
            "mentor_name",
            "students_count",
        ]

    def get_students_count(self, obj):
        annotated_count = getattr(obj, "students_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.students.count()


class GroupWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ["id", "course_name", "mentor", "study_days", "description"]


class GroupDetailSerializer(serializers.ModelSerializer):
    mentor = MentorProfileSerializer(read_only=True)
    mentor_name = serializers.CharField(source="mentor.user.full_name", read_only=True)
    study_days_label = serializers.CharField(source="get_study_days_display", read_only=True)
    students_count = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()
    lessons = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "course_name",
            "study_days",
            "study_days_label",
            "description",
            "mentor",
            "mentor_name",
            "students_count",
            "students",
            "lessons",
        ]

    def get_students_count(self, obj):
        annotated_count = getattr(obj, "students_count", None)
        if annotated_count is not None:
            return annotated_count
        return obj.students.count()

    def get_students(self, obj):
        request = self.context.get("request")
        if request and request.user.role == User.ROLE_STUDENT:
            return []
        queryset = obj.students.select_related("user")
        return StudentProfileSerializer(queryset, many=True).data

    def get_lessons(self, obj):
        queryset = obj.lessons.order_by("-lesson_date", "group__course_name")
        return LessonSerializer(queryset, many=True, context=self.context).data
