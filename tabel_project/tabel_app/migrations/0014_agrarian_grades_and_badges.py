import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


DEFAULT_BADGES = (
    ("Звезда", "⭐", "За заметный результат или выдающуюся работу."),
    ("Похвала", "👏", "За активность и хорошую работу на занятии."),
    ("Достижение", "🏆", "За важное учебное достижение."),
    ("Отличная работа", "🔥", "За работу особенно высокого качества."),
    ("Усилие", "💪", "За настойчивость и приложенные усилия."),
    ("Цель достигнута", "🎯", "За достижение поставленной цели."),
    ("Прогресс", "🚀", "За заметный прогресс в обучении."),
    ("Хорошая идея", "💡", "За полезную или оригинальную идею."),
)


def seed_default_badges(apps, schema_editor):
    Badge = apps.get_model("tabel_app", "Badge")
    for sort_order, (name, icon, description) in enumerate(DEFAULT_BADGES, start=1):
        Badge.objects.get_or_create(
            name=name,
            defaults={
                "icon": icon,
                "description": description,
                "sort_order": sort_order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tabel_app", "0013_college_branches"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="lessonrecord",
            unique_together=set(),
        ),
        migrations.AddField(
            model_name="lessonrecord",
            name="author",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="authored_lesson_records",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="lessonrecord",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="lessonrecord",
            name="sequence",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="lessonrecord",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="lessonrecord",
            constraint=models.UniqueConstraint(
                fields=("student", "lesson", "sequence"),
                name="unique_student_lesson_record_sequence",
            ),
        ),
        migrations.AlterModelOptions(
            name="lessonrecord",
            options={
                "ordering": (
                    "student__user__full_name",
                    "lesson__lesson_date",
                    "sequence",
                    "id",
                )
            },
        ),
        migrations.CreateModel(
            name="Badge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("icon", models.CharField(max_length=32)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("sort_order", "name", "id")},
        ),
        migrations.CreateModel(
            name="StudentBadge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("comment", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("badge", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="awards", to="tabel_app.badge")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="student_badges", to="tabel_app.group")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="badges", to="tabel_app.studentprofile")),
                ("teacher", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="awarded_student_badges", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.RunPython(seed_default_badges, migrations.RunPython.noop),
    ]
