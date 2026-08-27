from django.core.management.base import BaseCommand

from django.utils import timezone

from tabel_app.models import (
    Group,
    Lesson,
    LessonRecord,
    MentorProfile,
    StudentProfile,
    User,
    ORGANIZATION_COLLEGE,
)


class Command(BaseCommand):
    help = "Creates demo users, groups, lessons, and grades for the Tabel frontend."

    def handle(self, *args, **options):
        admin, _ = User.objects.get_or_create(
            username="admin_demo",
            defaults={
                "full_name": "Admin Demo",
                "role": User.ROLE_ADMIN,
                "email": "admin@tabel.local",
            },
        )
        admin.set_password("admin12345")
        admin.save()

        mentor_user, _ = User.objects.get_or_create(
            username="mentor_demo",
            defaults={
                "full_name": "Aizada Mentor",
                "role": User.ROLE_MENTOR,
                "email": "mentor@tabel.local",
            },
        )
        mentor_user.set_password("mentor12345")
        mentor_user.save()
        mentor, _ = MentorProfile.objects.get_or_create(user=mentor_user)

        group, _ = Group.objects.get_or_create(
            course_name="Frontend Bootcamp",
            defaults={
                "mentor": mentor,
                "study_days": Group.MON_WED_SAT,
                "description": "Практическая группа для демонстрации интерфейса.",
            },
        )
        if group.mentor_id != mentor.pk:
            group.mentor = mentor
            group.save(update_fields=["mentor"])

        students = [
            ("student_demo_1", "Nur Student", "parent1@tabel.local", "Aigul Parent", "+996700000011"),
            ("student_demo_2", "Bek Student", "parent2@tabel.local", "Kanat Parent", "+996700000022"),
        ]

        for username, full_name, email, parent_name, parent_phone in students:
            student_user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "full_name": full_name,
                    "role": User.ROLE_STUDENT,
                    "email": email,
                },
            )
            student_user.set_password("student12345")
            student_user.save()
            StudentProfile.objects.update_or_create(
                user=student_user,
                defaults={
                    "group": group,
                    "parent_name": parent_name,
                    "parent_phone": parent_phone,
                },
            )

        lesson, _ = Lesson.objects.get_or_create(
            group=group,
            topic="Командная работа и контроль задач",
        )

        for index, student in enumerate(group.students.select_related("user"), start=1):
            LessonRecord.objects.update_or_create(
                lesson=lesson,
                student=student,
                defaults={
                    "grade": "5" if index == 1 else "4",
                    "comment": "Стабильная работа на уроке",
                },
            )

        # College demo: one student with several subjects for a combined report.
        college_user, _ = User.objects.get_or_create(
            username="college_demo_student",
            defaults={
                "full_name": "Айбек уулу Нурбек",
                "role": User.ROLE_STUDENT,
                "email": "college.student@tabel.local",
            },
        )
        college_user.set_password("student12345")
        college_user.save()
        college_mentor_user, _ = User.objects.get_or_create(
            username="college_mentor_demo",
            defaults={
                "full_name": "Петров Руслан",
                "role": User.ROLE_MENTOR,
                "email": "college.mentor@tabel.local",
            },
        )
        college_mentor_user.set_password("mentor12345")
        college_mentor_user.save()
        college_mentor, _ = MentorProfile.objects.update_or_create(
            user=college_mentor_user,
            defaults={"organization_type": ORGANIZATION_COLLEGE},
        )
        subjects = ["Английский язык", "Кибербезопасность", "Искусственный интеллект", "Немецкий язык"]
        college_groups = []
        for subject in subjects:
            college_group, _ = Group.objects.update_or_create(
                course_name=subject,
                organization_type=ORGANIZATION_COLLEGE,
                defaults={
                    "mentor": college_mentor,
                    "study_days": Group.MON_FRI,
                    "description": "Тестовая группа колледжа для общего отчёта.",
                    "college_course": "1",
                },
            )
            college_groups.append(college_group)

        college_student, _ = StudentProfile.objects.update_or_create(
            user=college_user,
            defaults={
                "group": college_groups[0],
                "parent_name": "Асанбек уулу",
                "parent_phone": "+996700123456",
                "organization_type": ORGANIZATION_COLLEGE,
                "college_course": "1",
            },
        )
        college_student.college_groups.set(college_groups)
        month_start = timezone.localdate().replace(day=1)
        for group_index, college_group in enumerate(college_groups):
            for lesson_index, day in enumerate((4, 11, 18, 25), start=1):
                lesson, _ = Lesson.objects.update_or_create(
                    group=college_group,
                    lesson_date=month_start.replace(day=day),
                    defaults={"topic": f"{college_group.course_name}: тема {lesson_index}"},
                )
                grade = "Н" if lesson_index == 3 and group_index % 2 == 0 else str(5 - (group_index + lesson_index) % 3)
                LessonRecord.objects.update_or_create(
                    lesson=lesson,
                    student=college_student,
                    defaults={
                        "grade": grade,
                        "comment": "Тестовая отметка для общего отчёта",
                    },
                )

        self.stdout.write(self.style.SUCCESS("Demo data created successfully."))
        self.stdout.write("Admin: admin_demo / admin12345")
        self.stdout.write("Mentor: mentor_demo / mentor12345")
        self.stdout.write("Student: student_demo_1 / student12345")
