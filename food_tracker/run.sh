#!/bin/sh
set -eu
export DATA_DIR="${DATA_DIR:-/data}"
exec /opt/venv/bin/gunicorn --bind 0.0.0.0:8099 --workers 1 --threads 4 --access-logfile - --error-logfile - 'app:create_app()'
