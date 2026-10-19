from datetime import date

from rest_framework.test import APITestCase

from .models import CollegeGroup, Group, Lesson, LessonRecord, MentorProfile, StudentProfile, User
from .report import build_dify_inputs, build_student_month_report
from .report_delivery import build_report_message_text


class CollegeGroupHierarchyTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="hierarchy-admin", role="ADMIN")
        cls.mentor = MentorProfile.objects.create(
            user=User.objects.create_user(username="hierarchy-mentor", role="MENTOR"),
            organization_type="college",
        )
        cls.main = CollegeGroup.objects.create(name="ПИ-4-25")
        cls.other = CollegeGroup.objects.create(name="ПИ-5-25")
        cls.subjects = [Group.objects.create(
            course_name=name, mentor=cls.mentor, main_group=cls.main,
            organization_type="college", study_days=Group.MON_FRI,
        ) for name in ("Fullstack", "Жасалма Интеллект", "Англис тили")]
        cls.student = StudentProfile.objects.create(
            user=User.objects.create_user(username="hierarchy-student", full_name="Таалайбеков Эрбол", role="STUDENT"),
            group=cls.subjects[0], organization_type="college", parent_phone="+996700000001",
        )
        cls.student.college_groups.set(cls.subjects)

    def setUp(self):
        self.client.force_authenticate(self.admin)
        self.client.credentials(HTTP_X_ORGANIZATION_TYPE="college")

    def test_main_group_needs_only_name_and_is_college_only(self):
        response = self.client.post("/api/college-groups/", {"name": "ПИ-6-25"})
        self.assertEqual(response.status_code, 201)
        response = self.client.patch(f"/api/college-groups/{response.data['id']}/", {"name": "ПИ-7-25"})
        self.assertEqual(response.data["name"], "ПИ-7-25")
        self.client.credentials(HTTP_X_ORGANIZATION_TYPE="academy")
        self.assertEqual(self.client.get("/api/college-groups/").status_code, 403)

    def test_student_can_be_created_without_parent_name(self):
        response = self.client.post("/api/students/", {
            "username": "new-hierarchy-student", "full_name": "Новый студент", "password": "example-password",
            "parent_phone": "+996700000002", "group": self.subjects[0].pk,
            "college_groups": [self.subjects[0].pk],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["parent_name"], "")
        self.assertEqual(response.data["main_group_name"], self.main.name)
        response = self.client.patch(f"/api/students/{response.data['id']}/", {"parent_name": ""})
        self.assertEqual(response.status_code, 200, response.data)

    def test_cannot_mix_subgroups_or_move_grades_between_subjects(self):
        foreign = Group.objects.create(course_name="Другой английский", main_group=self.other,
            mentor=self.mentor, organization_type="college", study_days=Group.MON_FRI)
        response = self.client.patch(f"/api/students/{self.student.pk}/", {
            "college_groups": [self.subjects[0].pk, foreign.pk],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        lesson = Lesson.objects.create(group=self.subjects[0], lesson_date=date(2026, 5, 4))
        record = LessonRecord.objects.create(student=self.student, lesson=lesson, grade="5")
        response = self.client.patch(f"/api/students/{self.student.pk}/", {"group": self.subjects[1].pk})
        self.assertEqual(response.status_code, 200, response.data)
        record.refresh_from_db()
        self.assertEqual(record.lesson_id, lesson.pk)

    def test_student_sees_all_own_subgroups_but_cannot_manage_main_groups(self):
        self.client.force_authenticate(self.student.user)
        response = self.client.get("/api/groups/")
        self.assertEqual(len(response.data), 3)
        self.assertEqual(len(self.client.get("/api/college-groups/").data), 1)
        self.assertEqual(self.client.post("/api/college-groups/", {"name": "Forbidden"}).status_code, 403)
        self.assertEqual(self.client.get(f"/api/college-groups/{self.other.pk}/").status_code, 404)
        self.client.force_authenticate(self.mentor.user)
        self.assertEqual(self.client.patch(f"/api/college-groups/{self.main.pk}/", {"name": "Forbidden"}).status_code, 403)

    def test_existing_subgroups_can_be_attached_sequentially(self):
        Group.objects.filter(pk__in=[item.pk for item in self.subjects]).update(main_group=None)
        for subject in self.subjects:
            response = self.client.patch(f"/api/groups/{subject.pk}/", {"main_group": self.main.pk})
            self.assertEqual(response.status_code, 200, response.data)

    def test_report_counts_each_subject_and_unique_absence_dates(self):
        for subject, grades in zip(self.subjects, [("5", "4", "Н"), ("3", "3", "Н"), ("2", "2", "Н")]):
            for day, grade in zip((4, 5, 6), grades):
                lesson = Lesson.objects.create(group=subject, lesson_date=date(2026, 5, day))
                LessonRecord.objects.create(student=self.student, lesson=lesson, grade=grade)
        # Unmarked lessons and marks in another month do not change May counts.
        Lesson.objects.create(group=self.subjects[0], lesson_date=date(2026, 5, 7))
        june = Lesson.objects.create(group=self.subjects[0], lesson_date=date(2026, 6, 1))
        LessonRecord.objects.create(student=self.student, lesson=june, grade="Н")
        report = build_student_month_report(self.student, date(2026, 5, 1))
        subjects = {item["name"]: item for item in report["subjects"]}
        self.assertEqual(subjects["Fullstack"]["grade_counts"], {"5": 1, "4": 1, "3": 0, "2": 0})
        self.assertEqual(subjects["Англис тили"]["grade_counts"]["2"], 2)
        self.assertEqual(report["absence_dates"], ["2026-05-06"])
        self.assertIn("*ПИ-4-25*", report["message_text"])
        self.assertIn("*Таалайбеков Эрбол*", report["message_text"])
        self.assertIn("“5”тен 1 даана", report["message_text"])
        self.assertEqual(report["message_text"].count("6-май"), 1)
        inputs = build_dify_inputs(report)
        self.assertEqual(inputs["message_text"], report["message_text"])
        self.assertEqual(build_report_message_text(report), report["message_text"])
        self.assertEqual(inputs["recipient_phone"], "+996700000001")
        self.assertEqual(inputs["group_name"], "ПИ-4-25")

    def test_report_with_empty_subject_has_zero_counts(self):
        report = build_student_month_report(self.student, date(2026, 5, 1))
        self.assertEqual(len(report["subjects"]), 3)
        self.assertIn("Сабактан калган жок", report["message_text"])
        self.assertTrue(all(sum(subject["grade_counts"].values()) == 0 for subject in report["subjects"]))
