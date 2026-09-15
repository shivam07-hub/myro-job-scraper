# Cloudflare Workers AI Setup

Use this when moving Phase 2 enrichment off the Mac while keeping the repo rule:
remote inference must be OpenAI-compatible and must serve an explicitly
allowlisted open-weight model.

Official docs:
- OpenAI-compatible endpoint: https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/
- Pricing/free allocation: https://developers.cloudflare.com/workers-ai/platform/pricing/

## Recommended first model

Start with:

```bash
@cf/meta/llama-3.1-8b-instruct-fp8-fast
```

Reason: it is one of Cloudflare's lower-cost fast text-generation models and is
good enough for a JSON extraction smoke test. If profile quality is weak, test
`@cf/google/gemma-4-26b-a4b-it` next.

## Required `.env` values

Add these to `scraper/.env`:

```bash
CLOUDFLARE_ACCOUNT_ID=<account-id>
CLOUDFLARE_API_TOKEN=<workers-ai-api-token>
CLOUDFLARE_WORKERS_AI_MODEL=@cf/meta/llama-3.1-8b-instruct-fp8-fast
CLOUDFLARE_WORKERS_AI_MODEL_ALLOWLIST=@cf/meta/llama-3.1-8b-instruct-fp8-fast
```

Do not set `INFERENCE_BASE_URL` at the same time unless intentionally
overriding the derived Cloudflare URL. The scraper derives:

```bash
https://api.cloudflare.com/client/v4/accounts/<account-id>/ai/v1
```

## Dashboard steps

1. Open Cloudflare Dashboard.
2. Copy the Account ID from the account overview URL/details.
3. Create an API token with Workers AI access.
4. Paste the token into `CLOUDFLARE_API_TOKEN`.

## Smoke test

From `scraper/`:

```bash
python test_cloudflare_workers_ai.py
```

Expected result:
- provider is `cloudflare_workers_ai`
- HTTP call succeeds
- response parses as compact JSON

## Batch strategy

Use small batches first:

```bash
ENRICH_WORKERS=2 python main.py --company "<company-or-folder>" --enrich-only --company-cap 100
```

Track Cloudflare neuron usage in the Workers AI dashboard. Free allocation is
10,000 neurons/day and resets at 00:00 UTC.
