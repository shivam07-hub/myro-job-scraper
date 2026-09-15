# `santifer/career-ops` audit

Audit date: 2026-07-12  
Upstream: https://github.com/santifer/career-ops (MIT)

## Decision

Use upstream as a discovery/provider reference, not as a replacement pipeline.
Myro already has the stronger production contract for this product: canonical
Supabase rows, lifecycle delisting, day-level verification, durable async
enrichment, Lightcast grounding, and personalized matching.

The upstream project's useful ideas are:

- direct adapters before browser extraction;
- a provider registry rather than one large scraper;
- flag-only URL/domain trust checks;
- deduplication, liveness checks, and repost detection;
- candidate-side structured evaluation and application tracking.

Its browser-per-job/CLI-agent orchestration is not appropriate for Myro's daily
company feed, and its model choices are not imported. This repository continues
to use only local or explicitly approved open-weight inference.

## Adopted in this cutover

The provider/board audit produced seven direct, full-JD India sources that were
validated, scraped, and published live:

| ATS | Company | Live India jobs |
|---|---|---:|
| Greenhouse | Celonis | 32 |
| Greenhouse | Glean | 26 |
| Greenhouse | Boomi | 26 |
| Greenhouse | Hightouch | 2 |
| Greenhouse | Hootsuite | 1 |
| Ashby | Deepgram | 2 |
| Ashby | Zapier | 3 |

ElevenLabs remains review-only. India appears mostly as secondary or broad
multi-location eligibility; promoting it without confirming location semantics
would weaken trust.

Ashby is now a first-class `KNOWN_PORTALS.md` section rather than a hardcoded
company-only exception. The India filter accepts an explicit India signal in a
title only when the structured location is broad (for example `APAC | Remote`),
and never infers location from arbitrary JD prose.

## Provider surface-area backlog

Only promote a provider after a real India company endpoint is observed and a
targeted scrape proves stable IDs, complete pagination, location semantics,
candidate-facing apply URLs, and usable JDs.

Priority direct-company ATS families present upstream but not yet first-class
here:

1. Teamtailor
2. Recruitee
3. Workable
4. BambooHR
5. Breezy
6. Comeet
7. Personio
8. Jibe
9. Softgarden
10. Avature (dedicated direct route; current JS cases remain portal-specific)

Lower priority for Myro are aggregator feeds such as RemoteOK, Remotive,
The Muse, Working Nomads, Hacker News, and similar boards. They may increase raw
volume, but they conflict with the north star: trusted cards sourced from the
employer's own career surface. Aggregators should not enter `KNOWN_PORTALS.md`
without a separate provenance and trust policy.

## Trust-model comparison

The upstream trust validator flags invalid/missing URLs, suspicious shortened
domains, and company/domain mismatches while allowlisting known ATS hosts. Myro
already has stronger live-state signals (`last_verified_live_at`,
`listing_confidence`, lifecycle retirement, source hashes). The incremental
idea worth adopting later is a source-time apply-domain validator that lowers
confidence or flags a card; it should never silently drop a job.

## Delta 4 product contract

The retention loop is based on trust, not volume:

1. Publish a newly observed role immediately with today's verified day.
2. Let it enter personalized search using only explicit deterministic evidence.
3. Prioritize lazy enrichment only when the role reaches a user's shortlist.
4. Require summary + controlled domain before enrichment is terminal.
5. Record Click Apply intent only against verified active card exposures.
6. Let the independent lifecycle loop retire vanished roles safely.

The north-star metric is `verified_apply_intent_daily.click_apply_intent_rate`.
It measures whether trusted recommendations lead users to begin an application,
not how many cards the scraper can collect.
