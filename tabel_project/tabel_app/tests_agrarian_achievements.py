from datetime import date

from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    Badge,
    Group,
    LessonRecord,
    MentorProfile,
    StudentBadge,
    StudentProfile,
    User,
)
from .report import build_student_month_report


class AgrarianGradesAndBadgesApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="agrarian-admin", role=User.ROLE_ADMIN)
        self.mentor_user = User.objects.create_user(username="agrarian-mentor", role=User.ROLE_MENTOR)
        self.mentor = MentorProfile.objects.create(user=self.mentor_user, organization_type="college")
        self.group = Group.objects.create(
            course_name="Агрономия",
            mentor=self.mentor,
            study_days=Group.MON_FRI,
            organization_type="college",
            college_branch="agrarian",
            college_course="1",
        )
        self.student_user = User.objects.create_user(username="agrarian-student", role=User.ROLE_STUDENT)
        self.student = StudentProfile.objects.create(
            user=self.student_user,
            parent_phone="+996700001001",
            group=self.group,
            organization_type="college",
            college_branch="agrarian",
            college_course="1",
        )
        self.student.college_groups.add(self.group)
        self.second_student = StudentProfile.objects.create(
            user=User.objects.create_user(username="agrarian-student-two", role=User.ROLE_STUDENT),
            parent_phone="+996700001002",
            group=self.group,
            organization_type="college",
            college_branch="agrarian",
            college_course="1",
        )
        self.second_student.college_groups.add(self.group)
        self.headers = {
            "HTTP_X_ORGANIZATION_TYPE": "college",
            "HTTP_X_COLLEGE_BRANCH": "agrarian",
        }
        self.client.force_authenticate(self.mentor_user)

    def create_grade(self, *, student=None, day="2026-09-22", score="5", comment="Отлично"):
        return self.client.post(
            "/api/grade-records/",
            {
                "student": (student or self.student).pk,
                "group": self.group.pk,
                "date": day,
                "score": score,
                "comment": comment,
            },
            format="json",
            **self.headers,
        )

    def test_one_two_and_ten_grades_on_same_day_are_separate_records(self):
        comments = [f"Комментарий {index}" for index in range(1, 11)]
        responses = [
            self.create_grade(score=str(5 - index % 4), comment=comment)
            for index, comment in enumerate(comments)
        ]

        self.assertTrue(all(response.status_code == status.HTTP_201_CREATED for response in responses))
        self.assertEqual(len({response.data["id"] for response in responses}), 10)
        self.assertEqual([response.data["sequence"] for response in responses], list(range(1, 11)))
        records = LessonRecord.objects.filter(student=self.student, lesson__lesson_date=date(2026, 9, 22))
        self.assertEqual(records.count(), 10)
        self.assertEqual(list(records.order_by("sequence").values_list("comment", flat=True)), comments)
        self.assertTrue(all(record.author_id == self.mentor_user.pk for record in records))

    def test_different_days_and_multiple_students_do_not_conflict(self):
        first = self.create_grade(day="2026-09-22", comment="Первый день")
        second = self.create_grade(day="2026-09-23", comment="Второй день")
        other_student = self.create_grade(student=self.second_student, day="2026-09-22", comment="Другой студент")

        self.assertEqual([first.status_code, second.status_code, other_student.status_code], [201, 201, 201])
        self.assertEqual(LessonRecord.objects.count(), 3)
        self.assertEqual(LessonRecord.objects.filter(student=self.student).count(), 2)
        self.assertEqual(LessonRecord.objects.filter(student=self.second_student).count(), 1)

    def test_each_grade_can_be_retrieved_changed_and_deleted_by_id(self):
        first = self.create_grade(score="5", comment="Первая")
        second = self.create_grade(score="4", comment="Вторая")

        detail = self.client.get(f"/api/grade-records/{first.data['id']}/", **self.headers)
        changed = self.client.patch(
            f"/api/grade-records/{first.data['id']}/",
            {"score": "3", "comment": "Исправленный комментарий"},
            format="json",
            **self.headers,
        )
        deleted = self.client.delete(f"/api/grade-records/{second.data['id']}/", **self.headers)

        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(changed.status_code, status.HTTP_200_OK)
        self.assertEqual(changed.data["score"], "3")
        self.assertEqual(changed.data["comment"], "Исправленный комментарий")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(LessonRecord.objects.filter(pk=first.data["id"]).exists())
        self.assertFalse(LessonRecord.objects.filter(pk=second.data["id"]).exists())

    def test_multiple_badges_are_independent_history_entries(self):
        badges = list(Badge.objects.filter(is_active=True)[:3])
        responses = [
            self.client.post(
                "/api/student-badges/",
                {
                    "student": self.student.pk,
                    "group": self.group.pk,
                    "badge": badge.pk,
                    "comment": f"Причина {index}",
                },
                format="json",
                **self.headers,
            )
            for index, badge in enumerate(badges, start=1)
        ]

        self.assertEqual([response.status_code for response in responses], [201, 201, 201])
        self.assertEqual(StudentBadge.objects.filter(student=self.student).count(), 3)
        self.assertEqual(
            set(StudentBadge.objects.values_list("comment", flat=True)),
            {"Причина 1", "Причина 2", "Причина 3"},
        )

    def test_student_can_read_but_cannot_mutate_grades_or_badges(self):
        grade = self.create_grade()
        badge = Badge.objects.filter(is_active=True).first()
        award = self.client.post(
            "/api/student-badges/",
            {"student": self.student.pk, "group": self.group.pk, "badge": badge.pk},
            format="json",
            **self.headers,
        )
        self.client.force_authenticate(self.student_user)

        grade_list = self.client.get("/api/grade-records/", **self.headers)
        badge_list = self.client.get("/api/student-badges/", **self.headers)
        create_grade = self.create_grade(comment="Нельзя")
        change_grade = self.client.patch(
            f"/api/grade-records/{grade.data['id']}/", {"comment": "Нельзя"}, format="json", **self.headers,
        )
        create_badge = self.client.post(
            "/api/student-badges/",
            {"student": self.student.pk, "group": self.group.pk, "badge": badge.pk},
            format="json",
            **self.headers,
        )
        delete_badge = self.client.delete(f"/api/student-badges/{award.data['id']}/", **self.headers)

        self.assertEqual(grade_list.status_code, 200)
        self.assertEqual(len(grade_list.data), 1)
        self.assertEqual(badge_list.status_code, 200)
        self.assertEqual(len(badge_list.data), 1)
        self.assertEqual(create_grade.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(change_grade.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create_badge.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete_badge.status_code, status.HTTP_403_FORBIDDEN)

    def test_new_endpoints_are_forbidden_in_kuwait_college(self):
        kuwait_headers = {
            "HTTP_X_ORGANIZATION_TYPE": "college",
            "HTTP_X_COLLEGE_BRANCH": "kuwait",
        }
        self.client.force_authenticate(self.admin)

        self.assertEqual(self.client.get("/api/grade-records/", **kuwait_headers).status_code, 403)
        self.assertEqual(self.client.get("/api/badges/", **kuwait_headers).status_code, 403)
        self.assertEqual(self.client.get("/api/student-badges/", **kuwait_headers).status_code, 403)

    def test_group_gradebook_shows_best_grade_and_total_count(self):
        created = self.create_grade(score="4", comment="Первая")
        second = self.create_grade(score="5", comment="Вторая")

        response = self.client.get(
            "/api/groups/{}/gradebook/?month=2026-09".format(self.group.pk),
            **self.headers,
        )
        cell = next(item for item in response.data["rows"][0]["cells"] if item["date"] == "2026-09-22")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(cell["grade"], "5")
        self.assertEqual(cell["best_grade"], "5")
        self.assertEqual(cell["grade_count"], 2)
        self.assertEqual([item["id"] for item in cell["grade_entries"]], [created.data["id"], second.data["id"]])
        self.assertTrue(response.data["agrarian_features"])

        self.client.force_authenticate(self.admin)
        admin_response = self.client.get(
            "/api/groups/{}/gradebook/?month=2026-09".format(self.group.pk),
            **self.headers,
        )
        admin_cell = next(item for item in admin_response.data["rows"][0]["cells"] if item["date"] == "2026-09-22")
        self.assertEqual(admin_cell["best_grade"], "5")
        self.assertEqual(admin_cell["grade_count"], 2)

    def test_admin_student_gradebook_shows_best_grade_and_total_count(self):
        self.create_grade(score="3", comment="Первая")
        self.create_grade(score="5", comment="Вторая")
        self.create_grade(score="4", comment="Третья")
        self.client.force_authenticate(self.admin)

        response = self.client.get(
            f"/api/students/{self.student.pk}/gradebook/?month=2026-09",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["rows"][0]["grades"]["2026-09-22"], "5")
        self.assertEqual(response.data["rows"][0]["grade_counts"]["2026-09-22"], 3)

    def test_student_history_and_monthly_report_include_all_grades(self):
        self.create_grade(score="5", comment="Отлично решил задачу")
        self.create_grade(score="4", comment="Была небольшая ошибка")
        badge = Badge.objects.filter(is_active=True).first()
        self.client.post(
            "/api/student-badges/",
            {"student": self.student.pk, "group": self.group.pk, "badge": badge.pk, "comment": "Отличная работа"},
            format="json",
            **self.headers,
        )
        self.client.force_authenticate(self.student_user)

        history = self.client.get("/api/college-gradebook/?month=2026-09", **self.headers)
        report = build_student_month_report(self.student, date(2026, 9, 1))
        entries = history.data["rows"][0]["grade_entries"]["2026-09-22"]

        self.assertEqual(history.status_code, 200)
        self.assertEqual([entry["score"] for entry in entries], ["5", "4"])
        self.assertEqual(
            [entry["comment"] for entry in entries],
            ["Отлично решил задачу", "Была небольшая ошибка"],
        )
        self.assertEqual(len(history.data["badges"]), 1)
        self.assertEqual(history.data["rows"][0]["grades"]["2026-09-22"], "5")
        self.assertEqual(history.data["rows"][0]["grade_counts"]["2026-09-22"], 2)
        self.assertEqual(report["summary"]["numeric_grades_count"], 2)
        self.assertEqual(report["summary"]["marked_lessons_count"], 1)
        self.assertEqual(report["summary"]["average_grade"], 4.5)
