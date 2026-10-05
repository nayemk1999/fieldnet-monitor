#!/bin/sh
set -e
case "$1" in
  api)
    python manage.py migrate --noinput
    exec gunicorn fieldnet.wsgi:application -b 0.0.0.0:8000 -w "${WEB_CONCURRENCY:-2}" --access-logfile -
    ;;
  worker)
    exec python manage.py run_worker
    ;;
  *)
    exec "$@"
    ;;
esac
