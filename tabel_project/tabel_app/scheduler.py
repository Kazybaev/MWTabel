from __future__ import annotations

import os
import sys
import threading

from django.utils import timezone

from .report import logger, send_due_monthly_reports


_scheduler_thread = None
_scheduler_lock = threading.Lock()
_scheduler_stop_event = threading.Event()


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _scheduler_enabled() -> bool:
    return _is_truthy(os.getenv("AUTO_MONTHLY_REPORTS", "false"))


def _run_on_start_enabled() -> bool:
    return _is_truthy(os.getenv("REPORT_SCHEDULER_RUN_ON_START", "true"))


def _scheduler_interval_seconds() -> int:
    try:
        interval = int(os.getenv("REPORT_SCHEDULER_INTERVAL_SECONDS", "3600"))
    except ValueError:
        interval = 3600
    return max(interval, 60)


def _should_start_in_this_process() -> bool:
    if not _scheduler_enabled():
        return False

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "runserver":
            return os.environ.get("RUN_MAIN") == "true"
        if command in {
            "migrate",
            "makemigrations",
            "collectstatic",
            "seed_demo",
            "send_monthly_reports",
            "shell",
            "createsuperuser",
            "test",
            "check",
            "dbshell",
            "flush",
            "loaddata",
            "dumpdata",
        }:
            return False

    return True


def run_scheduled_report_check(trigger: str = "scheduler") -> list[dict]:
    run_date = timezone.localdate()
    logger.info("Automatic report check started: trigger='%s', run_date='%s'", trigger, run_date.isoformat())
    try:
        results = send_due_monthly_reports(run_date=run_date)
    except Exception:
        logger.exception("Automatic report check crashed: trigger='%s'", trigger)
        return []

    sent = sum(1 for result in results if result["status"] == "sent")
    failed = sum(1 for result in results if result["status"] == "failed")
    dry_run = sum(1 for result in results if result["status"] == "dry_run")
    skipped = sum(1 for result in results if result["status"] == "skipped")

    if sent or failed or dry_run:
        logger.info(
            "Automatic report check finished: sent=%s, failed=%s, dry_run=%s, skipped=%s",
            sent,
            failed,
            dry_run,
            skipped,
        )
    elif results:
        logger.debug(
            "Automatic report check finished with only skipped results: skipped=%s",
            skipped,
        )
    else:
        logger.debug("Automatic report check finished: no students matched the current month window")

    return results


def _scheduler_loop() -> None:
    interval = _scheduler_interval_seconds()
    logger.info("Monthly report scheduler loop is running every %s seconds", interval)

    if _run_on_start_enabled():
        run_scheduled_report_check(trigger="startup")

    while not _scheduler_stop_event.wait(interval):
        run_scheduled_report_check(trigger="interval")


def start_report_scheduler() -> None:
    global _scheduler_thread

    if not _should_start_in_this_process():
        return

    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return

        _scheduler_stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=_scheduler_loop,
            name="monthly-report-scheduler",
            daemon=True,
        )
        _scheduler_thread.start()
        logger.info("Automatic monthly report scheduler started")
