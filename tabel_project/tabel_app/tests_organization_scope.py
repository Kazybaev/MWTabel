from rest_framework import status
from rest_framework.test import APITestCase
from django.utils import timezone

from .models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    ORGANIZATION_ACADEMY,
    ORGANIZATION_COLLEGE,
    StudentProfile,
    User,
    UserOrganizationAccess,
)


class OrganizationScopeApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="scope-admin", password="pass-12345", full_name="Scope Admin", role=User.ROLE_ADMIN)
        UserOrganizationAccess.objects.bulk_create([
            UserOrganizationAccess(user=self.admin, organization_type=ORGANIZATION_ACADEMY),
            UserOrganizationAccess(user=self.admin, organization_type=ORGANIZATION_COLLEGE),
        ])
        academy_mentor_user = User.objects.create_user(username="academy-mentor", password="pass-12345", full_name="Academy Mentor", role=User.ROLE_MENTOR)
        college_mentor_user = User.objects.create_user(username="college-mentor", password="pass-12345", full_name="College Mentor", role=User.ROLE_MENTOR)
        self.academy_mentor = MentorProfile.objects.create(user=academy_mentor_user, organization_type=ORGANIZATION_ACADEMY)
        self.college_mentor = MentorProfile.objects.create(user=college_mentor_user, organization_type=ORGANIZATION_COLLEGE)
        self.academy_group = Group.objects.create(course_name="Academy Group", mentor=self.academy_mentor, study_days=Group.MON_WED_SAT, organization_type=ORGANIZATION_ACADEMY)
        self.college_group = Group.objects.create(course_name="Math", mentor=self.college_mentor, study_days=Group.MON_FRI, organization_type=ORGANIZATION_COLLEGE)
        self.client.force_authenticate(self.admin)

    def headers(self, organization):
        return {"HTTP_X_ORGANIZATION_TYPE": organization}

    def test_group_lists_are_fully_separated(self):
        academy = self.client.get("/api/groups/", **self.headers(ORGANIZATION_ACADEMY))
        college = self.client.get("/api/groups/", **self.headers(ORGANIZATION_COLLEGE))
        self.assertEqual([item["course_name"] for item in academy.data], ["Academy Group"])
        self.assertEqual([item["course_name"] for item in college.data], ["Math"])

    def test_college_group_cannot_use_academy_mentor(self):
        response = self.client.post("/api/groups/", {"course_name": "Invalid", "mentor": self.academy_mentor.pk, "study_days": Group.MON_FRI}, format="json", **self.headers(ORGANIZATION_COLLEGE))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_can_create_one_mentor_for_both_organizations(self):
        response = self.client.post(
            "/api/mentors/",
            {
                "full_name": "Shared Mentor",
                "username": "shared-mentor",
                "password": "pass-12345",
                "email": "shared@example.com",
                "organizations": [ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE],
            },
            format="json",
            **self.headers(ORGANIZATION_ACADEMY),
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mentor = MentorProfile.objects.get(user__username="shared-mentor")
        self.assertSetEqual(
            set(mentor.user.organization_accesses.values_list("organization_type", flat=True)),
            {ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE},
        )

        academy = self.client.get("/api/mentors/", **self.headers(ORGANIZATION_ACADEMY))
        college = self.client.get("/api/mentors/", **self.headers(ORGANIZATION_COLLEGE))
        self.assertIn(mentor.pk, {item["id"] for item in academy.data})
        self.assertIn(mentor.pk, {item["id"] for item in college.data})

        college_group = self.client.post(
            "/api/groups/",
            {
                "course_name": "Shared Mentor Subject",
                "mentor": mentor.pk,
                "study_days": Group.MON_FRI,
            },
            format="json",
            **self.headers(ORGANIZATION_COLLEGE),
        )
        self.assertEqual(college_group.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(mentor.user)
        me = self.client.get("/api/me/")
        self.assertSetEqual(set(me.data["organizations"]), {ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE})
        mentor_college_groups = self.client.get("/api/groups/", **self.headers(ORGANIZATION_COLLEGE))
        self.assertEqual([item["course_name"] for item in mentor_college_groups.data], ["Shared Mentor Subject"])

    def test_admin_can_update_mentor_organization_access(self):
        response = self.client.patch(
            f"/api/mentors/{self.academy_mentor.pk}/",
            {"organizations": [ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE]},
            format="json",
            **self.headers(ORGANIZATION_ACADEMY),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertSetEqual(
            set(self.academy_mentor.user.organization_accesses.values_list("organization_type", flat=True)),
            {ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE},
        )
        college = self.client.get("/api/mentors/", **self.headers(ORGANIZATION_COLLEGE))
        self.assertIn(self.academy_mentor.pk, {item["id"] for item in college.data})

    def test_student_cannot_use_group_from_other_organization(self):
        response = self.client.post("/api/students/", {"full_name": "Wrong Student", "username": "wrong-student", "password": "pass-12345", "email": "", "parent_name": "Parent", "parent_phone": "+996700000001", "group": self.academy_group.pk}, format="json", **self.headers(ORGANIZATION_COLLEGE))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_college_student_is_created_with_multiple_groups(self):
        second_group = Group.objects.create(course_name="English", mentor=self.college_mentor, study_days=Group.MON_FRI, organization_type=ORGANIZATION_COLLEGE)
        response = self.client.post("/api/students/", {"full_name": "College Student", "username": "college-student", "password": "pass-12345", "parent_name": "Parent", "parent_phone": "+996700000003", "group": self.college_group.pk, "college_course": "1", "college_groups": [self.college_group.pk, second_group.pk]}, format="json", **self.headers(ORGANIZATION_COLLEGE))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        student = StudentProfile.objects.get(user__username="college-student")
        self.assertEqual(student.organization_type, ORGANIZATION_COLLEGE)
        self.assertSetEqual(set(student.college_groups.values_list("pk", flat=True)), {self.college_group.pk, second_group.pk})

    def test_college_student_dashboard_can_show_all_or_one_group(self):
        second_group = Group.objects.create(
            course_name="English",
            mentor=self.college_mentor,
            study_days=Group.MON_FRI,
            organization_type=ORGANIZATION_COLLEGE,
        )
        student_user = User.objects.create_user(
            username="college-dashboard-student",
            password="pass-12345",
            full_name="College Dashboard Student",
            role=User.ROLE_STUDENT,
        )
        UserOrganizationAccess.objects.create(user=student_user, organization_type=ORGANIZATION_COLLEGE)
        student = StudentProfile.objects.create(
            user=student_user,
            parent_name="Parent",
            parent_phone="+996700000004",
            group=self.college_group,
            organization_type=ORGANIZATION_COLLEGE,
            college_course="1",
        )
        student.college_groups.set([self.college_group, second_group])
        today = timezone.localdate()
        math_lesson = Lesson.objects.create(group=self.college_group, lesson_date=today.replace(day=1), topic="Math lesson")
        english_lesson = Lesson.objects.create(group=second_group, lesson_date=today.replace(day=2), topic="English lesson")
        LessonRecord.objects.create(student=student, lesson=math_lesson, grade="5")
        LessonRecord.objects.create(student=student, lesson=english_lesson, grade="3")

        self.client.force_authenticate(student_user)
        response = self.client.get("/api/dashboard/", **self.headers(ORGANIZATION_COLLEGE))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        scopes = {scope["label"]: scope for scope in response.data["student_stat_scopes"]}
        self.assertSetEqual(set(scopes), {"Все группы", "Math", "English"})
        month_value = today.strftime("%Y-%m")
        all_month = next(month for month in scopes["Все группы"]["monthly_stats"] if month["value"] == month_value)
        math_month = next(month for month in scopes["Math"]["monthly_stats"] if month["value"] == month_value)
        english_month = next(month for month in scopes["English"]["monthly_stats"] if month["value"] == month_value)
        self.assertEqual(all_month["grades_count"], 2)
        self.assertEqual(all_month["average_grade"], 4.0)
        self.assertEqual(math_month["grades_count"], 1)
        self.assertEqual(english_month["grades_count"], 1)

    def test_admin_can_view_and_edit_one_student_gradebook_across_all_groups(self):
        second_group = Group.objects.create(
            course_name="English",
            mentor=self.college_mentor,
            study_days=Group.MON_FRI,
            organization_type=ORGANIZATION_COLLEGE,
        )
        student_user = User.objects.create_user(
            username="personal-gradebook-student",
            password="pass-12345",
            full_name="Personal Gradebook Student",
            role=User.ROLE_STUDENT,
        )
        student = StudentProfile.objects.create(
            user=student_user,
            parent_name="Parent",
            parent_phone="+996700000005",
            group=self.college_group,
            organization_type=ORGANIZATION_COLLEGE,
            college_course="1",
        )
        student.college_groups.set([self.college_group, second_group])
        month = timezone.localdate().replace(day=1)
        math_lesson = Lesson.objects.create(group=self.college_group, lesson_date=month, topic="Math")
        english_lesson = Lesson.objects.create(group=second_group, lesson_date=month.replace(day=2), topic="English")

        response = self.client.get(
            f"/api/students/{student.pk}/gradebook/?month={month:%Y-%m}",
            **self.headers(ORGANIZATION_COLLEGE),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["student"]["full_name"], "Personal Gradebook Student")
        self.assertSetEqual({row["subject"] for row in response.data["rows"]}, {"Math", "English"})

        group_detail = self.client.get(
            f"/api/groups/{second_group.pk}/",
            **self.headers(ORGANIZATION_COLLEGE),
        )
        self.assertEqual(group_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(group_detail.data["students_count"], 1)
        self.assertEqual(group_detail.data["students"][0]["id"], student.pk)

        group_gradebook = self.client.get(
            f"/api/groups/{second_group.pk}/gradebook/?month={month:%Y-%m}",
            **self.headers(ORGANIZATION_COLLEGE),
        )
        self.assertEqual(group_gradebook.status_code, status.HTTP_200_OK)
        self.assertEqual(group_gradebook.data["rows"][0]["student"]["id"], student.pk)

        response = self.client.post(
            f"/api/students/{student.pk}/gradebook/",
            {
                "month": month.strftime("%Y-%m"),
                "entries": [
                    {"group": self.college_group.pk, "date": month.isoformat(), "grade": "5"},
                    {"group": second_group.pk, "date": month.replace(day=2).isoformat(), "grade": "Н"},
                ],
            },
            format="json",
            **self.headers(ORGANIZATION_COLLEGE),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(LessonRecord.objects.filter(student=student, lesson=math_lesson, grade="5").exists())
        self.assertTrue(LessonRecord.objects.filter(student=student, lesson=english_lesson, grade="Н").exists())

        self.client.force_authenticate(self.college_mentor.user)
        forbidden = self.client.get(
            f"/api/students/{student.pk}/gradebook/?month={month:%Y-%m}",
            **self.headers(ORGANIZATION_COLLEGE),
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_without_college_access_receives_403(self):
        student_user = User.objects.create_user(username="academy-student", password="pass-12345", full_name="Academy Student", role=User.ROLE_STUDENT)
        StudentProfile.objects.create(user=student_user, parent_name="Parent", parent_phone="+996700000002", group=self.academy_group, organization_type=ORGANIZATION_ACADEMY)
        self.client.force_authenticate(student_user)
        response = self.client.get("/api/groups/", **self.headers(ORGANIZATION_COLLEGE))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
