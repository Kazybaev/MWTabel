from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from tabel_app.report_queue import cancel_report_batches, inspect_report_batch_cancellation


class Command(BaseCommand):
    help = "Preview or cancel explicitly selected report batches without deleting their history."

    def add_arguments(self, parser):
        parser.add_argument("--batch-ids", nargs="+", type=int, required=True)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the cancellation. Without this flag the command is read-only.",
        )

    def handle(self, *args, **options):
        batch_ids = options["batch_ids"]
        if any(batch_id < 1 for batch_id in batch_ids):
            raise CommandError("Batch IDs must be positive integers.")

        try:
            result = (
                cancel_report_batches(batch_ids)
                if options["apply"]
                else inspect_report_batch_cancellation(batch_ids)
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        result["mode"] = "apply" if options["apply"] else "dry-run"
        result.setdefault("applied", False)
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))

        if result["missing_ids"]:
            raise CommandError(f"Unknown batch IDs: {result['missing_ids']}")
