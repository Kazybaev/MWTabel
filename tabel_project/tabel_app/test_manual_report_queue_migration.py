from datetime import date
from unittest import skipUnless

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


@skipUnless(connection.vendor == "postgresql", "Migration rehearsal requires PostgreSQL.")
class ManualReportQueueMigrationTests(TransactionTestCase):
    migrate_from = ("tabel_app", "0017_enforce_college_branches")
    migrate_to = ("tabel_app", "0018_manual_report_queue_safety")

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.legacy_ids = self._seed_legacy_queue(old_apps)

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        super().tearDown()

    def _seed_legacy_queue(self, apps):
        User = apps.get_model("tabel_app", "User")
        Mentor = apps.get_model("tabel_app", "MentorProfile")
        Group = apps.get_model("tabel_app", "Group")
        Student = apps.get_model("tabel_app", "StudentProfile")
        Batch = apps.get_model("tabel_app", "MonthlyStudentReportBatch")
        Item = apps.get_model("tabel_app", "MonthlyStudentReportBatchItem")

        admin = User.objects.create(
            username="migration-admin", password="", full_name="Migration Admin", role="ADMIN"
        )
        mentor_user = User.objects.create(
            username="migration-mentor", password="", full_name="Migration Mentor", role="MENTOR"
        )
        mentor = Mentor.objects.create(user=mentor_user)
        group = Group.objects.create(
            course_name="Synthetic Academy",
            study_days="MON_WED_SAT",
            mentor=mentor,
            organization_type="academy",
        )
        student_user = User.objects.create(
            username="migration-student", password="", full_name="Migration Student", role="STUDENT"
        )
        student = Student.objects.create(
            user=student_user,
            parent_name="Synthetic Parent",
            parent_phone="+996700000001",
            group=group,
            organization_type="academy",
        )
        batches = [
            Batch.objects.create(
                month=date(2026, 9, 1),
                organization_type="academy",
                created_by=admin,
                requested_filters={"synthetic_label": label},
            )
            for label in ("B5", "B6")
        ]
        items = [
            Item.objects.create(
                batch=batch,
                student=student,
                month=date(2026, 9, 1),
                status="queued",
            )
            for batch in batches
        ]
        return [item.pk for item in items]

    def test_duplicate_active_legacy_jobs_are_backfilled_before_unique_constraint(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        Item = apps.get_model("tabel_app", "MonthlyStudentReportBatchItem")

        rows = list(
            Item.objects.filter(pk__in=self.legacy_ids)
            .order_by("id")
            .values("status", "dedupe_key", "requires_operator_review")
        )
        self.assertEqual([row["status"] for row in rows], ["queued", "queued"])
        self.assertTrue(all(row["requires_operator_review"] for row in rows))
        self.assertTrue(all(len(row["dedupe_key"]) == 64 for row in rows))
        self.assertEqual(len({row["dedupe_key"] for row in rows}), 2)

        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Item._meta.db_table
            )
        self.assertTrue(constraints["unique_active_monthly_report_context"]["unique"])
