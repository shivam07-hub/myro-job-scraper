# Upskilling Question-Bank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated local-LM question-bank pipeline for Machine Learning, Product Strategy, Management Consulting, and Financial Accounting.

**Architecture:** A new `scraper/question_bank/` package ingests transient candidates, normalizes and verifies them through LM Studio, persists copyright-safe checkpoints, and performs guarded Supabase upserts. Existing job scraping and enrichment modules remain behaviorally unchanged.

**Tech Stack:** Python 3, pytest, OpenAI-compatible LM Studio API, Supabase Python client, JSONL checkpoints.

---

### Task 1: Domain Validation And Dedupe

**Files:**
- Create: `scraper/question_bank/__init__.py`
- Create: `scraper/question_bank/models.py`
- Create: `scraper/question_bank/dedupe.py`
- Test: `scraper/tests/question_bank/test_models.py`
- Test: `scraper/tests/question_bank/test_dedupe.py`

- [ ] **Step 1: Write failing tests**

Cover exactly four unique options, valid answer and level ranges, one-sentence
explanations, forbidden aggregate options, canonical text hashing, and
near-duplicate similarity.

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
pytest -q scraper/tests/question_bank/test_models.py scraper/tests/question_bank/test_dedupe.py
```

Expected: collection or import failure because the package does not exist.

- [ ] **Step 3: Implement minimal validation and dedupe**

Add typed dataclasses, structured validation results, SHA-256 helpers, and a
deterministic token similarity function.

- [ ] **Step 4: Verify the tests pass**

Run the same pytest command and expect zero failures.

### Task 2: Copyright-Safe Sources And State

**Files:**
- Create: `scraper/question_bank/sources.py`
- Create: `scraper/question_bank/state.py`
- Create: `scraper/question_bank/pilot_sources.json`
- Test: `scraper/tests/question_bank/test_sources.py`
- Test: `scraper/tests/question_bank/test_state.py`

- [ ] **Step 1: Write failing tests**

Cover JSONL ingestion, HTTP source URL validation, four-skill manifest loading,
atomic checkpoint append, omission of `candidate_text`, and raw-hash resume.

- [ ] **Step 2: Verify the tests fail**

```bash
pytest -q scraper/tests/question_bank/test_sources.py scraper/tests/question_bank/test_state.py
```

- [ ] **Step 3: Implement the adapters and state store**

Keep candidate prose in memory only. Persist hashes, normalized records,
verification records, and rejection metadata under `logs/question_bank/`.

- [ ] **Step 4: Verify the tests pass**

Run the same pytest command and expect zero failures.

### Task 3: Local Normalizer And Independent Verifier

**Files:**
- Create: `scraper/question_bank/config.py`
- Create: `scraper/question_bank/prompts.py`
- Create: `scraper/question_bank/llm.py`
- Test: `scraper/tests/question_bank/test_llm.py`

- [ ] **Step 1: Write failing tests**

Cover loopback-only base URL enforcement, model selection, defensive JSON
parsing, deterministic option shuffling, and answer-index remapping.

- [ ] **Step 2: Verify the tests fail**

```bash
pytest -q scraper/tests/question_bank/test_llm.py
```

- [ ] **Step 3: Implement local LM Studio clients**

Use the existing repository LM Studio environment variables. Add
`QUESTION_NORMALIZER_MODEL` and `QUESTION_VERIFIER_MODEL` overrides. Reject
non-loopback LLM URLs before any request.

- [ ] **Step 4: Verify the tests pass**

Run the same pytest command and expect zero failures.

### Task 4: Pipeline And Status Decisions

**Files:**
- Create: `scraper/question_bank/pipeline.py`
- Test: `scraper/tests/question_bank/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

Cover active agreement, review disagreement, review ambiguity, structural
rejection, exact duplicates, near duplicates, level disagreement, and resume.

- [ ] **Step 2: Verify the tests fail**

```bash
pytest -q scraper/tests/question_bank/test_pipeline.py
```

- [ ] **Step 3: Implement the pipeline**

Use injected normalizer and verifier interfaces so tests remain offline. Emit
copyright-safe diagnostics after every candidate.

- [ ] **Step 4: Verify the tests pass**

Run the same pytest command and expect zero failures.

### Task 5: Guarded Supabase Writer

**Files:**
- Create: `scraper/question_bank/supabase_writer.py`
- Test: `scraper/tests/question_bank/test_supabase_writer.py`

- [ ] **Step 1: Write failing tests**

Cover schema preflight, exact taxonomy resolution, dry-run no-op behavior,
batched writes, review promotion, and active-row downgrade prevention.

- [ ] **Step 2: Verify the tests fail**

```bash
pytest -q scraper/tests/question_bank/test_supabase_writer.py
```

- [ ] **Step 3: Implement safe upserts**

Load existing rows before writing and merge locally. Upsert only rows that are
new or valid promotions.

- [ ] **Step 4: Verify the tests pass**

Run the same pytest command and expect zero failures.

### Task 6: CLI And End-To-End Pilot

**Files:**
- Create: `scraper/question_bank/cli.py`
- Create: `scraper/question_bank/README.md`
- Test: `scraper/tests/question_bank/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Cover `--dry-run`, `--publish`, `--resume-run`, `--skill`, `--input`, and
mutual-exclusion guards.

- [ ] **Step 2: Verify the tests fail**

```bash
pytest -q scraper/tests/question_bank/test_cli.py
```

- [ ] **Step 3: Implement the CLI**

Default to the four-skill manifest and dry-run behavior. Require explicit
`--publish` for Supabase writes.

- [ ] **Step 4: Run the full focused suite**

```bash
pytest -q scraper/tests/question_bank
```

Expected: all question-bank tests pass without network access.

### Task 7: Documentation And Verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `RUN_HISTORY.md`

- [ ] **Step 1: Document exact commands and safeguards**

Record candidate JSONL format, LM Studio variables, dry-run, resume, publish,
and diagnostics paths.

- [ ] **Step 2: Run live read-only preflight**

Confirm the four skills and `skill_questions` table schema against Supabase.

- [ ] **Step 3: Run offline end-to-end smoke**

Use fake local adapters or test fixtures. LM Studio integration is reported as
unavailable if `localhost:1234` is not running.

- [ ] **Step 4: Run final verification**

```bash
pytest -q scraper/tests/question_bank
python -m compileall -q scraper/question_bank
git diff --check
```

Record exact results in the completion response.

