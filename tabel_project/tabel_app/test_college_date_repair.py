import hashlib
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.core import management
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from .management.commands.repair_college_lesson_dates import Command, canonical_map


class CollegeDateRepairManifestTests(SimpleTestCase):
    def make_manifest(self, **overrides):
        rows = []
        start = date(2025, 8, 1)
        for index in range(236):
            old = start + timedelta(days=index % 34)
            rows.append({
                "lesson_id": index + 1,
                "group_id": (index % 24) + 1,
                "group_name": f"cohort-{index % 24 + 1}",
                "old_date": old.isoformat(),
                "new_date": old.replace(year=2026).isoformat(),
                "lesson_record_count": 0,
                "imported_grade_cell_count": 0,
            })
        manifest = {
            "schema_version": 1,
            "source_id": "college-2026-seed",
            "approved": True,
            "approved_at": "2026-09-10",
            "approved_by": "data owner confirmation",
            "basis": "owner approved",
            "old_year": 2025,
            "new_year": 2026,
            "map_sha256": hashlib.sha256(canonical_map(rows)).hexdigest(),
            "lessons": rows,
        }
        manifest.update(overrides)
        return manifest

    def write_manifest(self, manifest):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(manifest, handle, ensure_ascii=False)
        handle.close()
        raw = Path(handle.name).read_bytes()
        return Path(handle.name), hashlib.sha256(raw).hexdigest()

    def test_exact_approved_manifest_is_accepted(self):
        path, digest = self.write_manifest(self.make_manifest())
        manifest, rows, actual, map_digest = Command().load_manifest(path, digest, "college-2026-seed")
        self.assertTrue(manifest["approved"])
        self.assertEqual(len(rows), 236)
        self.assertEqual(actual, digest)
        self.assertEqual(map_digest, manifest["map_sha256"])

    def test_wrong_manifest_sha_is_rejected(self):
        path, _ = self.write_manifest(self.make_manifest())
        with self.assertRaises(CommandError):
            Command().load_manifest(path, "0" * 64, "college-2026-seed")

    def test_unapproved_manifest_is_rejected(self):
        path, digest = self.write_manifest(self.make_manifest(approved=False))
        with self.assertRaises(CommandError):
            Command().load_manifest(path, digest, "college-2026-seed")

    def test_wrong_source_id_is_rejected(self):
        path, digest = self.write_manifest(self.make_manifest())
        with self.assertRaises(CommandError):
            Command().load_manifest(path, digest, "college-2026-second-course")

    def test_month_day_change_is_rejected(self):
        manifest = self.make_manifest()
        manifest["lessons"][0]["new_date"] = "2026-09-01"
        manifest["map_sha256"] = hashlib.sha256(canonical_map(manifest["lessons"])).hexdigest()
        path, digest = self.write_manifest(manifest)
        with self.assertRaises(CommandError):
            Command().load_manifest(path, digest, "college-2026-seed")

    def test_management_command_is_registered(self):
        self.assertIn("repair_college_lesson_dates", management.get_commands())
