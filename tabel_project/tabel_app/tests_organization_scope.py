from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    Group,
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

    def test_user_without_college_access_receives_403(self):
        student_user = User.objects.create_user(username="academy-student", password="pass-12345", full_name="Academy Student", role=User.ROLE_STUDENT)
        StudentProfile.objects.create(user=student_user, parent_name="Parent", parent_phone="+996700000002", group=self.academy_group, organization_type=ORGANIZATION_ACADEMY)
        self.client.force_authenticate(student_user)
        response = self.client.get("/api/groups/", **self.headers(ORGANIZATION_COLLEGE))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
