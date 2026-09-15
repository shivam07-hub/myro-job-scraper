import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse
from environment import load_environment

load_environment()

# ── Open-weight inference ────────────────────────────────────────────────────
_LOCAL_INFERENCE_BASE_URL = "http://localhost:1234/v1"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_CLOUDFLARE_HOST = "api.cloudflare.com"


@dataclass(frozen=True)
class InferenceConfig:
    base_url: str
    api_key: str
    model: str
    provider: str
    model_allowlist: tuple[str, ...]


@dataclass(frozen=True)
class JobEmbeddingConfig:
    base_url: str
    api_key: str
    model: str
    dimensions: int


def _first_env(values: Mapping[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = (values.get(name) or "").strip()
        if value:
            return value
    return default


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _is_loopback_base_url(base_url: str) -> bool:
    return urlparse(base_url).hostname in _LOOPBACK_HOSTS


def _cloudflare_workers_ai_base_url(values: Mapping[str, str]) -> str:
    account_id = _first_env(values, "CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID")
    model = _first_env(values, "CLOUDFLARE_WORKERS_AI_MODEL")
    if not account_id or not model:
        return ""
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"


def _is_cloudflare_workers_ai_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    return parsed.hostname == _CLOUDFLARE_HOST and "/ai/v1" in parsed.path


def resolve_inference_config(env: Mapping[str, str] | None = None) -> InferenceConfig:
    """Resolve local LM Studio or an allowlisted remote open-weight endpoint."""
    values = os.environ if env is None else env
    cloudflare_base_url = _cloudflare_workers_ai_base_url(values)
    base_url = _first_env(
        values,
        "INFERENCE_BASE_URL",
        "OPEN_WEIGHT_BASE_URL",
        default=cloudflare_base_url
        or _first_env(values, "LM_STUDIO_BASE_URL", default=_LOCAL_INFERENCE_BASE_URL),
    ).rstrip("/")
    using_cloudflare = _is_cloudflare_workers_ai_base_url(base_url)
    api_key = _first_env(
        values,
        "INFERENCE_API_KEY",
        "OPEN_WEIGHT_API_KEY",
        *(("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY") if using_cloudflare else ()),
        "LM_STUDIO_API_KEY",
        default="lm-studio",
    )

    speed = (values.get("MODEL_SPEED") or "fast").strip().lower()
    fast_model = _first_env(
        values,
        "INFERENCE_MODEL_FAST",
        "OPEN_WEIGHT_MODEL_FAST",
        "LM_STUDIO_MODEL_FAST",
        default="google/gemma-3-4b",
    )
    quality_model = _first_env(
        values,
        "INFERENCE_MODEL_QUALITY",
        "OPEN_WEIGHT_MODEL_QUALITY",
        "LM_STUDIO_MODEL_QUALITY",
        default="deepseek-r1-0528-qwen3-8b-mlx",
    )
    model = _first_env(
        values,
        "INFERENCE_MODEL",
        "OPEN_WEIGHT_MODEL",
        *(("CLOUDFLARE_WORKERS_AI_MODEL",) if using_cloudflare else ()),
        "LM_STUDIO_MODEL",
        default=fast_model if speed == "fast" else quality_model,
    )
    if not model:
        raise ValueError("inference model name is required")

    allowlist = _split_csv(
        _first_env(
            values,
            "INFERENCE_MODEL_ALLOWLIST",
            "OPEN_WEIGHT_MODEL_ALLOWLIST",
            "CLOUDFLARE_WORKERS_AI_MODEL_ALLOWLIST",
        )
    )
    if _is_loopback_base_url(base_url):
        provider = "local"
    elif using_cloudflare:
        provider = "cloudflare_workers_ai"
    else:
        provider = "remote_open_weight"

    if provider in {"remote_open_weight", "cloudflare_workers_ai"}:
        if not allowlist:
            raise ValueError("remote open-weight inference requires an explicit model allowlist")
        if model not in allowlist:
            raise ValueError(f"inference model {model!r} is not in the open-weight allowlist")

    return InferenceConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        provider=provider,
        model_allowlist=allowlist,
    )


def resolve_job_embedding_config(
    env: Mapping[str, str] | None = None,
) -> JobEmbeddingConfig:
    """Resolve the local-only model used by semantic job retrieval.

    Embeddings are an independent, source-first lane.  They never inherit a
    remote generation endpoint: both job documents and Myro queries must use
    the exact same locally hosted model and dimensionality.
    """
    values = os.environ if env is None else env
    base_url = _first_env(
        values,
        "JOB_EMBEDDING_BASE_URL",
        "LM_STUDIO_BASE_URL",
        default=_LOCAL_INFERENCE_BASE_URL,
    ).rstrip("/")
    if not _is_loopback_base_url(base_url):
        raise ValueError("job embeddings must use a loopback LM Studio endpoint")

    model = _first_env(
        values,
        "JOB_EMBEDDING_MODEL",
        default="text-embedding-nomic-embed-text-v1.5",
    )
    if not model:
        raise ValueError("job embedding model name is required")
    raw_dimensions = _first_env(values, "JOB_EMBEDDING_DIMENSIONS", default="768")
    try:
        dimensions = int(raw_dimensions)
    except ValueError as exc:
        raise ValueError("JOB_EMBEDDING_DIMENSIONS must be an integer") from exc
    if dimensions < 1:
        raise ValueError("JOB_EMBEDDING_DIMENSIONS must be positive")

    return JobEmbeddingConfig(
        base_url=base_url,
        api_key=_first_env(
            values,
            "JOB_EMBEDDING_API_KEY",
            "LM_STUDIO_API_KEY",
            default="lm-studio",
        ),
        model=model,
        dimensions=dimensions,
    )


_INFERENCE_CONFIG = resolve_inference_config()
INFERENCE_BASE_URL = _INFERENCE_CONFIG.base_url
INFERENCE_API_KEY = _INFERENCE_CONFIG.api_key
INFERENCE_MODEL = _INFERENCE_CONFIG.model
INFERENCE_PROVIDER = _INFERENCE_CONFIG.provider
INFERENCE_MODEL_ALLOWLIST = _INFERENCE_CONFIG.model_allowlist

_JOB_EMBEDDING_CONFIG = resolve_job_embedding_config()
JOB_EMBEDDING_BASE_URL = _JOB_EMBEDDING_CONFIG.base_url
JOB_EMBEDDING_API_KEY = _JOB_EMBEDDING_CONFIG.api_key
JOB_EMBEDDING_MODEL = _JOB_EMBEDDING_CONFIG.model
JOB_EMBEDDING_DIMENSIONS = _JOB_EMBEDDING_CONFIG.dimensions

# Backward-compatible aliases for older scraper modules and local env files.
LM_STUDIO_BASE_URL = INFERENCE_BASE_URL
LM_STUDIO_API_KEY = INFERENCE_API_KEY
LM_STUDIO_MODEL = INFERENCE_MODEL
_speed = os.getenv("MODEL_SPEED", "fast").lower()

# ── Firecrawl — SDK-based. Set FIRECRAWL_URL=http://localhost:3002 for Docker.
# Defaults to cloud API (api.firecrawl.dev) if unset or set to the cloud URL.
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
FIRECRAWL_URL     = os.getenv("FIRECRAWL_URL", "")   # empty = cloud default
FIRECRAWL_CLOUD_API_KEY = os.getenv("FIRECRAWL_CLOUD_API_KEY", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent          # repo root

PORTALS_PATH = os.getenv(
    "PORTALS_PATH",
    str(_ROOT / "KNOWN_PORTALS.md"),
)
OUTPUT_BASE = os.getenv(
    "OUTPUT_BASE",
    str(_ROOT / "All_CSV_Outputs"),
)

# ── Scraper tuning ────────────────────────────────────────────────────────────
ENRICH_WORKERS         = int(os.getenv("ENRICH_WORKERS",         "4"))
WORKDAY_PAGE_SIZE      = int(os.getenv("WORKDAY_PAGE_SIZE",      "20"))
REQUEST_TIMEOUT        = int(os.getenv("REQUEST_TIMEOUT",        "30"))
# Listing-pagination ceiling per Workday tenant. Raised 500→5000 so large service
# integrators (Accenture ~3k India) are fully LISTED (metadata only — cheap) before the
# quality-aware cap ranks and selects. Small tenants break naturally well below this.
WORKDAY_MAX_JOBS       = int(os.getenv("WORKDAY_MAX_JOBS",       "100000"))
# Default JD-fetch cap for the standard path; the quality-cap path passes an explicit
# limit == the company cap so JDs are fetched for exactly the selected set.
WORKDAY_JD_FETCH_LIMIT = int(os.getenv("WORKDAY_JD_FETCH_LIMIT", "500"))
