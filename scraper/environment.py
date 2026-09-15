"""The scraper's declared environment surface.

Every environment key this pipeline reads is declared here once, with the
capability that needs it and whether that capability can run without it.

Two ``.env`` files exist in this repository and they belong to different
consumers:

* ``<repo>/.env``        — read by Docker Compose for the Firecrawl stack.
* ``<repo>/scraper/.env`` — read by this module for every Python entry point.

Nothing outside this module should call ``load_dotenv`` or guess a key name.
A missing key is an operator error that must surface *before* irreversible
work, not after: publication commits source rows long before it hands the run
to Stage A, so a late ``RuntimeError`` there costs a full re-run.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent / ".env"


@dataclass(frozen=True)
class EnvKey:
    """One declared environment key.

    ``capability`` is what the key unlocks, not which CLI reads it — several
    commands share a capability, and a command may need only some of them.
    """

    name: str
    capability: str
    purpose: str
    required: bool = True
    default: str = ""
    secret: bool = False


CAPABILITIES: dict[str, str] = {
    "supabase": "read and write the jobs database",
    "stage_a": "hand a published run to Myro's durable skill-floor queue",
    "analytics_refresh": "refresh the Myro intel snapshot after a publish",
    "firecrawl_cloud": "spend Firecrawl cloud credits during discovery",
    "firecrawl_local": "use the self-hosted Firecrawl Docker stack",
}

KEYS: tuple[EnvKey, ...] = (
    EnvKey("SUPABASE_URL", "supabase", "Supabase project REST URL"),
    EnvKey(
        "SUPABASE_SERVICE_KEY", "supabase",
        "service-role key; the only role allowed to write jobs", secret=True,
    ),
    EnvKey(
        "MYRO_BACKEND_URL", "stage_a",
        "True_Yodha backend base URL; the hand-off posts to "
        "{base}/internal/scrape/landed",
    ),
    EnvKey(
        "SCRAPE_WEBHOOK_TOKEN", "stage_a",
        "shared secret sent as the X-Scrape-Token header; must byte-match the "
        "backend's own value", secret=True,
    ),
    EnvKey(
        "MYRO_ANALYTICS_REFRESH_SECRET", "analytics_refresh",
        "secret for the intel snapshot refresh; absence only skips the refresh",
        required=False, secret=True,
    ),
    EnvKey(
        "FIRECRAWL_CLOUD_API_KEY", "firecrawl_cloud",
        "cloud API key; discovery spends real credits with it",
        required=False, secret=True,
    ),
    EnvKey(
        "FIRECRAWL_URL", "firecrawl_local",
        "self-hosted Firecrawl base URL; empty means the cloud default",
        required=False, default="",
    ),
)

_BY_CAPABILITY: dict[str, tuple[EnvKey, ...]] = {
    capability: tuple(key for key in KEYS if key.capability == capability)
    for capability in CAPABILITIES
}


class EnvironmentError_(RuntimeError):
    """A required key is absent. Carries the operator's next action."""


def load_environment(env_file: Path | None = None) -> Path | None:
    """Load ``scraper/.env`` once. Returns the file read, or None if absent.

    Existing process environment always wins, matching ``load_dotenv``'s own
    contract, so an operator can override a single key for one invocation.
    """
    path = env_file or ENV_FILE
    if not path.exists():
        return None
    load_dotenv(path)
    return path


def _values(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def missing(
    *capabilities: str, env: Mapping[str, str] | None = None
) -> list[EnvKey]:
    """Required keys of these capabilities that are absent or blank."""
    values = _values(env)
    absent: list[EnvKey] = []
    for capability in capabilities:
        if capability not in CAPABILITIES:
            raise KeyError(f"unknown capability {capability!r}")
        for key in _BY_CAPABILITY[capability]:
            if key.required and not (values.get(key.name) or "").strip():
                absent.append(key)
    return absent


def require(*capabilities: str, env: Mapping[str, str] | None = None) -> None:
    """Fail now, with the file path and every missing key, or return silently.

    Call this before the first irreversible write of a command, never at the
    point of use.
    """
    absent = missing(*capabilities, env=env)
    if not absent:
        return
    wanted = ", ".join(CAPABILITIES[c] for c in capabilities)
    lines = [
        f"Cannot {wanted}: {len(absent)} required key(s) missing from {ENV_FILE}",
    ]
    lines.extend(f"  {key.name} — {key.purpose}" for key in absent)
    lines.append(f"Add them to {ENV_FILE} and re-run.")
    raise EnvironmentError_("\n".join(lines))


def report(env: Mapping[str, str] | None = None) -> str:
    """Operator-facing status. Reports presence only — never a value."""
    values = _values(env)
    loaded = ENV_FILE if ENV_FILE.exists() else None
    lines = [
        f"env file: {loaded or f'{ENV_FILE} (absent)'}",
        "",
        f"{'KEY':<32} {'CAPABILITY':<18} {'REQ':<4} SET",
    ]
    for key in KEYS:
        present = bool((values.get(key.name) or "").strip())
        lines.append(
            f"{key.name:<32} {key.capability:<18} "
            f"{'yes' if key.required else 'no':<4} {'yes' if present else 'NO'}"
        )
    blocked = [
        capability for capability in CAPABILITIES
        if missing(capability, env=env)
    ]
    lines.append("")
    lines.append(
        "blocked capabilities: " + (", ".join(blocked) if blocked else "none")
    )
    return "\n".join(lines)


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report which scraper capabilities the environment can run"
    )
    parser.add_argument(
        "--require", nargs="*", default=[], metavar="CAPABILITY",
        help="exit non-zero unless these capabilities are fully configured",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_environment()
    print(report())
    if args.require:
        try:
            require(*args.require)
        except EnvironmentError_ as exc:
            print(f"\n{exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
