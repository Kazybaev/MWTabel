from datetime import date, timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (
    COLLEGE_BRANCH_AGRARIAN,
    COLLEGE_BRANCH_KUWAIT,
    ORGANIZATION_ACADEMY,
    ORGANIZATION_COLLEGE,
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    StudentProfile,
    User,
)
from .rating import ABSENCE_PENALTY, RATING_LIMIT, build_student_rating, grade_points


class StudentRatingTests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.admin = User.objects.create_user(username="admin", password="pass-12345", full_name="Admin", role=User.ROLE_ADMIN)
        mentor_user = User.objects.create_user(username="mentor", password="pass-12345", full_name="Mentor", role=User.ROLE_MENTOR)
        self.mentor_user = mentor_user
        self.mentor = MentorProfile.objects.create(user=mentor_user, organization_type=ORGANIZATION_ACADEMY)
        college_mentor_user = User.objects.create_user(username="cmentor", password="pass-12345", full_name="C Mentor", role=User.ROLE_MENTOR)
        self.college_mentor = MentorProfile.objects.create(user=college_mentor_user, organization_type=ORGANIZATION_COLLEGE)

        self.academy_group = self.make_group("Python", ORGANIZATION_ACADEMY)
        self.kuwait_group = self.make_group("Math", ORGANIZATION_COLLEGE, COLLEGE_BRANCH_KUWAIT)
        self.agrarian_group = self.make_group("Biology", ORGANIZATION_COLLEGE, COLLEGE_BRANCH_AGRARIAN)

        self.alice = self.make_student("alice", "Alice", self.academy_group)
        self.bob = self.make_student("bob", "Bob", self.academy_group)
        self.carl = self.make_student("carl", "Carl", self.academy_group)
        self.kuwait_student = self.make_student("kira", "Kira", self.kuwait_group)
        self.agrarian_student = self.make_student("aziz", "Aziz", self.agrarian_group)

    def make_group(self, name, organization, branch=COLLEGE_BRANCH_KUWAIT):
        mentor = self.college_mentor if organization == ORGANIZATION_COLLEGE else self.mentor
        return Group.objects.create(
            course_name=name,
            mentor=mentor,
            study_days=Group.MON_FRI,
            organization_type=organization,
            college_branch=branch,
        )

    def make_student(self, username, name, group):
        user = User.objects.create_user(username=username, password="pass-12345", full_name=name, role=User.ROLE_STUDENT)
        return StudentProfile.objects.create(
            user=user,
            parent_phone="+996700000001",
            group=group,
            organization_type=group.organization_type,
            college_branch=group.college_branch,
        )

    def grade(self, student, grade, lesson_date=None, sequence=1, group=None):
        lesson, _ = Lesson.objects.get_or_create(group=group or student.group, lesson_date=lesson_date or self.today)
        return LessonRecord.objects.create(student=student, lesson=lesson, grade=grade, sequence=sequence)

    def headers(self, organization=ORGANIZATION_ACADEMY, branch=COLLEGE_BRANCH_KUWAIT):
        return {"HTTP_X_ORGANIZATION_TYPE": organization, "HTTP_X_COLLEGE_BRANCH": branch}

    def test_points_reward_grades_and_penalize_absences(self):
        self.assertEqual(grade_points("5"), 5)
        self.assertEqual(grade_points("4"), 4)
        self.assertEqual(grade_points("3"), -1)
        self.assertEqual(grade_points("2"), -2)
        self.assertEqual(grade_points("Н"), ABSENCE_PENALTY)
        self.assertEqual(grade_points("н"), ABSENCE_PENALTY)
        self.assertEqual(grade_points(""), 0)

    def test_ranking_orders_by_points_and_absence_moves_student_down(self):
        self.grade(self.alice, "5")
        self.grade(self.bob, "4")
        self.grade(self.carl, "5")
        self.grade(self.carl, "Н", self.today.replace(day=1) if self.today.day > 1 else self.today, sequence=2)

        rating = build_student_rating(self.bob, ORGANIZATION_ACADEMY, None, today=self.today)

        names = [entry["full_name"] for entry in rating["top"]]
        self.assertEqual(names, ["Alice", "Bob", "Carl"])
        self.assertEqual([entry["points"] for entry in rating["top"]], [5, 4, 5 + ABSENCE_PENALTY])
        self.assertEqual(rating["me"]["full_name"], "Bob")
        self.assertTrue(rating["me"]["is_me"])
        self.assertEqual(sum(entry["is_me"] for entry in rating["top"]), 1)
        self.assertEqual(rating["scope_label"], "Академия")

    def test_academy_and_each_college_branch_are_ranked_separately(self):
        for student in (self.alice, self.kuwait_student, self.agrarian_student):
            self.grade(student, "5")

        academy = build_student_rating(self.alice, ORGANIZATION_ACADEMY, None, today=self.today)
        kuwait = build_student_rating(self.kuwait_student, ORGANIZATION_COLLEGE, COLLEGE_BRANCH_KUWAIT, today=self.today)
        agrarian = build_student_rating(self.agrarian_student, ORGANIZATION_COLLEGE, COLLEGE_BRANCH_AGRARIAN, today=self.today)

        self.assertEqual({entry["full_name"] for entry in academy["top"]}, {"Alice", "Bob", "Carl"})
        self.assertEqual([entry["full_name"] for entry in kuwait["top"]], ["Kira"])
        self.assertEqual([entry["full_name"] for entry in agrarian["top"]], ["Aziz"])
        self.assertEqual(kuwait["scope_label"], "Кувейтский колледж")
        self.assertEqual(agrarian["scope_label"], "Аграрный колледж")

    def test_college_top_includes_active_students_with_archived_primary_subjects(self):
        branch = COLLEGE_BRANCH_KUWAIT
        english = self.make_group("English", ORGANIZATION_COLLEGE, branch)
        german = self.make_group("German", ORGANIZATION_COLLEGE, branch)
        cyber = self.make_group("Cybersecurity", ORGANIZATION_COLLEGE, branch)
        it = self.make_group("IT", ORGANIZATION_COLLEGE, branch)
        second_cohort = self.make_group("Second cohort", ORGANIZATION_COLLEGE, branch)
        current_students = [self.kuwait_student] + [
            self.make_student(f"current-{i}", f"Current {i}", second_cohort) for i in range(2)
        ]
        continuing_students = [
            self.make_student(f"continuing-{i}", f"Continuing {i}", cyber) for i in range(10)
        ]
        for student in continuing_students:
            student.college_groups.add(cyber, english, german, it)

        archived = self.make_student("archived-college", "Archived", cyber)
        archived.college_groups.add(cyber)
        self.client.force_authenticate(self.admin)
        headers = self.headers(ORGANIZATION_COLLEGE, branch)
        response = self.client.post(f"/api/groups/{cyber.pk}/archive/", {}, format="json", **headers)
        self.assertEqual(response.status_code, 200)
        archived.refresh_from_db()
        self.assertIsNotNone(archived.archived_at)

        student = continuing_students[0]
        previous_month = self.today.replace(day=1) - timedelta(days=1)
        self.grade(student, "5", group=english)
        self.grade(student, "4", group=german)
        self.grade(student, "Н", group=it)
        self.grade(student, "5", lesson_date=previous_month, group=cyber)
        self.grade(student, "5", group=self.agrarian_group)
        self.grade(student, "5", group=self.academy_group)
        for subject in (cyber, english, it):
            self.grade(continuing_students[1], "5", lesson_date=previous_month, group=subject)

        self.client.force_authenticate(student.user)
        month = self.client.get("/api/rating/?period=month", **headers)
        all_time = self.client.get("/api/rating/?period=all", **headers)
        expected_names = {person.user.full_name for person in current_students + continuing_students}
        for response in (month, all_time):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["participants_count"], 13)
            self.assertEqual(len(response.data["top"]), 13)
            self.assertEqual({entry["full_name"] for entry in response.data["top"]}, expected_names)

        self.assertEqual(month.data["me"]["points"], 6)
        self.assertEqual(month.data["me"]["grades_count"], 2)
        self.assertEqual(month.data["me"]["absences_count"], 1)
        self.assertEqual(all_time.data["me"]["points"], 11)
        self.assertEqual(all_time.data["me"]["grades_count"], 3)
        self.assertEqual(month.data["top"][0]["full_name"], student.user.full_name)
        self.assertEqual(all_time.data["top"][0]["full_name"], continuing_students[1].user.full_name)

    def test_new_grade_today_shows_upward_movement(self):
        earlier = timezone.now() - timedelta(days=2)
        old = self.grade(self.bob, "5")
        LessonRecord.objects.filter(pk=old.pk).update(created_at=earlier)
        self.grade(self.alice, "5")
        self.grade(self.alice, "4", sequence=2)

        rating = build_student_rating(self.alice, ORGANIZATION_ACADEMY, None, today=self.today)

        self.assertEqual(rating["me"]["rank"], 1)
        self.assertEqual(rating["me"]["rank_change"], 1)
        bob = next(entry for entry in rating["top"] if entry["full_name"] == "Bob")
        self.assertEqual(bob["rank_change"], -1)

    def test_month_period_ignores_previous_months_but_all_time_counts_them(self):
        previous_month_day = self.today.replace(day=1) - timedelta(days=1)
        self.grade(self.bob, "5", previous_month_day)
        self.grade(self.alice, "4")

        month = build_student_rating(self.alice, ORGANIZATION_ACADEMY, None, today=self.today)
        all_time = build_student_rating(self.alice, ORGANIZATION_ACADEMY, None, period="all", today=self.today)

        self.assertEqual(month["top"][0]["full_name"], "Alice")
        self.assertEqual(all_time["top"][0]["full_name"], "Bob")

    def test_archived_students_are_excluded(self):
        self.grade(self.carl, "5")
        self.carl.archived_at = timezone.now()
        self.carl.save(update_fields=["archived_at"])

        rating = build_student_rating(self.alice, ORGANIZATION_ACADEMY, None, today=self.today)

        self.assertNotIn("Carl", [entry["full_name"] for entry in rating["top"]])
        self.assertEqual(rating["participants_count"], 2)

    def test_me_is_returned_even_outside_top_limit(self):
        with patch("tabel_app.rating.RATING_LIMIT", 1):
            self.grade(self.alice, "5")
            rating = build_student_rating(self.carl, ORGANIZATION_ACADEMY, None, today=self.today)

        self.assertEqual(len(rating["top"]), 1)
        self.assertEqual(rating["me"]["full_name"], "Carl")
        self.assertGreater(rating["me"]["rank"], 1)
        self.assertEqual(RATING_LIMIT, 100)

    def test_api_returns_rating_for_student(self):
        self.grade(self.alice, "5")
        self.client.force_authenticate(self.alice.user)

        response = self.client.get("/api/rating/", **self.headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["me"]["rank"], 1)
        self.assertNotIn("parent_phone", str(response.data))

    def test_api_college_student_sees_only_own_branch(self):
        self.client.force_authenticate(self.agrarian_student.user)

        own = self.client.get("/api/rating/", **self.headers(ORGANIZATION_COLLEGE, COLLEGE_BRANCH_AGRARIAN))
        other_branch = self.client.get("/api/rating/", **self.headers(ORGANIZATION_COLLEGE, COLLEGE_BRANCH_KUWAIT))
        academy = self.client.get("/api/rating/", **self.headers(ORGANIZATION_ACADEMY))

        self.assertEqual(own.status_code, 200)
        self.assertEqual([entry["full_name"] for entry in own.data["top"]], ["Aziz"])
        self.assertEqual(other_branch.status_code, 403)
        self.assertEqual(academy.status_code, 403)

    def test_api_forbidden_for_admin_mentor_and_anonymous(self):
        self.assertEqual(self.client.get("/api/rating/", **self.headers()).status_code, 401)
        for user in (self.admin, self.mentor_user):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get("/api/rating/", **self.headers()).status_code, 403)
