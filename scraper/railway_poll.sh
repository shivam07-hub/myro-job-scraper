#!/bin/sh
# Railway cron entry point: one daily source poll, then exit.
# Fails fast, with a readable message, when the volume or a secret is missing.
set -eu

if [ ! -d /data ]; then
    echo "No volume at /data: attach a Railway volume mounted at /data (see docs/RAILWAY.md)" >&2
    exit 2
fi
mkdir -p /data/All_CSV_Outputs /data/logs

cd /app/scraper
python environment.py --require supabase stage_a
exec python daily_poll.py --scope india
