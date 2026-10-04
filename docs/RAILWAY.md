# Railway: daily source poll

Decided 2026-10-03 (CLAUDE.md, PENDING WORK → 00a). Railway runs the daily
scrape → resolve → publish at **01:00 IST**. The laptop only runs inference
(embeddings and enrichment) through its hourly launchd agent. Publication no
longer depends on the Mac being awake.

## What is in the repo

| File | Role |
|---|---|
| `Dockerfile` | Python 3.13 image with `scraper/requirements.txt` (Scrapling fetcher included). Outputs and logs are symlinked onto the volume at `/data`. |
| `.dockerignore` | Keeps every `.env` file, the 2.4 GB `All_CSV_Outputs/`, and `logs/` out of the image. |
| `railway.json` | Dockerfile build; cron `30 19 * * *` (19:30 UTC = 01:00 IST); no restarts. A cron job runs once and exits. |
| `scraper/railway_poll.sh` | Checks the volume and the required secrets, then runs `daily_poll.py --scope india`. |

## Owner steps (secrets and login stay with you)

1. Install the CLI: `brew install railway`
2. Log in: `railway login`
3. In the Railway dashboard, create a project, add a service from the GitHub repo
   `shivam07-hub/myro-job-scraper`, branch `main` (merge PR #1 first).
4. In that service's **Variables**, paste the four required secrets from
   `scraper/.env`: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `MYRO_BACKEND_URL`,
   `SCRAPE_WEBHOOK_TOKEN`. Optional: `MYRO_ANALYTICS_REFRESH_SECRET`. Do not
   set `FIRECRAWL_URL`: there is no Firecrawl stack in the container.
5. Tell Claude it's done.

## Claude steps after that

1. `railway link` to the service; `railway volume add --mount-path /data` (a few GB).
2. Confirm the cron schedule from `railway.json` is active.
3. Trigger one run, watch it end to end (publish + Stage A hand-off), and check
   `job_source_runs` in Supabase.
4. On the first green run, set the Codex automation `daily-trusted-career-poll`
   to `PAUSED` (decision 6).

## Notes

- Auto-written caches (`workday_registry.json`, `baseline_ledger.json`) live in
  the image, so each deploy resets them to the committed version. They are
  rebuilt during runs; commit learned entries from the laptop when they matter.
- A run takes ~10 hours. Railway skips a cron fire while the previous run is
  still going.
- Silence detection (no run at all) is True_Yodha's 36-hour staleness alert,
  not Railway's (decision 7).
