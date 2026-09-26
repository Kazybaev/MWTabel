from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from tabel_app.report_queue import claim_next_report_item, process_claimed_report_item


class Command(BaseCommand):
    help = "Process persistent monthly report batch items outside Gunicorn."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Exit when no queued item remains.")
        parser.add_argument("--max-items", type=int, help="Exit after processing at most this many items.")
        parser.add_argument("--poll-interval", type=float, default=2.0)
        parser.add_argument("--lease-seconds", type=int, default=900)

    def handle(self, *args, **options):
        if options["poll_interval"] < 0:
            raise CommandError("--poll-interval cannot be negative.")
        if options["lease_seconds"] < 60:
            raise CommandError("--lease-seconds must be at least 60.")
        if options["max_items"] is not None and options["max_items"] < 1:
            raise CommandError("--max-items must be at least 1.")
        processed = 0
        while True:
            item = claim_next_report_item(lease_seconds=options["lease_seconds"])
            if item is None:
                if options["once"]:
                    return
                time.sleep(options["poll_interval"])
                continue
            process_claimed_report_item(item.pk, item.worker_token)
            processed += 1
            if options["max_items"] is not None and processed >= options["max_items"]:
                return
