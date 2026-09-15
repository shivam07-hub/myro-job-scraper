"""
Provider contracts used by the modular scraper architecture.
"""
from __future__ import annotations

from schema import Portal

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

FALLBACK_FIRECRAWL_EXTRACT = "firecrawl_extract"


class ScrapeReason(str, Enum):
    """Typed outcome reason for every ProviderResult."""
    SUCCESS       = "success"        # jobs returned (may be empty list = genuinely 0)
    NO_JOBS       = "no_jobs"        # API OK but 0 matches for scope/filter
    API_BLOCKED   = "api_blocked"    # HTTP error / Cloudflare block / redirect
    CONFIG_ERROR  = "config_error"   # missing slug, bad endpoint, wrong tenant
    TIMEOUT       = "timeout"        # request timed out
    PARSE_ERROR   = "parse_error"    # response not parseable (unexpected format)
    PARTIAL       = "partial"        # some pages returned, but snapshot did not complete
    FALLBACK      = "fallback"       # routed to secondary provider


@dataclass
class ProviderResult:
    """
    Standard provider return shape.

    `reason`         — always set; use ScrapeReason enum.
    `fallback_policy` — set when runtime should route to a fallback provider.
    """
    jobs:             list[dict]
    reason:           ScrapeReason   = ScrapeReason.SUCCESS
    fallback_policy:  str | None     = None
    fallback_reason:  str | None     = None
    fallback_portal:  dict | None    = None

    @classmethod
    def success(cls, jobs: list[dict]) -> "ProviderResult":
        reason = ScrapeReason.SUCCESS if jobs else ScrapeReason.NO_JOBS
        return cls(jobs=jobs, reason=reason)

    @classmethod
    def error(cls, reason: ScrapeReason, note: str = "") -> "ProviderResult":
        return cls(jobs=[], reason=reason, fallback_reason=note or reason.value)

    @classmethod
    def partial(cls, jobs: list[dict], note: str) -> "ProviderResult":
        """Keep partial rows as evidence, never as a publishable snapshot."""
        return cls(
            jobs=jobs,
            reason=ScrapeReason.PARTIAL,
            fallback_reason=note or ScrapeReason.PARTIAL.value,
        )

    @classmethod
    def fallback(
        cls,
        *,
        policy: str,
        reason: str,
        portal: Portal | None = None,
    ) -> "ProviderResult":
        return cls(
            jobs=[],
            reason=ScrapeReason.FALLBACK,
            fallback_policy=policy,
            fallback_reason=reason,
            fallback_portal=portal,
        )


class Provider(Protocol):
    """Provider protocol for ATS/backend-specific scraping logic."""

    key: str

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        ...
