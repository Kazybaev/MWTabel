#!/bin/sh
set -e

mkdir -p /vol/frontend
cp -r /app/frontend/dist/. /vol/frontend/

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
