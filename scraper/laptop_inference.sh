#!/bin/sh
# Hourly laptop entry point (launchd: ops/launchd/com.myro.inference-drain.plist).
# Railway publishes; this drains embeddings, then enrichment, with local LM Studio.
# A drain still running from the last hour makes this a quiet skip (exit 0).
set -eu

REPO="/Users/incognito/myro-job-scraper"
LOG="$REPO/logs/inference_$(date +%Y_%m_%d).log"
mkdir -p "$REPO/logs"

cd "$REPO/scraper"
echo "=== $(date '+%Y-%m-%d %H:%M:%S') inference-only start" >> "$LOG"
ENRICH_FORCE_LLM=1 /opt/anaconda3/bin/python daily_cycle.py --inference-only >> "$LOG" 2>&1
