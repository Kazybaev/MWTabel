"""Owner-approved, insert-free repair of first-course Lesson dates.

The command is deliberately manifest-driven.  It never infers scope from a
year, group name, or primary-key range; every Lesson must be listed in the
approved provenance map and be linked to an ImportedGradeCell for the source.
"""

import hashlib
import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count

from tabel_app.models import Group, ImportedGradeCell, Lesson, LessonRecord


MAP_FIELDS = (
    "lesson_id",
    "group_id",
    "group_name",
    "old_date",
    "new_date",
    "lesson_record_count",
    "imported_grade_cell_count",
)


def canonical_map(rows):
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class Command(BaseCommand):
    help = "Dry-run (or explicitly apply) owner-approved first-course Lesson date repair."

    def add_arguments(self, parser):
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--expect-database", required=True)
        parser.add_argument("--report", required=True)
        parser.add_argument("--apply", action="store_true")

    def fail(self, message):
        raise CommandError(message)

    def load_manifest(self, path, expected_sha, source_id):
        raw = Path(path).read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != expected_sha:
            self.fail(f"Manifest SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")
        try:
            manifest = json.loads(raw)
        except (TypeError, ValueError):
            self.fail("Manifest is not valid JSON.")
        if manifest.get("approved") is not True:
            self.fail("Manifest is not explicitly approved.")
        if manifest.get("source_id") != source_id:
            self.fail("Manifest source-id mismatch.")
        if manifest.get("old_year") != 2025 or manifest.get("new_year") != 2026:
            self.fail("Manifest must approve the 2025 -> 2026 repair.")
        rows = manifest.get("lessons")
        if not isinstance(rows, list) or len(rows) != 236:
            self.fail("Approved manifest must contain exactly 236 Lessons.")
        normalized = []
        for row in rows:
            if set(row) != set(MAP_FIELDS):
                self.fail("Manifest row has unexpected fields.")
            if row["old_date"][:4] != "2025" or row["new_date"][:4] != "2026":
                self.fail("Manifest contains a date outside 2025 -> 2026.")
            if row["old_date"][5:] != row["new_date"][5:]:
                self.fail("Manifest changes month/day.")
            normalized.append({key: row[key] for key in MAP_FIELDS})
        if len({row["lesson_id"] for row in normalized}) != 236:
            self.fail("Manifest Lesson IDs are not unique.")
        map_sha = hashlib.sha256(canonical_map(normalized)).hexdigest()
        if map_sha != manifest.get("map_sha256"):
            self.fail("Manifest map SHA-256 mismatch.")
        return manifest, normalized, actual_sha, map_sha

    def handle(self, *args, **options):
        if connection.settings_dict.get("NAME") != options["expect_database"]:
            self.fail("Connected database does not match --expect-database.")
        if options["source_id"] != "college-2026-seed":
            self.fail("This repair command only accepts --source-id college-2026-seed.")

        manifest, rows, manifest_sha, map_sha = self.load_manifest(
            options["manifest"], options["manifest_sha256"], options["source_id"]
        )
        ids = [row["lesson_id"] for row in rows]
        lessons = list(Lesson.objects.filter(pk__in=ids).select_related("group"))
        by_id = {lesson.pk: lesson for lesson in lessons}
        if len(by_id) != 236:
            self.fail("Manifest does not resolve to exactly 236 existing Lessons.")

        source_cells = ImportedGradeCell.objects.filter(
            source_id=options["source_id"], lesson_id__in=ids
        )
        source_ids = set(source_cells.values_list("lesson_id", flat=True))
        if source_ids != set(ids):
            self.fail("Every manifest Lesson must have source ImportedGradeCell provenance.")
        if source_cells.count() != 2462:
            self.fail("Source provenance does not resolve to exactly 2462 cells with Lessons.")
        source_group_mismatch = any(
            group_id is not None and group_id != by_id[lesson_id].group_id
            for lesson_id, group_id in source_cells.values_list("lesson_id", "group_id")
        )
        if source_group_mismatch:
            self.fail("Source ImportedGradeCell group provenance is inconsistent with the manifest scope.")

        first_groups = Group.objects.filter(organization_type="college", college_course="")
        if first_groups.count() != 24:
            self.fail("First-course scope must contain exactly 24 groups.")
        manifest_group_ids = {lesson.group_id for lesson in lessons}
        outside_lessons = Lesson.objects.filter(
            group__organization_type="college", group__college_course=""
        ).exclude(pk__in=ids)
        if outside_lessons.exists():
            self.fail("First-course contains Lesson rows outside the approved source scope.")
        empty_groups = first_groups.exclude(pk__in=manifest_group_ids)
        if empty_groups.filter(lessons__isnull=False).exists() or LessonRecord.objects.filter(
            lesson__group__in=empty_groups
        ).exists():
            self.fail("An approved empty first-course group already has Lesson data.")

        conflicts = []
        state = Counter()
        target_dates = {}
        for row in rows:
            lesson = by_id[row["lesson_id"]]
            expected_old = date.fromisoformat(row["old_date"])
            expected_new = date.fromisoformat(row["new_date"])
            if lesson.group_id != row["group_id"] or lesson.group.course_name != row["group_name"]:
                conflicts.append({"lesson_id": lesson.pk, "reason": "group_provenance_mismatch"})
            if lesson.group.organization_type != "college" or lesson.group.college_course != "":
                conflicts.append({"lesson_id": lesson.pk, "reason": "outside_first_course_scope"})
            if lesson.lesson_date == expected_old:
                state["pending"] += 1
            elif lesson.lesson_date == expected_new:
                state["already_corrected"] += 1
            else:
                conflicts.append({"lesson_id": lesson.pk, "reason": "mixed_or_unexpected_date", "actual": lesson.lesson_date.isoformat()})
            target_dates[lesson.pk] = expected_new
            if expected_new > date.today():
                conflicts.append({"lesson_id": lesson.pk, "reason": "target_date_in_future", "target": expected_new.isoformat()})

        if state["pending"] and state["already_corrected"]:
            conflicts.append({"reason": "partially_corrected_state"})

        for row in rows:
            lesson = by_id[row["lesson_id"]]
            target = target_dates[lesson.pk]
            existing = Lesson.objects.filter(group_id=lesson.group_id, lesson_date=target).exclude(pk=lesson.pk)
            if existing.exists():
                conflicts.append({"lesson_id": lesson.pk, "reason": "target_lesson_conflict", "target": target.isoformat()})
            target_records = LessonRecord.objects.filter(lesson__in=existing)
            if target_records.exists():
                conflicts.append({"lesson_id": lesson.pk, "reason": "target_lesson_has_records"})

        second_course = set(ImportedGradeCell.objects.filter(source_id="college-2026-second-course", lesson_id__in=ids).values_list("lesson_id", flat=True))
        academy = set(Lesson.objects.filter(pk__in=ids, group__organization_type="academy").values_list("id", flat=True))
        if second_course:
            conflicts.append({"reason": "second_course_scope_overlap", "lesson_ids": sorted(second_course)})
        if academy:
            conflicts.append({"reason": "academy_scope_overlap", "lesson_ids": sorted(academy)})

        record_count = LessonRecord.objects.filter(lesson_id__in=ids).count()
        if record_count != 2462:
            conflicts.append({"reason": "lesson_record_count_mismatch", "count": record_count})
        duplicate_records = list(
            LessonRecord.objects.filter(lesson_id__in=ids)
            .values("student_id", "lesson_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        if duplicate_records:
            conflicts.append({"reason": "duplicate_lesson_records", "keys": duplicate_records})
        if len(ids) != len(set(ids)):
            conflicts.append({"reason": "duplicate_manifest_ids"})

        report = {
            "mode": "apply" if options["apply"] else "dry-run",
            "applied": False,
            "database": options["expect_database"],
            "source_id": options["source_id"],
            "manifest_sha256": manifest_sha,
            "map_sha256": map_sha,
            "approved": manifest["approved"],
            "scope": {"lessons": 236, "lesson_records": record_count, "source_cells_with_lessons": source_cells.count()},
            "state": dict(state),
            "conflicts": conflicts,
            "pending": state["pending"],
            "already_corrected": state["already_corrected"],
            "updates": 0,
        }
        if conflicts:
            report["status"] = "blocked"
        elif state["pending"] == 236:
            report["status"] = "ready" if not options["apply"] else "applied"
            if options["apply"]:
                with transaction.atomic():
                    for row in rows:
                        Lesson.objects.filter(pk=row["lesson_id"], lesson_date=row["old_date"]).update(lesson_date=row["new_date"])
                report["applied"] = True
                report["updates"] = 236
        elif state["already_corrected"] == 236:
            report["status"] = "idempotent"
        else:
            report["status"] = "blocked"

        report_path = Path(options["report"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(report_path, 0o600)
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if report["status"] == "blocked":
            raise CommandError("Date repair blocked; no database changes were made.")
