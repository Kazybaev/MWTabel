from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from tabel_app.models import MonthlyStudentReportAttempt, MonthlyStudentReportDispatch
from tabel_app.report_delivery import record_meta_delivery_callback


EXPECTED_MONTH = "2026-08"
EXPECTED_ROWS = 27
EXPECTED_INITIAL_STATUSES = Counter({"failed": 26, "pending": 1})
EXPECTED_APPLIED_STATUSES = Counter({"accepted": 27})
COMMAND_NAME = "reconcile_monthly_report_callbacks"


def _json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_report_path(raw_path):
    if not raw_path or not os.path.isabs(raw_path):
        raise CommandError("--report-file must be a non-empty absolute path.")
    path = Path(raw_path)
    current = Path(path.anchor)
    try:
        for part in path.parts[1:-1]:
            current /= part
            current_stat = os.lstat(current)
            if stat.S_ISLNK(current_stat.st_mode):
                raise CommandError("--report-file must not traverse a symlink.")
        parent_stat = os.lstat(path.parent)
    except FileNotFoundError as exc:
        raise CommandError("--report-file parent directory must already exist.") from exc
    except OSError as exc:
        raise CommandError("Could not validate --report-file parent directory.") from exc
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise CommandError("--report-file parent must be a real directory, not a symlink.")
    try:
        target_stat = os.lstat(path)
    except FileNotFoundError:
        return path
    except OSError as exc:
        raise CommandError("Could not validate --report-file target.") from exc
    if stat.S_ISLNK(target_stat.st_mode):
        raise CommandError("--report-file must not be a symlink.")
    raise CommandError("--report-file already exists; refusing to overwrite it.")


def _reserve_report(path, pending_report):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise CommandError("--report-file already exists; refusing to overwrite it.") from exc
    except OSError as exc:
        raise CommandError("Could not safely create --report-file.") from exc
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(_json_bytes(pending_report))
            handle.flush()
            os.fsync(handle.fileno())
        reserved_stat = os.fstat(descriptor)
    except Exception:
        os.close(descriptor)
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    os.close(descriptor)
    _fsync_directory(path.parent)
    return reserved_stat.st_dev, reserved_stat.st_ino


def _replace_reserved_report(path, reserved_identity, report):
    try:
        target_stat = os.lstat(path)
    except OSError as exc:
        raise CommandError("Reserved report journal is missing or inaccessible.") from exc
    if stat.S_ISLNK(target_stat.st_mode) or (target_stat.st_dev, target_stat.st_ino) != reserved_identity:
        raise CommandError("Reserved report journal changed unexpectedly; refusing to overwrite it.")

    descriptor = None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(_json_bytes(report))
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        descriptor = None
        os.replace(temporary_path, path)
        temporary_path = None
        os.chmod(path, 0o600, follow_symlinks=False)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise CommandError("Could not atomically finalize --report-file.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


class Command(BaseCommand):
    help = "Offline, reviewed-manifest reconciliation for accepted Meta report callbacks (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, help="Path to the reviewed JSON manifest.")
        parser.add_argument("--sha256", required=True, help="Expected lowercase SHA-256 of the exact manifest bytes.")
        parser.add_argument(
            "--expect-database",
            required=True,
            help="Exact configured and actual database name required before validation or apply.",
        )
        parser.add_argument(
            "--report-file",
            required=True,
            help="New absolute path for the private atomic JSON audit report.",
        )
        parser.add_argument("--apply", action="store_true", help="Apply the validated reconciliation atomically.")

    def handle(self, *args, **options):
        started_at = timezone.now()
        manifest_path = Path(options["manifest"])
        expected_sha = str(options["sha256"]).strip()
        expected_database = options["expect_database"]
        mode = "apply" if options["apply"] else "dry-run"
        report = self._base_report(
            mode=mode,
            started_at=started_at,
            expected_database=expected_database,
            manifest_path=manifest_path,
            expected_sha=expected_sha,
        )
        report_path = _validate_report_path(options["report_file"])
        pending_report = dict(report)
        pending_report["error"] = (
            "pending: command did not finalize this journal; verify database state and rerun dry-run "
            "with a new report path"
        )
        reserved_identity = _reserve_report(report_path, pending_report)

        try:
            configured_database, actual_database = self._database_names()
            report["database_actual"] = actual_database
            if not isinstance(expected_database, str) or not expected_database:
                raise CommandError("--expect-database must be a non-empty exact database name.")
            if configured_database != expected_database or actual_database != expected_database:
                raise CommandError(
                    f"Database mismatch: expected {expected_database!r}, configured {configured_database!r}, "
                    f"actual {actual_database!r}."
                )
            if len(expected_sha) != 64 or any(character not in "0123456789abcdef" for character in expected_sha):
                raise CommandError("--sha256 must be exactly 64 lowercase hexadecimal characters.")
            raw_manifest = manifest_path.read_bytes()
            actual_sha = hashlib.sha256(raw_manifest).hexdigest()
            if not hmac.compare_digest(actual_sha, expected_sha):
                raise CommandError(f"Manifest SHA-256 mismatch: expected {expected_sha}, got {actual_sha}.")
            manifest = json.loads(raw_manifest)
            entries = self._validate_manifest(manifest)
            report["manifest_rows"] = len(entries)
            report["month"] = manifest["report_month"]

            with transaction.atomic():
                locked = self._validate_database(entries, expected_sha)
                already_applied = all(row["already_applied"] for row in locked)
                report["validation_passed"] = True
                report["already_applied"] = already_applied
                report["target_dispatch_count"] = len({row["dispatch"].pk for row in locked})
                report["target_attempt_count"] = len({row["attempt"].pk for row in locked})
                report["before_status_counts"] = self._status_counts(locked)
                if options["apply"] and not already_applied:
                    for row in locked:
                        self._apply_entry(row, expected_sha, manifest["operation"])
                    report["applied"] = True
                    report["changed_dispatch_ids"] = sorted(row["dispatch"].pk for row in locked)
                    report["changed_attempt_ids"] = sorted(row["attempt"].pk for row in locked)
                report.update(self._after_state(entries))
        except Exception as exc:
            report["finished_at"] = timezone.now().isoformat()
            report["error"] = self._safe_error(exc)
            try:
                _replace_reserved_report(report_path, reserved_identity, report)
            except CommandError as report_exc:
                raise CommandError(
                    "Reconciliation failed and its reserved failure report could not be finalized; "
                    "database changes were rolled back."
                ) from report_exc
            if isinstance(exc, CommandError):
                raise
            if isinstance(exc, OSError):
                raise CommandError("Could not read or validate the reconciliation manifest.") from exc
            if isinstance(exc, json.JSONDecodeError):
                raise CommandError("Manifest is not valid JSON.") from exc
            if isinstance(exc, DatabaseError):
                raise CommandError("Could not verify or reconcile the selected database.") from exc
            raise CommandError("Reconciliation operation failed; database changes were rolled back.") from exc

        report["finished_at"] = timezone.now().isoformat()
        try:
            _replace_reserved_report(report_path, reserved_identity, report)
        except CommandError as exc:
            if report["applied"]:
                raise CommandError(
                    "Database reconciliation committed, but the report journal could not be finalized. "
                    "Do not re-apply; run dry-run with a new report path to confirm already_applied."
                ) from exc
            raise

        outcome = "already applied; no changes" if report["already_applied"] else (
            "27 callbacks reconciled" if report["applied"] else "validation passed; no changes"
        )
        self.stdout.write(self.style.SUCCESS(
            f"{mode.upper()}: {outcome}. rows={report['manifest_rows']} month={report['month']} "
            f"database_actual={report['database_actual']} applied={str(report['applied']).lower()} "
            "network_calls=0"
        ))

    def _base_report(self, *, mode, started_at, expected_database, manifest_path, expected_sha):
        return {
            "command": COMMAND_NAME,
            "mode": mode,
            "started_at": started_at.isoformat(),
            "finished_at": None,
            "database_expected": expected_database,
            "database_actual": None,
            "manifest_path": str(manifest_path),
            "manifest_sha256": expected_sha,
            "manifest_rows": None,
            "month": None,
            "validation_passed": False,
            "applied": False,
            "already_applied": False,
            "target_dispatch_count": 0,
            "target_attempt_count": 0,
            "before_status_counts": {"dispatch": {}, "attempt": {}},
            "after_status_counts": {"dispatch": {}, "attempt": {}},
            "meta_message_ids_count": 0,
            "unique_meta_message_ids_count": 0,
            "network_calls": 0,
            "changed_dispatch_ids": [],
            "changed_attempt_ids": [],
            "error": None,
        }

    def _database_names(self):
        configured_database = str(connection.settings_dict.get("NAME") or "")
        if not configured_database:
            raise CommandError("Django database NAME is empty; refusing reconciliation.")
        try:
            connection.ensure_connection()
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database()")
                    row = cursor.fetchone()
                actual_database = str(row[0]) if row and row[0] is not None else ""
            else:
                actual_database = configured_database
        except DatabaseError as exc:
            raise CommandError("Could not verify the actual database name.") from exc
        return configured_database, actual_database

    def _status_counts(self, locked):
        return {
            "dispatch": dict(sorted(Counter(row["dispatch"].status for row in locked).items())),
            "attempt": dict(sorted(Counter(row["attempt"].status for row in locked).items())),
        }

    def _after_state(self, entries):
        attempt_ids = [entry["attempt_id"] for entry in entries]
        dispatch_ids = [entry["dispatch_id"] for entry in entries]
        attempts = list(MonthlyStudentReportAttempt.objects.filter(pk__in=attempt_ids).order_by("pk"))
        dispatches = list(MonthlyStudentReportDispatch.objects.filter(pk__in=dispatch_ids).order_by("pk"))
        message_ids = [attempt.meta_message_id for attempt in attempts if attempt.meta_message_id]
        return {
            "after_status_counts": {
                "dispatch": dict(sorted(Counter(row.status for row in dispatches).items())),
                "attempt": dict(sorted(Counter(row.status for row in attempts).items())),
            },
            "meta_message_ids_count": len(message_ids),
            "unique_meta_message_ids_count": len(set(message_ids)),
        }

    def _safe_error(self, exc):
        if isinstance(exc, CommandError):
            return str(exc)
        if isinstance(exc, json.JSONDecodeError):
            return "Manifest is not valid JSON."
        if isinstance(exc, OSError):
            return "Could not read or write a required reconciliation artifact."
        if isinstance(exc, DatabaseError):
            return "Database verification or reconciliation failed."
        return f"{type(exc).__name__}: reconciliation operation failed"

    def _validate_manifest(self, manifest):
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise CommandError("Unsupported manifest schema_version.")
        if manifest.get("report_month") != EXPECTED_MONTH:
            raise CommandError(f"Manifest report_month must be {EXPECTED_MONTH}.")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or len(entries) != EXPECTED_ROWS:
            raise CommandError(f"Manifest must contain exactly {EXPECTED_ROWS} entries.")
        required = {
            "student_id", "login", "month", "dispatch_id", "attempt_id", "workflow_run_id",
            "meta_http_status", "meta_message_id", "message_status", "meta_response",
        }
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict) or not required.issubset(entry):
                raise CommandError(f"Manifest entry {index} is missing required fields.")
            if entry["month"] != EXPECTED_MONTH:
                raise CommandError(f"Manifest entry {index} has an unexpected month.")
            if entry["meta_http_status"] != 200:
                raise CommandError(f"Manifest entry {index} Meta HTTP status is not 200.")
            if entry["message_status"] != "accepted":
                raise CommandError(f"Manifest entry {index} message_status is not accepted.")
            response = entry["meta_response"]
            messages = response.get("messages") if isinstance(response, dict) else None
            if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
                raise CommandError(f"Manifest entry {index} has an invalid Meta response.")
            if messages[0].get("id") != entry["meta_message_id"]:
                raise CommandError(f"Manifest entry {index} Meta message ID does not match its response.")
            if messages[0].get("message_status") != entry["message_status"]:
                raise CommandError(f"Manifest entry {index} message_status does not match its response.")
        for field in ("student_id", "workflow_run_id", "meta_message_id", "dispatch_id", "attempt_id"):
            values = [entry[field] for entry in entries]
            if len(set(values)) != EXPECTED_ROWS:
                raise CommandError(f"Manifest must contain {EXPECTED_ROWS} unique {field} values.")
        return entries

    def _validate_database(self, entries, manifest_sha):
        attempt_ids = [entry["attempt_id"] for entry in entries]
        attempts = {
            attempt.pk: attempt
            for attempt in MonthlyStudentReportAttempt.objects.select_for_update()
            .select_related("dispatch__student__user")
            .only(
                "id", "dispatch_id", "attempt_number", "status", "workflow_run_id", "response_payload",
                "dispatch__id", "dispatch__student_id", "dispatch__month", "dispatch__payload",
                "dispatch__attempts", "dispatch__status", "dispatch__workflow_run_id",
                "dispatch__student__user__username",
            )
            .filter(pk__in=attempt_ids)
        }
        if len(attempts) != EXPECTED_ROWS:
            raise CommandError("Not every manifest attempt exists.")

        locked = []
        statuses = Counter()
        dispatch_statuses = Counter()
        for entry in entries:
            attempt = attempts[entry["attempt_id"]]
            dispatch = attempt.dispatch
            if dispatch.pk != entry["dispatch_id"]:
                raise CommandError(f"Attempt {attempt.pk} does not belong to the reviewed dispatch.")
            if dispatch.student_id != entry["student_id"] or dispatch.student.user.username != entry["login"]:
                raise CommandError(f"Reviewed identity mismatch for attempt {attempt.pk}.")
            if dispatch.month.strftime("%Y-%m") != entry["month"]:
                raise CommandError(f"Reviewed month mismatch for attempt {attempt.pk}.")
            if attempt.attempt_number != dispatch.attempts:
                raise CommandError(f"Attempt {attempt.pk} is not the dispatch's current attempt.")
            if attempt.workflow_run_id and attempt.workflow_run_id != entry["workflow_run_id"]:
                raise CommandError(f"Dify workflow_run_id mismatch for attempt {attempt.pk}.")
            if dispatch.workflow_run_id and dispatch.workflow_run_id != entry["workflow_run_id"]:
                raise CommandError(f"Dify workflow_run_id mismatch for dispatch {dispatch.pk}.")
            meta = attempt.response_payload.get("meta", {}) if isinstance(attempt.response_payload, dict) else {}
            exact_existing = (
                attempt.status == MonthlyStudentReportDispatch.STATUS_ACCEPTED
                and attempt.meta_message_id == entry["meta_message_id"]
                and attempt.message_status == entry["message_status"]
                and meta.get("callback_received") is True
                and meta.get("status_code") == entry["meta_http_status"]
                and meta.get("response") == entry["meta_response"]
                and meta.get("reconciliation", {}).get("manifest_sha256") == manifest_sha
            )
            if meta.get("callback_received") and not exact_existing:
                raise CommandError(f"Attempt {attempt.pk} already has a different callback.")
            statuses[attempt.status] += 1
            dispatch_statuses[dispatch.status] += 1
            locked.append({
                "entry": entry,
                "attempt": attempt,
                "dispatch": dispatch,
                "already_applied": exact_existing,
            })

        if all(row["already_applied"] for row in locked):
            if statuses != EXPECTED_APPLIED_STATUSES or dispatch_statuses != EXPECTED_APPLIED_STATUSES:
                raise CommandError("Applied reconciliation has an unexpected status distribution.")
        elif (
            any(row["already_applied"] for row in locked)
            or statuses != EXPECTED_INITIAL_STATUSES
            or dispatch_statuses != EXPECTED_INITIAL_STATUSES
        ):
            raise CommandError(
                "Current attempt and dispatch statuses must both be exactly failed=26,pending=1; "
                f"got attempts={dict(statuses)} dispatches={dict(dispatch_statuses)}."
            )
        return locked

    def _apply_entry(self, row, manifest_sha, operation):
        entry = row["entry"]
        dispatch = row["dispatch"]
        report = dict(dispatch.payload) if isinstance(dispatch.payload, dict) else {}
        report["correlation"] = {
            "dispatch_id": dispatch.pk,
            "attempt_id": row["attempt"].pk,
            "batch_item_id": None,
        }
        updated_dispatch, duplicate = record_meta_delivery_callback(
            delivery={"channel": "meta_whatsapp", "report": report, "meta_request": {}},
            meta_status_code=entry["meta_http_status"],
            meta_response=entry["meta_response"],
        )
        if duplicate:
            raise CommandError(f"Unexpected duplicate while applying attempt {row['attempt'].pk}.")
        attempt = MonthlyStudentReportAttempt.objects.select_for_update().get(pk=row["attempt"].pk)
        attempt.workflow_run_id = entry["workflow_run_id"]
        attempt.response_payload["meta"]["reconciliation"] = {
            "operation": operation,
            "manifest_sha256": manifest_sha,
        }
        attempt.save(update_fields=["workflow_run_id", "response_payload", "updated_at"])
        if attempt.attempt_number == updated_dispatch.attempts:
            updated_dispatch.workflow_run_id = entry["workflow_run_id"]
            updated_dispatch.response_payload = attempt.response_payload
            updated_dispatch.save(update_fields=["workflow_run_id", "response_payload", "updated_at"])
