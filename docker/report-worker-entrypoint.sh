#!/bin/sh
set -e

if [ "${REPORT_WORKER_ENABLED:-false}" != "true" ]; then
    echo "report-worker is disabled; set REPORT_WORKER_ENABLED=true for a controlled start" >&2
    exit 78
fi

exec "$@"
