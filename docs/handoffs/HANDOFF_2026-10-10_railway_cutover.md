# Handoff 2026-10-10 — Railway cutover: verify the first runs, then finish the cutover

Read `CLAUDE.md` first (especially SCOPE, CHANGE DISCIPLINE, and PENDING WORK → 00a, the
14 locked decisions). This file is the operating checklist for the days after the cutover.

## What is live

| Piece | Where | Schedule |
|---|---|---|
| Daily source poll (scrape → resolve → publish) | Railway project `myro-job-scraper` (`f4ae0198-40cf-4484-8481-3d257c39fce8`), service `daily-poll` (`19ce5ea5-cf61-4a4f-ae81-ffd2f1b55cf7`), env `production`, region europe-west4 | cron `30 19 * * *` = **01:00 IST** daily, ~10 h run |
| Run outputs + logs | Railway volume `scraper-data`, 5 GB at `/data` | persistent |
| Embeddings + enrichment drain | launchd agent `com.myro.inference-drain` on the owner's Mac → `scraper/laptop_inference.sh` → `daily_cycle.py --inference-only` | hourly while awake |
| Old Codex automation `daily-trusted-career-poll` | `~/.codex/automations/` | still `ACTIVE`; only fires if the Codex app is open — **pause it after the first green Railway publish** |

The local Railway CLI (`/Users/incognito/.npm-global/bin/railway`) is already linked to the
service from the repo root. Secrets are set on the service; never print, copy, or re-set them.

## Checklist

### 1. First Railway run (starts 2026-10-10 01:00 IST)

```bash
cd /Users/incognito/myro-job-scraper
railway logs --deployment --lines 60
```

At the start, expect `blocked capabilities: none`, `scrapling fetcher: ready`, `Portals to process: ~320`,
then `[1/…]`. A run that ends early with `Cannot …` or `No volume at /data` is a config problem: fix the
service, not the code.

### 2. Did it publish? (around 11:00 IST)

Counts only; reads `scraper/.env` through the project's own client and prints no secrets:

```bash
cd /Users/incognito/myro-job-scraper/scraper && /opt/anaconda3/bin/python - <<'EOF'
from environment import load_environment; load_environment()
import os
from supabase import create_client
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
runs = sb.table("job_source_runs").select("status,started_at").order("started_at", desc=True).limit(400).execute().data
latest = runs[0]["started_at"][:10] if runs else None
today = [r for r in runs if r["started_at"][:10] == latest]
print("latest run date:", latest, "| companies:", len(today), "| by status:",
      {s: sum(1 for r in today if r["status"] == s) for s in {r["status"] for r in today}})
EOF
```

Green means a run dated today with ~230+ `complete`, and the Railway log ends with
`Stage A hand-off accepted` and `Daily source poll complete`.

### 3. Geo-blocking check (after the first green run)

The laptop ran from India; Railway runs from the Netherlands. Compare the run's diagnosis
(`railway logs`, or `/data/logs/diagnosis_*.md` via `railway ssh`) with the last laptop run
(`logs/diagnosis_20260930_020205_103187.md`). A company that went to 0 **only** on Railway is
probably blocking non-Indian IPs. List those for the owner; don't change regions or add proxies without
approval.

### 4. Pause the Codex automation (decision 6) — only after step 2 is green

```bash
sed -i '' 's/^status = "ACTIVE"$/status = "PAUSED"/' ~/.codex/automations/daily-trusted-career-poll/automation.toml
grep '^status' ~/.codex/automations/daily-trusted-career-poll/automation.toml
```

Then set decision 6 to done in `CLAUDE.md` → 00a.

### 5. Laptop agent health (any day)

```bash
launchctl print gui/$(id -u)/com.myro.inference-drain | grep -E "state|last exit"
tail -20 /Users/incognito/myro-job-scraper/logs/inference_$(date +%Y_%m_%d).log
```

`Daily cycle skipped_busy` is normal: the previous hour's drain is still running. Repeated
`Daily cycle failed …` lines are not normal; read the named step.

### 6. Dated follow-ups

- **2026-10-17 — enrichment checkpoint (decision 9).** Count jobs with `enrichment_status` in
  (`pending`, `retryable`, `processing`). Under 5,000 means stay local. Over 5,000 means bring the owner the
  paid open-weight option with a cost estimate. Don't switch on your own.
- **Before 2026-12-01 — `railway.json` is deprecated.** Run `railway config migrate`, review the
  generated `.railway/railway.ts`, and keep cron `30 19 * * *`, the Dockerfile build and restart `NEVER`.
- **Monthly — Dream Sports (decision 12).** Check https://www.dreamsports.group/careers/ for a
  live job board; re-add it only through a direct ATS route.
- **True_Yodha staleness alert (decision 7)** is a task in the True_Yodha repo, not this one.

## Guardrails

- CHANGE DISCIPLINE applies: run the existing commands first; propose code changes only after a
  concrete failure, and get the owner's approval before writing them.
- Never handle secrets. If a variable is missing on Railway, the owner loads it with the stdin
  command in `docs/RAILWAY.md` history (values never pass through the agent).
- Don't start a laptop scrape (`daily_poll.py` / `daily_cycle.py` without `--inference-only`) while
  the Railway run is in progress; two publishers would race the same companies.
