# Open-Weight Enrichment Preset

Use this contract for local LM Studio or any approved remote OpenAI-compatible
endpoint serving an open-weight model. The scraper sends the extraction prompt,
system message, `temperature=0.0`, and `max_tokens` through the API, so the
server-side preset does not need to carry the full job-enrichment instructions.

## Recommended local preset: `mirror-cv-fast`

Model:

- `google/gemma-3-4b` for normal enrichment (`MODEL_SPEED=fast`)
- `deepseek-r1-0528-qwen3-8b-mlx` only when quality is more important than speed (`MODEL_SPEED=quality`)

System prompt:

```text
You are a precise job data extractor. Return one valid JSON object only. No explanation, no markdown, no extra text.
```

Runtime settings:

| Setting | Value |
|---|---|
| Temperature | `0.0` |
| Response length | Short; API currently sets `768` tokens for fast mode |
| Context length | At least `2048` tokens |
| Structured output | Optional; if enabled, allow exactly `job_summary`, `role_domain`, and `skills` |

## Expected API behavior

`scraper/enricher.py` sends:

- `role_domain`: one controlled functional area
- `job_summary`: one short factual role summary
- `skills`: up to 10 Lightcast skills from the supplied candidate list, each with `name` and `required_level`

The model must return JSON shaped like:

```json
{"job_summary": "Build and maintain data services.", "role_domain": "Software Engineering", "skills": [{"name": "Python (Programming Language)", "required_level": 3}]}
```

The code validates everything after the model responds:

- Unknown `role_domain` values are dropped.
- `job_summary` is capped at 100 words.
- Skill strings not matching the Lightcast L3 taxonomy are dropped.
- `required_level` is constrained to `1` through `4`.
- Backward-compatible `main_skills` is derived from `skills`; `side_skills` is deprecated and remains empty.
- Extra fields are ignored by the pipeline but should not be emitted.

## Quick readiness check

For local LM Studio, from the repo root:

```bash
curl -s http://localhost:1234/v1/models
```

Confirm the loaded model ID matches `scraper/.env`:

```bash
MODEL_SPEED=fast
INFERENCE_MODEL_FAST=google/gemma-3-4b
```

For a remote open-weight endpoint, configure:

```bash
INFERENCE_BASE_URL=https://<approved-open-weight-host>/v1
INFERENCE_API_KEY=<provider-token-or-placeholder>
INFERENCE_MODEL=google/gemma-3-4b
OPEN_WEIGHT_MODEL_ALLOWLIST=google/gemma-3-4b
```

The allowlist is required for remote endpoints so the scraper does not silently
drift to a closed/proprietary model.

For Cloudflare Workers AI specifically, see `scraper/CLOUDFLARE_WORKERS_AI.md`.
The scraper supports `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_WORKERS_AI_MODEL`, and
`CLOUDFLARE_WORKERS_AI_MODEL_ALLOWLIST`.
