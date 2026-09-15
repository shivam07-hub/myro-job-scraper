# Upskilling Question-Bank Pipeline Design

**Date:** 2026-06-11

**Status:** Approved for implementation

## Goal

Populate the existing Supabase `skill_questions` table with normalized,
independently verified multiple-choice questions for:

- Machine Learning
- Product Strategy
- Management Consulting
- Financial Accounting

Each skill targets 50-60 active questions, with at least 10 active questions at
each level from 1 through 5.

## Constraints

- All LLM calls use LM Studio at `http://localhost:1234/v1`.
- Cloud LLM APIs are forbidden.
- Existing job scraping and enrichment behavior must not change.
- Source prose must not be retained verbatim after candidate extraction.
- The pipeline may store normalized questions, generated answer keys and
  explanations, hashes, source URLs, and local diagnostics.
- `status='active'` is only allowed after an independent answer-key pass agrees.
- Verification should use a separate local model when one is configured.
- The existing Supabase table is the only production persistence target. Local
  JSONL files hold resumability and audit diagnostics.

## Architecture

The feature lives in an isolated `scraper/question_bank/` package and has its
own CLI. It imports shared configuration and JSON parsing patterns but does not
change `main.py`, job providers, job enrichment, or `csv_importer.py`.

```text
source manifest / candidate JSONL
    -> source ingestion
    -> raw candidate hash
    -> LM Studio normalization
    -> deterministic validation
    -> exact and near dedupe
    -> independent LM Studio verification
    -> active or review
    -> dry-run report or Supabase upsert
```

## File Layout

```text
scraper/question_bank/
  __init__.py
  cli.py
  config.py
  dedupe.py
  llm.py
  models.py
  pipeline.py
  sources.py
  state.py
  supabase_writer.py
  pilot_sources.json

scraper/tests/question_bank/
  test_dedupe.py
  test_models.py
  test_pipeline.py
  test_sources.py
  test_state.py
  test_supabase_writer.py
```

Generated runs live under the git-ignored `logs/question_bank/<run_id>/`.

## Source Ingestion

The pilot supports a copyright-safe JSONL adapter. Each input record contains:

```json
{
  "skill_key": "Machine Learning",
  "source_url": "https://example.org/source",
  "candidate_text": "transient source question text"
}
```

`candidate_text` is read into memory, hashed, sent to normalization, and then
discarded. Checkpoints never write it. The manifest identifies the four
canonical skills and one or more JSONL inputs. Future direct-HTTP or Firecrawl
adapters can produce the same in-memory candidate contract.

The pipeline rejects non-HTTP provenance URLs, missing skills, empty candidates,
and records whose `skill_key` does not resolve exactly in Supabase.

## Normalization

The normalization prompt receives:

- Canonical skill name
- Optional skill description from Supabase
- Target level, when the run is filling a level deficit
- One transient source candidate

It returns JSON containing:

- `question_text`
- `options`
- `correct_index`
- `explanation`
- `level`
- `rejected`
- `rejection_reason`

The model must rewrite rather than quote the source. It must reject candidates
that cannot become one objective, self-contained MCQ.

Deterministic validation additionally requires:

- Exactly four distinct, non-empty options
- `correct_index` from 0 through 3
- Level from 1 through 5
- One non-empty sentence for the explanation
- No `all of the above` or `none of the above`
- No answer cues or duplicated option text
- Reasonable field-length limits

## Difficulty Scale

- Level 1: terminology, definitions, and direct recall
- Level 2: concept recognition and straightforward interpretation
- Level 3: applied scenarios and procedural choice
- Level 4: multi-factor analysis and non-obvious tradeoffs
- Level 5: architecture, strategy, failure modes, and competing constraints

## Dedupe

Three dedupe layers are used:

1. `raw_hash`: SHA-256 of Unicode-normalized transient source text. It prevents
   repeat normalization during resumed runs.
2. `dedupe_hash`: SHA-256 of canonicalized normalized question text. It is the
   Supabase conflict key with `skill_id` and `level`.
3. Near-duplicate detection: normalized token similarity marks paraphrases as
   `review` instead of publishing them.

The normalized text canonicalizer applies Unicode NFKC, lowercase conversion,
smart-quote normalization, whitespace collapse, and terminal punctuation
removal.

## Independent Verification

The verifier receives only:

- Canonical skill and optional description
- Normalized question
- Deterministically shuffled options

It does not receive the normalizer's answer or explanation. It returns:

- Chosen shuffled option index
- `ambiguous`
- One-sentence rationale
- Suggested level

The answer is mapped back to the original option order. A row becomes `active`
only when:

- The verifier chooses the same answer
- The verifier does not mark the question ambiguous
- Deterministic validation passes
- No exact or near duplicate exists
- The suggested level differs by no more than one

All other valid normalized rows become `review`. Verification uses
`QUESTION_VERIFIER_MODEL` when configured; otherwise it uses the normalizer
model and records `same_model_verifier=true` in local diagnostics.

The public product may expose questions and explanations and allow user appeals.
For this reason, generated explanations must state the decisive reason for the
answer rather than merely repeat the option.

## Resumability

Each run writes atomic JSONL checkpoints after every candidate:

- `normalized.jsonl`: normalized, copyright-safe records
- `verified.jsonl`: verification results and status
- `rejected.jsonl`: hashes, URLs, and rejection reasons only
- `summary.json`: counts by skill, level, status, and reason

No checkpoint contains source candidate prose. `--resume-run <run_id>` loads
processed raw hashes and continues from the next candidate.

## Supabase Writes

Before writes, the CLI:

1. Reads the Supabase OpenAPI document.
2. Confirms the expected `skill_questions` columns.
3. Resolves each manifest skill against `skills.taxonomy_key`.
4. Loads existing question hashes for the selected skills.
5. Confirms `--publish` was explicitly supplied.

Rows are batched in groups of 100 and upserted on
`skill_id,level,dedupe_hash`.

Conflict policy:

- Never replace an existing `active` row with `review`.
- Allow a re-verified `review` row to become `active`.
- Do not overwrite an active question's content during routine reruns.
- Always send an explicit status; never rely on the table default.

`--dry-run` executes local ingestion, normalization, validation, dedupe, and
verification but performs no Supabase writes.

## Diagnostics

The run summary reports:

- Ingested candidates
- Raw duplicates
- Normalizer rejects by reason
- Structural rejects by reason
- Exact normalized duplicates
- Near duplicates
- Verifier disagreements
- Ambiguous questions
- Same-model verification count
- `active` and `review` totals by skill and level
- Remaining count to reach 10 active questions per level

## Testing

Tests use injected fake normalizer, verifier, and Supabase adapters. No cloud
network calls are permitted.

- Model tests cover malformed questions and valid four-option questions.
- Dedupe tests cover punctuation, whitespace, Unicode quotes, and paraphrases.
- Pipeline tests cover agreement, disagreement, ambiguity, near duplicates,
  and deterministic option shuffling.
- State tests prove checkpoints omit source candidate prose and resume by hash.
- Writer tests prove dry runs make no writes and active rows are never
  downgraded.
- A local integration smoke calls LM Studio only when explicitly requested.

## Pilot Acceptance

The implementation pilot is accepted when:

- All four skills resolve against the live `skills` table.
- Unit and mocked end-to-end tests pass.
- A dry run can process a candidate JSONL without cloud LLMs.
- No generated checkpoint contains `candidate_text`.
- Only independently agreed questions are marked `active`.
- Real publication remains guarded by the explicit `--publish` flag.

