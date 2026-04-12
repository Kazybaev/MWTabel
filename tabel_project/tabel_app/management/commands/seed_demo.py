from django.core.management.base import BaseCommand

from tabel_app.models import Group, Lesson, LessonRecord, MentorProfile, StudentProfile, User


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

        self.stdout.write(self.style.SUCCESS("Demo data created successfully."))
        self.stdout.write("Admin: admin_demo / admin12345")
        self.stdout.write("Mentor: mentor_demo / mentor12345")
        self.stdout.write("Student: student_demo_1 / student12345")
