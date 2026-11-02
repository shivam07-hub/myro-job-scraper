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
# Railway keeps container logs for about a week and csv_importer logs only to
# stdout, so copy the run to the volume. tee still passes output through if that
# file fails. sh has no pipefail, so the poll's exit code travels in a file.
log="/data/logs/railway_poll_$(date -u +%Y%m%d_%H%M%S).log"
exit_file=$(mktemp)
echo 0 > "$exit_file"
# The 5 GB volume holds ~10 full polls; keep three run dates and two weeks of
# logs so it never fills again (it did on 2026-10-21).
{ python daily_poll.py --scope india --keep-runs 3 --keep-log-days 14 2>&1 || echo $? > "$exit_file"; } \
    | tee -a "$log" || true
exit "$(cat "$exit_file")"
