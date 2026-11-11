#!/bin/sh
set -e

if [ "${REPORT_WORKER_ENABLED:-false}" != "true" ]; then
    echo "report-worker is disabled; set REPORT_WORKER_ENABLED=true for a controlled start" >&2
    exit 78
fi

case "${REPORT_WORKER_MODE:-continuous}" in
    continuous)
        if [ "${REPORT_LEGACY_QUEUE_REVIEWED:-false}" != "true" ]; then
            echo "continuous report-worker is blocked until the legacy queue review is approved" >&2
            exit 78
        fi
        ;;
    recovery)
        case "${REPORT_RECOVERY_BATCH_IDS:-}" in
            ""|*[!0-9,]*)
                echo "recovery worker requires explicit numeric REPORT_RECOVERY_BATCH_IDS" >&2
                exit 78
                ;;
        esac
        ;;
    *)
        echo "unknown REPORT_WORKER_MODE" >&2
        exit 78
        ;;
esac

exec "$@"
