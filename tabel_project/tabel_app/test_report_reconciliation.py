import hashlib
import io
import json
import os
import stat
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from .management.commands import reconcile_monthly_report_callbacks as reconciliation_command
from .management.commands.reconcile_monthly_report_callbacks import Command

from .models import (
    Group,
    MentorProfile,
    MonthlyStudentReportAttempt,
    MonthlyStudentReportDispatch,
    StudentProfile,
    User,
)


class MonthlyReportReconciliationCommandTests(TestCase):
    def setUp(self):
        mentor_user = User.objects.create_user(
            username="recon-mentor",
            full_name="Recon Mentor",
            role=User.ROLE_MENTOR,
        )
        mentor = MentorProfile.objects.create(user=mentor_user)
        group = Group.objects.create(course_name="Recon Group", mentor=mentor, study_days=Group.MON_WED_SAT)
        self.entries = []
        self.attempts = []
        for index in range(27):
            user = User.objects.create_user(
                username=f"recon-student-{index:02d}",
                full_name=f"Recon Student {index:02d}",
                role=User.ROLE_STUDENT,
            )
            student = StudentProfile.objects.create(
                user=user,
                parent_phone=f"+99670012{index:04d}",
                group=group,
            )
            status = "pending" if index == 26 else "failed"
            report = {
                "student": {"id": student.pk, "username": user.username, "full_name": user.full_name},
                "period": {"month": "2026-08"},
                "summary": {},
            }
            dispatch = MonthlyStudentReportDispatch.objects.create(
                student=student,
                month=date(2026, 8, 1),
                trigger_date=date(2026, 8, 31),
                status=status,
                attempts=1,
                payload=report,
            )
            attempt = MonthlyStudentReportAttempt.objects.create(
                dispatch=dispatch,
                attempt_number=1,
                status=status,
                payload=report,
                workflow_run_id="" if index == 26 else f"run-{index:02d}",
            )
            message_id = f"wamid.reconciled-{index:02d}"
            meta_response = {
                "messaging_product": "whatsapp",
                "messages": [{"id": message_id, "message_status": "accepted"}],
            }
            self.entries.append({
                "student_id": student.pk,
                "login": user.username,
                "month": "2026-08",
                "dispatch_id": dispatch.pk,
                "attempt_id": attempt.pk,
                "workflow_run_id": f"run-{index:02d}",
                "meta_http_status": 200,
                "meta_message_id": message_id,
                "message_status": "accepted",
                "meta_response": meta_response,
            })
            self.attempts.append(attempt)

    def write_manifest(self, mutate=None):
        manifest = {
            "schema_version": 1,
            "operation": "test-reconciliation",
            "report_month": "2026-08",
            "source": {"kind": "confirmed_dify_workflow_runs", "run_count": 27},
            "entries": json.loads(json.dumps(self.entries)),
        }
        if mutate:
            mutate(manifest)
        tempdir = tempfile.TemporaryDirectory()
        path = Path(tempdir.name) / "manifest.json"
        raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
        path.write_bytes(raw)
        return tempdir, path, hashlib.sha256(raw).hexdigest()

    def database_name(self):
        return str(connection.settings_dict["NAME"])

    def command_options(self, tempdir, path, digest, report_name="report.json", **overrides):
        options = {
            "manifest": path,
            "sha256": digest,
            "expect_database": self.database_name(),
            "report_file": Path(tempdir.name) / report_name,
        }
        options.update(overrides)
        return options

    def load_report(self, report_path):
        return json.loads(Path(report_path).read_text(encoding="utf-8"))

    @patch("urllib.request.urlopen")
    def test_dry_run_changes_nothing_and_makes_no_http_calls(self, mocked_urlopen):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        options = self.command_options(tempdir, path, digest)

        call_command("reconcile_monthly_report_callbacks", **options)

        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="failed").count(), 26)
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="pending").count(), 1)
        self.assertFalse(MonthlyStudentReportAttempt.objects.exclude(meta_message_id=None).exists())
        report = self.load_report(options["report_file"])
        self.assertEqual(report["mode"], "dry-run")
        self.assertFalse(report["applied"])
        self.assertTrue(report["validation_passed"])
        self.assertEqual(stat.S_IMODE(os.stat(options["report_file"]).st_mode), 0o600)
        mocked_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_successful_recovery_and_second_apply_are_idempotent(self, mocked_urlopen):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)

        call_command(
            "reconcile_monthly_report_callbacks",
            **self.command_options(tempdir, path, digest, "apply-1.json", apply=True),
        )
        first_sent_at = list(MonthlyStudentReportAttempt.objects.order_by("id").values_list("sent_at", flat=True))
        second_options = self.command_options(tempdir, path, digest, "apply-2.json", apply=True)
        call_command("reconcile_monthly_report_callbacks", **second_options)

        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 27)
        self.assertEqual(MonthlyStudentReportDispatch.objects.filter(status="accepted").count(), 27)
        self.assertEqual(MonthlyStudentReportAttempt.objects.exclude(meta_message_id=None).count(), 27)
        self.assertEqual(
            first_sent_at,
            list(MonthlyStudentReportAttempt.objects.order_by("id").values_list("sent_at", flat=True)),
        )
        second_report = self.load_report(second_options["report_file"])
        self.assertTrue(second_report["already_applied"])
        self.assertFalse(second_report["applied"])
        self.assertEqual(second_report["changed_attempt_ids"], [])
        mocked_urlopen.assert_not_called()

    def test_wrong_student_dispatch_attempt_mapping_is_blocked(self):
        def mutate(manifest):
            manifest["entries"][0]["dispatch_id"] = manifest["entries"][1]["dispatch_id"]

        tempdir, path, digest = self.write_manifest(mutate)
        self.addCleanup(tempdir.cleanup)
        with self.assertRaises(CommandError):
            call_command(
                "reconcile_monthly_report_callbacks",
                **self.command_options(tempdir, path, digest, apply=True),
            )
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_duplicate_meta_message_id_is_blocked(self):
        def mutate(manifest):
            duplicate = manifest["entries"][0]["meta_message_id"]
            manifest["entries"][1]["meta_message_id"] = duplicate
            manifest["entries"][1]["meta_response"]["messages"][0]["id"] = duplicate

        tempdir, path, digest = self.write_manifest(mutate)
        self.addCleanup(tempdir.cleanup)
        with self.assertRaises(CommandError):
            call_command(
                "reconcile_monthly_report_callbacks",
                **self.command_options(tempdir, path, digest, apply=True),
            )

    def test_changed_manifest_sha_is_blocked(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        path.write_text(path.read_text() + " ")
        with self.assertRaises(CommandError):
            call_command(
                "reconcile_monthly_report_callbacks",
                **self.command_options(tempdir, path, digest, apply=True),
            )
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_expect_database_is_required_and_database_is_unchanged(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        with self.assertRaises(CommandError):
            call_command(
                "reconcile_monthly_report_callbacks",
                manifest=path,
                sha256=digest,
                report_file=Path(tempdir.name) / "missing-database.json",
                apply=True,
            )
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_wrong_database_is_blocked_and_writes_failure_report(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        options = self.command_options(
            tempdir,
            path,
            digest,
            expect_database="definitely-not-this-database",
            apply=True,
        )
        with self.assertRaisesMessage(CommandError, "Database mismatch"):
            call_command("reconcile_monthly_report_callbacks", **options)
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)
        report = self.load_report(options["report_file"])
        self.assertFalse(report["validation_passed"])
        self.assertFalse(report["applied"])
        self.assertEqual(report["database_actual"], self.database_name())
        self.assertIn("Database mismatch", report["error"])

    def test_empty_database_name_is_blocked(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        options = self.command_options(tempdir, path, digest, expect_database="", apply=True)
        with self.assertRaisesMessage(CommandError, "non-empty exact database name"):
            call_command("reconcile_monthly_report_callbacks", **options)
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_database_verification_failure_is_blocked_before_apply(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        options = self.command_options(tempdir, path, digest, apply=True)
        with patch.object(Command, "_database_names", side_effect=CommandError("database check unavailable")):
            with self.assertRaisesMessage(CommandError, "database check unavailable"):
                call_command("reconcile_monthly_report_callbacks", **options)
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)
        report = self.load_report(options["report_file"])
        self.assertFalse(report["validation_passed"])
        self.assertFalse(report["applied"])

    def test_report_file_is_required(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        with self.assertRaises(CommandError):
            call_command(
                "reconcile_monthly_report_callbacks",
                manifest=path,
                sha256=digest,
                expect_database=self.database_name(),
            )

    def test_relative_report_path_is_blocked(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        with self.assertRaisesMessage(CommandError, "absolute path"):
            call_command(
                "reconcile_monthly_report_callbacks",
                **self.command_options(tempdir, path, digest, report_file=Path("relative-report.json"), apply=True),
            )
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_symlink_report_path_is_blocked(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        report_path = Path(tempdir.name) / "report-link.json"
        report_path.symlink_to(Path(tempdir.name) / "unexpected-target.json")
        with self.assertRaisesMessage(CommandError, "must not be a symlink"):
            call_command(
                "reconcile_monthly_report_callbacks",
                **self.command_options(tempdir, path, digest, report_file=report_path, apply=True),
            )
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_existing_report_is_not_overwritten(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        report_path = Path(tempdir.name) / "existing.json"
        report_path.write_text("do-not-overwrite", encoding="utf-8")
        with self.assertRaisesMessage(CommandError, "already exists"):
            call_command(
                "reconcile_monthly_report_callbacks",
                **self.command_options(tempdir, path, digest, report_file=report_path, apply=True),
            )
        self.assertEqual(report_path.read_text(encoding="utf-8"), "do-not-overwrite")
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_uncreatable_report_blocks_apply(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        report_path = Path(tempdir.name) / "missing-parent" / "report.json"
        with self.assertRaisesMessage(CommandError, "parent directory must already exist"):
            call_command(
                "reconcile_monthly_report_callbacks",
                **self.command_options(tempdir, path, digest, report_file=report_path, apply=True),
            )
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)

    def test_apply_report_has_exact_before_and_after_counts(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        options = self.command_options(tempdir, path, digest, apply=True)
        call_command("reconcile_monthly_report_callbacks", **options)
        report = self.load_report(options["report_file"])
        self.assertEqual(report["mode"], "apply")
        self.assertTrue(report["validation_passed"])
        self.assertTrue(report["applied"])
        self.assertFalse(report["already_applied"])
        self.assertEqual(report["target_dispatch_count"], 27)
        self.assertEqual(report["target_attempt_count"], 27)
        self.assertEqual(report["before_status_counts"]["dispatch"], {"failed": 26, "pending": 1})
        self.assertEqual(report["before_status_counts"]["attempt"], {"failed": 26, "pending": 1})
        self.assertEqual(report["after_status_counts"]["dispatch"], {"accepted": 27})
        self.assertEqual(report["after_status_counts"]["attempt"], {"accepted": 27})
        self.assertEqual(report["meta_message_ids_count"], 27)
        self.assertEqual(report["unique_meta_message_ids_count"], 27)
        self.assertEqual(len(report["changed_dispatch_ids"]), 27)
        self.assertEqual(len(report["changed_attempt_ids"]), 27)
        self.assertEqual(report["network_calls"], 0)

    def test_apply_failure_rolls_back_all_rows_and_writes_failure_report(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        options = self.command_options(tempdir, path, digest, apply=True)
        original_apply_entry = Command._apply_entry
        calls = {"count": 0}

        def fail_partway(command, row, manifest_sha, operation):
            original_apply_entry(command, row, manifest_sha, operation)
            calls["count"] += 1
            if calls["count"] == 10:
                raise RuntimeError("sensitive-value-must-not-leak")

        with patch.object(Command, "_apply_entry", new=fail_partway):
            with self.assertRaisesMessage(CommandError, "database changes were rolled back"):
                call_command("reconcile_monthly_report_callbacks", **options)
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)
        self.assertEqual(MonthlyStudentReportDispatch.objects.filter(status="accepted").count(), 0)
        self.assertFalse(MonthlyStudentReportAttempt.objects.exclude(meta_message_id=None).exists())
        report_text = Path(options["report_file"]).read_text(encoding="utf-8")
        self.assertNotIn("sensitive-value-must-not-leak", report_text)
        self.assertIn("reconciliation operation failed", report_text)

    def test_report_finalize_failure_after_commit_recovers_with_idempotent_dry_run(self):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        apply_options = self.command_options(tempdir, path, digest, "pending-apply.json", apply=True)
        original_replace = reconciliation_command._replace_reserved_report

        with patch.object(
            reconciliation_command,
            "_replace_reserved_report",
            side_effect=CommandError("simulated report finalize failure"),
        ):
            with self.assertRaisesMessage(CommandError, "Database reconciliation committed"):
                call_command("reconcile_monthly_report_callbacks", **apply_options)

        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 27)
        pending = self.load_report(apply_options["report_file"])
        self.assertIn("pending", pending["error"])

        dry_run_options = self.command_options(tempdir, path, digest, "recovery-dry-run.json")
        with patch.object(reconciliation_command, "_replace_reserved_report", new=original_replace):
            call_command("reconcile_monthly_report_callbacks", **dry_run_options)
        recovered = self.load_report(dry_run_options["report_file"])
        self.assertTrue(recovered["already_applied"])
        self.assertFalse(recovered["applied"])
        self.assertEqual(recovered["after_status_counts"]["attempt"], {"accepted": 27})

    @patch("socket.create_connection", side_effect=AssertionError("unexpected network call"))
    @patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network call"))
    def test_stdout_and_report_are_private_and_network_is_fail_closed(self, mocked_urlopen, mocked_socket):
        tempdir, path, digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        options = self.command_options(tempdir, path, digest)
        stdout = io.StringIO()
        call_command("reconcile_monthly_report_callbacks", stdout=stdout, **options)
        combined = stdout.getvalue() + Path(options["report_file"]).read_text(encoding="utf-8")
        self.assertNotIn("+996700120000", combined)
        self.assertNotIn("dev-secret-key-change-me", combined)
        self.assertNotIn("wamid.reconciled-00", stdout.getvalue())
        mocked_urlopen.assert_not_called()
        mocked_socket.assert_not_called()

    def test_sha256_argument_is_required(self):
        tempdir, path, _digest = self.write_manifest()
        self.addCleanup(tempdir.cleanup)
        with self.assertRaises(CommandError):
            call_command(
                "reconcile_monthly_report_callbacks",
                manifest=path,
                expect_database=self.database_name(),
                report_file=Path(tempdir.name) / "missing-sha.json",
                apply=True,
            )
        self.assertEqual(MonthlyStudentReportAttempt.objects.filter(status="accepted").count(), 0)
