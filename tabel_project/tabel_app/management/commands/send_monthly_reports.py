from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from tabel_app.report import normalize_month_start, send_due_monthly_reports


class Command(BaseCommand):
    help = "Send monthly student reports to Dify on the last lesson day of the month."

    def add_arguments(self, parser):
        parser.add_argument("--date", dest="run_date", help="Run date in YYYY-MM-DD format.")
        parser.add_argument("--month", dest="month", help="Reporting month in YYYY-MM format.")
        parser.add_argument("--student-id", dest="student_id", type=int, help="Send only for one student.")
        parser.add_argument("--group-id", dest="group_id", type=int, help="Send only for one group.")
        parser.add_argument("--dry-run", action="store_true", help="Build reports without sending them.")
        parser.add_argument("--force", action="store_true", help="Send even if today is not the trigger date.")

    def handle(self, *args, **options):
        run_date = self._parse_date(options.get("run_date"))
        month_start = self._parse_month(options.get("month"))
        results = send_due_monthly_reports(
            run_date=run_date,
            month_start=month_start,
            student_id=options.get("student_id"),
            group_id=options.get("group_id"),
            dry_run=options.get("dry_run", False),
            force=options.get("force", False),
        )

        if not results:
            self.stdout.write(self.style.WARNING("No students matched the selected report window."))
            return

        sent_count = 0
        failed_count = 0
        skipped_count = 0
        dry_run_count = 0

        for result in results:
            status = result["status"]
            student_name = result["student_name"]
            if status == "sent":
                sent_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Sent report for {student_name} (dispatch #{result['dispatch_id']})."
                    )
                )
            elif status == "failed":
                failed_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"Failed report for {student_name}: {result['reason']}"
                    )
                )
            elif status == "dry_run":
                dry_run_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Dry run for {student_name}; trigger date {result['trigger_date']}."
                    )
                )
            else:
                skipped_count += 1
                reason = result.get("reason", "skipped")
                self.stdout.write(f"Skipped {student_name}: {reason}.")

        self.stdout.write("")
        self.stdout.write(
            f"Summary: sent={sent_count}, failed={failed_count}, dry_run={dry_run_count}, skipped={skipped_count}"
        )

        if failed_count:
            raise CommandError("One or more student reports failed to send.")

    def _parse_date(self, value):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError("--date must be in YYYY-MM-DD format.") from exc

    def _parse_month(self, value):
        if not value:
            return None
        try:
            parsed = datetime.strptime(value, "%Y-%m").date()
        except ValueError as exc:
            raise CommandError("--month must be in YYYY-MM format.") from exc
        return normalize_month_start(parsed)
