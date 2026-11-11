from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand, CommandError

from tabel_app.models import MonthlyStudentReportBatch
from tabel_app.report_queue import claim_next_report_item, process_claimed_report_item


class Command(BaseCommand):
    help = "Process persistent monthly report batch items outside Gunicorn."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Exit when no queued item remains.")
        parser.add_argument("--max-items", type=int, help="Exit after processing at most this many items.")
        parser.add_argument(
            "--recovery-batch-ids",
            help="Comma-separated IDs for a one-off legacy queue recovery.",
        )
        parser.add_argument("--poll-interval", type=float, default=2.0)
        parser.add_argument("--lease-seconds", type=int, default=900)

    def handle(self, *args, **options):
        if options["poll_interval"] < 0:
            raise CommandError("--poll-interval cannot be negative.")
        if options["lease_seconds"] < 60:
            raise CommandError("--lease-seconds must be at least 60.")
        if options["max_items"] is not None and options["max_items"] < 1:
            raise CommandError("--max-items must be at least 1.")
        worker_mode = os.getenv("REPORT_WORKER_MODE", "continuous").strip().lower()
        if worker_mode not in {"continuous", "recovery"}:
            raise CommandError("REPORT_WORKER_MODE must be continuous or recovery.")
        explicit_recovery_ids = (options["recovery_batch_ids"] or "").strip()
        recovery_mode = bool(explicit_recovery_ids) or worker_mode == "recovery"
        raw_batch_ids = (
            explicit_recovery_ids
            or (os.getenv("REPORT_RECOVERY_BATCH_IDS", "").strip() if recovery_mode else "")
        )
        batch_ids = None
        if recovery_mode:
            if not raw_batch_ids:
                raise CommandError("Recovery mode requires exact recovery batch IDs.")
            if not options["once"]:
                raise CommandError("Legacy recovery requires --once.")
            try:
                batch_ids = sorted({int(value.strip()) for value in raw_batch_ids.split(",") if value.strip()})
            except ValueError as exc:
                raise CommandError("Recovery batch IDs must be comma-separated positive integers.") from exc
            if not batch_ids or any(batch_id < 1 for batch_id in batch_ids):
                raise CommandError("Recovery batch IDs must be comma-separated positive integers.")
            found_ids = set(
                MonthlyStudentReportBatch.objects.filter(pk__in=batch_ids).values_list("pk", flat=True)
            )
            missing_ids = [batch_id for batch_id in batch_ids if batch_id not in found_ids]
            if missing_ids:
                raise CommandError(f"Unknown batch IDs: {missing_ids}")
        elif os.getenv("REPORT_LEGACY_QUEUE_REVIEWED", "false").lower() != "true":
            raise CommandError(
                "Continuous worker is blocked until REPORT_LEGACY_QUEUE_REVIEWED=true."
            )
        processed = 0
        while True:
            item = claim_next_report_item(
                batch_ids=batch_ids,
                include_operator_review=recovery_mode,
                lease_seconds=options["lease_seconds"],
            )
            if item is None:
                if options["once"]:
                    return
                time.sleep(options["poll_interval"])
                continue
            process_claimed_report_item(item.pk, item.worker_token)
            processed += 1
            if options["max_items"] is not None and processed >= options["max_items"]:
                return
