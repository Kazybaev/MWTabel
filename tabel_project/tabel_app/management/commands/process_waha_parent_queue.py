from django.core.management.base import BaseCommand, CommandError

from tabel_app.waha_parent_reports import WahaParentConfigurationError, run_waha_parent_worker


class Command(BaseCommand):
    help = "Process confirmed WAHA parent-report batches."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Exit when the queue is empty.")
        parser.add_argument("--poll-interval", type=float, default=2.0)

    def handle(self, *args, **options):
        if options["poll_interval"] < 0:
            raise CommandError("--poll-interval cannot be negative.")
        try:
            run_waha_parent_worker(once=options["once"], poll_interval=options["poll_interval"])
        except WahaParentConfigurationError as exc:
            raise CommandError(str(exc)) from exc
