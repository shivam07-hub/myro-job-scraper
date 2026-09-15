"""
Open-weight enrichment — all LLM calls go through an OpenAI-compatible endpoint.
By default that endpoint is local LM Studio (`http://localhost:1234/v1`), but it
can be moved to an approved remote open-weight model server via `INFERENCE_*`
environment variables.

Single responsibility (v2, Dump 4+):
  enrich_job(job)
      Read job_title + job_description from canonical job dict.
      Ask the configured open-weight inference endpoint to extract:
        - role_domain  (functional area classification)
        - skills       (Lightcast L3 skills with required_level)
      Skills that do not match an L3 entry in lightcast_skills_taxonomy.json are dropped.
      L1 and L2 taxonomy levels are derivable from L3 via the taxonomy JSON — not stored here.
      Back-compat fields main_skills and side_skills are still populated.
      Writes into the job dict in-place and returns it.
      Safe to call if job_description is empty (returns job unchanged).
"""
from __future__ import annotations

import os
import json
import hashlib
import threading
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI
from config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    _speed as _MODEL_SPEED,
)
from jd_skill_evidence import extract_skill_evidence
from rag_skills import retrieve as _retrieve_skills
from normalizer import match_to_taxonomy, parse_json_response, clean_jd_for_llm
from schema import is_missing_jd_description

# Singleton — None until first use
_client: OpenAI | None = None
_ENRICHMENT_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()


class InferenceQuotaExceeded(RuntimeError):
    """Raised when the inference endpoint reports exhausted quota/rate allocation."""


class InferenceUnavailable(RuntimeError):
    """Raised when the configured inference endpoint cannot currently serve work."""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=INFERENCE_BASE_URL, api_key=INFERENCE_API_KEY)
    return _client

# ── Controlled vocabularies ────────────────────────────────────────────────────

_ROLE_DOMAIN_VALUES = {
    "Software Engineering",
    "Data & Analytics",
    "Finance",
    "Strategy & Consulting",
    "HR & People",
    "Sales & Marketing",
    "Operations",
    "Legal & Compliance",
    "Product Management",
    "Research & Science",
    "IT & Infrastructure",
    "Risk & Compliance",
    "General Management",
    "Supply Chain",
    "Manufacturing",
}

CANDIDATE_PROFILE_VERSION = "cv_profile_v1"

_PROFILE_ARRAY_CAPS = {
    "cv_positioning": (4, 120),
    "proof_points": (4, 90),
    "gap_risks": (3, 100),
    "project_suggestions": (3, 130),
    "resume_keywords": (10, 35),
    "interview_themes": (4, 55),
}


def _valid_role_domain(value) -> str | None:
    """Return a controlled role domain string; tolerate legacy non-scalar rows."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value in _ROLE_DOMAIN_VALUES else None


def has_terminal_core_enrichment(job: dict) -> bool:
    """True only when the trust-facing core card fields are complete.

    Taxonomy skills are valuable matching inputs, but skill-only output is not a
    complete card: users still need a factual summary and controlled domain to
    understand why the role is being proposed.  Jobs with no defensible
    taxonomy skill can still complete with those two trust-facing fields.
    """
    return bool(
        (job.get("job_summary") or "").strip()
        and _valid_role_domain(job.get("role_domain"))
    )

# ── Prompt ────────────────────────────────────────────────────────────────────


_ENRICH_PROMPT = """\
Job Title: {title}

JD excerpt:
{jd}

Explicit skills JSON, already taxonomy-grounded. Preserve unless clearly wrong:
{explicit_skill_evidence}

Candidate vocabulary. Choose ONLY names from this list:
{skills_list}

Return JSON with EXACTLY these keys:
1. job_summary: neutral role summary, max 35 words. No marketing, navigation, IDs, dates, location, markdown.
2. role_domain: exactly one of:
   "Software Engineering" | "Data & Analytics" | "Finance" | "Strategy & Consulting" |
   "HR & People" | "Sales & Marketing" | "Operations" | "Legal & Compliance" |
   "Product Management" | "Research & Science" | "IT & Infrastructure" |
   "Risk & Compliance" | "General Management" | "Supply Chain" | "Manufacturing"
3. skills: max 6 objects: {{"name":"<exact vocabulary name>","required_level":1|2|3|4}}.
   Level guide: L1 exposure/preferred/plus; L2 hands-on/proficient/1-3 yrs; L3 strong/lead/3-5 yrs; L4 expert/5+ yrs/principal.
   There is NO must-have vs nice-to-have split. Omit off-vocabulary skills.
   Do not fill the quota. Return fewer skills if the JD does not clearly support them.
   Never select a skill just because it appears in the approved vocabulary.

Return ONLY valid JSON:
{{"job_summary": "", "role_domain": null, "skills": []}}"""


# ── Public function ───────────────────────────────────────────────────────────

def enrich_job(job: dict) -> dict:
    """
    Extract role_domain and structured skills from job_description via the
    configured open-weight inference endpoint.
    Only runs if job_description is non-empty and skills are not already set.
    Mutates and returns the job dict.
    """
    jd = (job.get('job_description') or '').strip()
    if not jd:
        return job
    if is_missing_jd_description(jd):
        job['skills'] = []
        job['main_skills'] = []
        job['side_skills'] = []
        job['job_summary'] = job.get('job_summary') or jd
        job['candidate_profile'] = job.get('candidate_profile') or {}
        return job

    title  = (job.get('job_title') or '').strip()
    # Clean a COPY of the JD for the LLM (raw job_description is left untouched).
    jd_clean = clean_jd_for_llm(jd)
    candidate_pool = _retrieve_skills(title + " " + jd_clean[:1500], k=40)
    explicit_evidence = _compact_skill_evidence(extract_skill_evidence(jd_clean[:3000], candidate_pool))
    prompt_candidates = _prompt_skill_candidates(candidate_pool, explicit_evidence, limit=18)
    profile_hash = _candidate_profile_hash(
        job_id=str(job.get('job_id') or ''),
        title=title,
        jd_clean=jd_clean,
        candidates=prompt_candidates,
        explicit_evidence=explicit_evidence,
    )

    # Skip if already fully enriched with the current profile hash.
    if (job.get('skills') and job.get('main_skills')
            and _valid_role_domain(job.get('role_domain'))
            and job.get('job_summary')
            and _has_candidate_profile(job.get('candidate_profile'))
            and job.get('candidate_profile_hash') == profile_hash
            and job.get('candidate_profile_version') == CANDIDATE_PROFILE_VERSION):
        return job

    if explicit_evidence and not _force_llm_for_explicit_evidence():
        extracted = _validate_enrichment({}, explicit_evidence=explicit_evidence)
    else:
        cache_key = _candidate_profile_hash(
            job_id="",
            title=title,
            jd_clean=jd_clean,
            candidates=prompt_candidates,
            explicit_evidence=explicit_evidence,
        )
        extracted = _get_cached_enrichment(cache_key)
        if extracted is None:
            prompt = _build_enrich_prompt(
                title=title,
                jd_clean=jd_clean,
                explicit_evidence=explicit_evidence,
                prompt_candidates=prompt_candidates,
            )
            extracted = _llm_json(prompt, default={})
            if extracted:
                extracted = _validate_enrichment(extracted, explicit_evidence=explicit_evidence)
                _put_cached_enrichment(cache_key, extracted)

    if extracted or explicit_evidence:
        extracted = _validate_enrichment(extracted or {}, explicit_evidence=explicit_evidence)
        if not job.get('job_summary'):
            job['job_summary'] = extracted.get('job_summary') or ''
        current_role_domain = _valid_role_domain(job.get('role_domain'))
        if current_role_domain is None:
            job['role_domain'] = _valid_role_domain(extracted.get('role_domain')) or ''
        elif job.get('role_domain') != current_role_domain:
            job['role_domain'] = current_role_domain
        if not job.get('skills') or explicit_evidence:
            job['skills'] = extracted.get('skills', [])
        if not job.get('main_skills') or explicit_evidence:
            job['main_skills'] = extracted.get('main_skills', [])
        if not job.get('side_skills'):
            job['side_skills'] = extracted.get('side_skills', [])
        if _profile_enrichment_enabled() and extracted.get('candidate_profile'):
            job['candidate_profile'] = extracted['candidate_profile']
            job['candidate_profile_version'] = CANDIDATE_PROFILE_VERSION
            job['candidate_profile_hash'] = profile_hash
            job['candidate_profile_model'] = INFERENCE_MODEL
        if has_terminal_core_enrichment(job) and not (job.get('skills') or job.get('main_skills')):
            job['quality_status'] = 'enriched_no_taxonomy_skills'

    return job


# ── Internal helpers ──────────────────────────────────────────────────────────

def _candidate_profile_hash(
    *,
    job_id: str,
    title: str,
    jd_clean: str,
    candidates: list[str],
    explicit_evidence: list[dict],
) -> str:
    payload = {
        "version": CANDIDATE_PROFILE_VERSION,
        "job_id": job_id,
        "title": title,
        "jd": jd_clean,
        "candidates": candidates,
        "explicit_evidence": explicit_evidence,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _force_llm_for_explicit_evidence() -> bool:
    return os.getenv("ENRICH_FORCE_LLM", "").strip().lower() in {"1", "true", "yes"}


def _profile_enrichment_enabled() -> bool:
    return os.getenv("ENRICH_CANDIDATE_PROFILE", "").strip().lower() in {"1", "true", "yes"}


def _json_copy(data: dict) -> dict:
    return json.loads(json.dumps(data, ensure_ascii=False))


def _get_cached_enrichment(cache_key: str) -> dict | None:
    with _CACHE_LOCK:
        cached = _ENRICHMENT_CACHE.get(cache_key)
        return _json_copy(cached) if cached is not None else None


def _put_cached_enrichment(cache_key: str, data: dict) -> None:
    with _CACHE_LOCK:
        _ENRICHMENT_CACHE[cache_key] = _json_copy(data)


def _compact_skill_evidence(explicit_evidence: list[dict] | None, evidence_chars: int = 160) -> list[dict]:
    """Keep deterministic evidence useful without letting long JD lines bloat prompts."""
    compact: list[dict] = []
    seen: set[str] = set()
    for item in explicit_evidence or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out = {
            "name": name,
            "required_level": item.get("required_level"),
            "zone": item.get("zone"),
        }
        evidence = _trim_chars(item.get("evidence") or "", evidence_chars)
        if evidence:
            out["evidence"] = evidence
        compact.append(out)
        if len(compact) >= 10:
            break
    return compact


def _build_enrich_prompt(
    *,
    title: str,
    jd_clean: str,
    explicit_evidence: list[dict],
    prompt_candidates: list[str],
) -> str:
    return _ENRICH_PROMPT.format(
        title=title,
        jd=jd_clean[:900],
        explicit_skill_evidence=json.dumps(explicit_evidence, ensure_ascii=False, separators=(",", ":")),
        skills_list=", ".join(prompt_candidates[:12]),
    )


def _prompt_skill_candidates(candidate_pool: list[str], explicit_evidence: list[dict], limit: int = 18) -> list[str]:
    """Keep prompt vocabulary compact while always preserving explicit JD skills."""
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name:
            return
        key = name.lower()
        if key in seen:
            return
        out.append(name)
        seen.add(key)

    for item in explicit_evidence:
        if isinstance(item, dict):
            add(item.get("name"))
    for name in candidate_pool:
        add(name)
        if len(out) >= limit:
            break
    return out[:limit]


def _trim_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).strip()


def _trim_chars(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit].rstrip()


def _validate_candidate_profile(profile) -> dict:
    if not isinstance(profile, dict):
        profile = {}

    out = {
        "ideal_candidate_summary": _trim_words(str(profile.get("ideal_candidate_summary") or "").strip(), 60),
    }
    for key, (max_items, max_chars) in _PROFILE_ARRAY_CAPS.items():
        raw = profile.get(key) or []
        if not isinstance(raw, list):
            raw = []
        values = []
        seen = set()
        for item in raw:
            value = _trim_chars(str(item or ""), max_chars)
            dedupe = value.lower()
            if not value or dedupe in seen:
                continue
            values.append(value)
            seen.add(dedupe)
            if len(values) >= max_items:
                break
        out[key] = values
    if not out["ideal_candidate_summary"]:
        for key in ("cv_positioning", "proof_points"):
            if out.get(key):
                out["ideal_candidate_summary"] = _trim_words(out[key][0], 45)
                break
    if not out["ideal_candidate_summary"] and not any(out.get(key) for key in _PROFILE_ARRAY_CAPS):
        return {}
    return out


def _has_candidate_profile(profile) -> bool:
    return isinstance(profile, dict) and bool(str(profile.get("ideal_candidate_summary") or "").strip())


def _validate_enrichment(data: dict, explicit_evidence: list[dict] | None = None) -> dict:
    """
    Validate LLM output:
    - role_domain must be in the controlled vocabulary.
    - skills is ONE flat list of needed skills, each matched against the Lightcast
      L3 taxonomy and carrying a required_level (1-4). There is no primary/side
      split — importance is expressed through required_level. The canonical
      taxonomy name is used (not the LLM's raw string); the list is capped at 10.
    - main_skills mirrors the full canonical skill-name list (back-compat column
      True_Yodha still reads for chips); side_skills is always [] (deprecated).
    """
    data['role_domain'] = _valid_role_domain(data.get('role_domain'))

    # job_summary: clean prose, hard-capped at 100 words (sentence-aware trim as safety net).
    summary = (data.get('job_summary') or '').strip()
    if summary:
        words = summary.split()
        if len(words) > 100:
            trimmed = ' '.join(words[:100])
            # prefer ending on the last full sentence within the cap
            cut = max(trimmed.rfind('. '), trimmed.rfind('! '), trimmed.rfind('? '))
            summary = (trimmed[:cut + 1] if cut > 40 else trimmed).strip()
    data['job_summary'] = summary

    raw_skills = data.get('skills') or []
    # Back-compat: flatten any legacy main_skills/side_skills input into the single list.
    if not raw_skills and (data.get('main_skills') or data.get('side_skills')):
        raw_skills = [
            {"name": skill, "required_level": 2} for skill in (data.get('main_skills') or [])
        ] + [
            {"name": skill, "required_level": 1} for skill in (data.get('side_skills') or [])
        ]
    if not isinstance(raw_skills, list):
        raw_skills = []

    by_name: dict[str, dict] = {}

    def add_skill(name, level) -> None:
        canonical = match_to_taxonomy(name or '')
        if not canonical:
            return
        if not isinstance(level, int) or level not in (1, 2, 3, 4):
            level = 2
        existing = by_name.get(canonical)
        if existing:
            existing['required_level'] = max(existing['required_level'], level)
            return
        if len(by_name) >= 10:
            return
        by_name[canonical] = {'name': canonical, 'required_level': level}

    for item in explicit_evidence or []:
        if isinstance(item, dict):
            add_skill(item.get('name'), item.get('required_level'))

    for item in raw_skills:
        if isinstance(item, dict):
            name, level = item.get('name'), item.get('required_level')
        elif isinstance(item, str):
            name, level = item, None
        else:
            continue
        add_skill(name, level)

    validated = list(by_name.values())[:10]
    data['skills'] = validated
    data['main_skills'] = [s['name'] for s in validated]   # all needed skills (one bucket)
    data['side_skills'] = []                                # deprecated; always empty
    data['candidate_profile'] = _validate_candidate_profile(data.get('candidate_profile'))
    return data


def _llm_json(prompt: str, default):
    """Call the inference endpoint and parse JSON. Returns default on any failure."""
    # deepseek-r1 (quality) emits a reasoning_content block before the answer;
    # needs 2048 to guarantee JSON output after thinking tokens.
    # Fast models need enough headroom for a compact candidate_profile; the
    # prompt caps content tightly so this stays cheaper than retrying truncations.
    _max_tokens = 2048 if _MODEL_SPEED == "quality" else 512
    try:
        resp = _get_client().chat.completions.create(
            model=INFERENCE_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise job data extractor. Start your response with { immediately. No preamble, no markdown."},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ],
            temperature=0.0,
            max_tokens=_max_tokens,
        )
        choice = resp.choices[0]
        text = choice.message.content or ''
        # Restore the assistant prefill "{" — the API returns only the continuation.
        return _parse_llm_json_text(text, finish_reason=choice.finish_reason) if text else default
    except (APIConnectionError, APITimeoutError, InternalServerError) as e:
        raise InferenceUnavailable(str(e)) from e
    except Exception as e:
        message = str(e)
        if "429" in message or "daily free allocation" in message or "Too Many Requests" in message:
            raise InferenceQuotaExceeded(message) from e
        print(f"    [LLM ERROR]: {e}")
        return default


def _parse_llm_json_text(text: str, finish_reason: str | None = None):
    if text and not text.lstrip().startswith('{'):
        text = '{' + text
    parsed = parse_json_response(text) if text else None
    if parsed is not None:
        return parsed

    # Small open-weight models can emit a trailing comma before a closing
    # object/array delimiter. Remove only commas outside strings whose next
    # non-whitespace character is `]` or `}`.
    repaired = _remove_trailing_json_commas(text)

    # Cloudflare/local fast models can occasionally omit only the final
    # top-level closing brace while still reporting finish_reason=stop.
    # Repair only balanced-prefix JSON; do not guess through open strings.
    if finish_reason == "stop":
        repaired = _append_missing_json_closers(repaired)
    if repaired != text:
        return parse_json_response(repaired)
    return None


def _remove_trailing_json_commas(text: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    for index, ch in enumerate(text):
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            continue
        if ch == ",":
            cursor = index + 1
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor < len(text) and text[cursor] in "]}":
                continue
        out.append(ch)
    return "".join(out)


def _append_missing_json_closers(text: str) -> str:
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return text
            stack.pop()
    if in_string or not stack:
        return text
    return text + "".join(reversed(stack))
