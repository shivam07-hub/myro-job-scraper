# Upskilling Question Bank

This package builds verified MCQs for the four approved pilot skills:

- Machine Learning
- Product Strategy
- Management Consulting
- Financial Accounting

It is isolated from the jobs pipeline and uses LM Studio only.

## Candidate Input

Create a git-ignored JSONL file under `scraper/question_bank_inputs/`.
Each line is one transient source candidate:

```json
{"skill_key":"Machine Learning","source_url":"https://example.org/source","candidate_text":"Raw candidate used only in memory","target_level":2}
```

`candidate_text` is hashed, normalized, and discarded. It is never written to
question-bank checkpoints or Supabase.

## Local Models

Set these in `scraper/.env`:

```bash
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_API_KEY=lm-studio
QUESTION_NORMALIZER_MODEL=<local-model-id>
QUESTION_VERIFIER_MODEL=<different-local-model-id>
```

The verifier override is preferred. When omitted, the normalizer model is reused
and local diagnostics record `same_model_verifier=true`.

The CLI refuses non-loopback LLM URLs.

## Commands

From `scraper/`:

```bash
# Supabase schema + four taxonomy keys only; does not require LM Studio
python -m question_bank.cli --preflight-only

# Full local pipeline, no Supabase writes
python -m question_bank.cli \
  --input question_bank_inputs/pilot.jsonl \
  --dry-run

# Resume an interrupted run
python -m question_bank.cli \
  --input question_bank_inputs/pilot.jsonl \
  --resume-run qb_20260611_120000 \
  --dry-run

# Publish guarded active/review rows
python -m question_bank.cli \
  --input question_bank_inputs/pilot.jsonl \
  --publish
```

Dry-run is the default when `--publish` is absent. Production writes are batched
and use the conflict key `skill_id,level,dedupe_hash`.

## Publication Rules

Only questions whose independent verifier agrees with the answer key can become
`active`. Ambiguity, answer disagreement, large level disagreement, verifier
failure, and near-duplicate detection produce `review`.

Existing active rows are never downgraded or overwritten by routine reruns.

## Diagnostics

Copyright-safe run records are written to:

```text
logs/question_bank/<run_id>/
  normalized.jsonl
  verified.jsonl
  rejected.jsonl
  summary.json
```

Rejected rows contain source URLs, hashes, and reasons, but no source prose.

