#!/usr/bin/env python3
"""Run one complete source-first daily cycle.

Order is deliberate for low-memory local operation:
1. poll career sources and publish source fields;
2. start/load the local embedding model and embed newly published jobs;
3. start/load the configured generative model when necessary;
4. drain the forward-only enrichment queue to zero.

Remote allowlisted open-weight inference skips the LM Studio bootstrap.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

import requests

from config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    INFERENCE_PROVIDER,
    JOB_EMBEDDING_API_KEY,
    JOB_EMBEDDING_BASE_URL,
    JOB_EMBEDDING_MODEL,
)


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
LOG_DIR = REPO_ROOT / "logs"


def build_commands(
    *,
    python: str,
    scope: str,
    company_cap: int,
    company: str | None,
    max_messages: int,
    max_embeddings: int,
) -> tuple[list[str], list[str], list[str]]:
    poll = [
        python,
        str(ROOT / "daily_poll.py"),
        "--scope",
        scope,
        "--company-cap",
        str(company_cap),
    ]
    if company:
        poll.extend(["--company", company])
    embeddings = [
        python,
        str(ROOT / "job_embedding_worker.py"),
        "--batch-size",
        "32",
        "--max-jobs",
        str(max_embeddings),
    ]
    worker = [
        python,
        str(ROOT / "enrichment_worker.py"),
        "--batch-size",
        "10",
        "--max-messages",
        str(max_messages),
    ]
    return poll, embeddings, worker


def _run(command: list[str], *, env: dict[str, str]) -> dict:
    started = datetime.now().astimezone()
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    ended = datetime.now().astimezone()
    return {
        "command": command,
        "returncode": completed.returncode,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": round((ended - started).total_seconds(), 3),
    }


def _model_ids() -> set[str] | None:
    headers = {"Authorization": f"Bearer {INFERENCE_API_KEY}"}
    try:
        response = requests.get(
            f"{INFERENCE_BASE_URL.rstrip('/')}/models",
            headers=headers,
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    return {
        str(item.get("id"))
        for item in (payload.get("data") or [])
        if isinstance(item, dict) and item.get("id")
    }


def _embedding_model_ids() -> set[str] | None:
    headers = {"Authorization": f"Bearer {JOB_EMBEDDING_API_KEY}"}
    try:
        response = requests.get(
            f"{JOB_EMBEDDING_BASE_URL.rstrip('/')}/models",
            headers=headers,
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    return {
        str(item.get("id"))
        for item in (payload.get("data") or [])
        if isinstance(item, dict) and item.get("id")
    }


def _wait_for_model(timeout_seconds: int) -> set[str]:
    deadline = time.monotonic() + timeout_seconds
    last_ids: set[str] = set()
    while time.monotonic() < deadline:
        ids = _model_ids()
        if ids is not None:
            last_ids = ids
            if INFERENCE_MODEL in ids:
                return ids
        time.sleep(2)
    raise RuntimeError(
        f"LM Studio model {INFERENCE_MODEL!r} was not ready within {timeout_seconds}s; "
        f"loaded={sorted(last_ids)}"
    )


def _loaded_lms_model_ids(lms: str, *, env: dict[str, str]) -> set[str] | None:
    completed = subprocess.run(
        [lms, "ps", "--json"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "[]")
    except ValueError:
        return None
    if not isinstance(payload, list):
        return None
    return {
        str(item.get("identifier") or item.get("modelKey"))
        for item in payload
        if isinstance(item, dict) and (item.get("identifier") or item.get("modelKey"))
    }


def _wait_for_loaded_lms_model(
    lms: str,
    *,
    env: dict[str, str],
    timeout_seconds: int,
) -> set[str]:
    deadline = time.monotonic() + timeout_seconds
    last_ids: set[str] = set()
    while time.monotonic() < deadline:
        ids = _loaded_lms_model_ids(lms, env=env)
        if ids is not None:
            last_ids = ids
            if INFERENCE_MODEL in ids:
                return ids
        time.sleep(2)
    raise RuntimeError(
        f"LM Studio model {INFERENCE_MODEL!r} was not loaded within {timeout_seconds}s; "
        f"loaded={sorted(last_ids)}"
    )


def _lms_binary() -> str:
    found = shutil.which("lms")
    if found:
        return found
    fallback = Path.home() / ".lmstudio" / "bin" / "lms"
    if fallback.is_file():
        return str(fallback)
    raise RuntimeError("LM Studio CLI `lms` is not installed or not on PATH")


def _checked(command: list[str], *, env: dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit {completed.returncode}: {' '.join(command)}")


def ensure_inference_ready(
    *,
    env: dict[str, str],
    model_ttl_seconds: int,
    timeout_seconds: int,
) -> dict:
    """Start local LM Studio when selected; remote providers need no bootstrap."""
    if INFERENCE_PROVIDER != "local":
        return {
            "provider": INFERENCE_PROVIDER,
            "model": INFERENCE_MODEL,
            "lm_studio_started": False,
        }

    lms = _lms_binary()
    ids = _model_ids()
    loaded_ids = _loaded_lms_model_ids(lms, env=env)
    server_started = False
    model_loaded = False

    if ids is None:
        daemon = subprocess.run([lms, "daemon", "status"], cwd=ROOT, env=env, check=False)
        if daemon.returncode != 0:
            _checked([lms, "daemon", "up"], env=env)

        parsed = urlparse(INFERENCE_BASE_URL)
        port = parsed.port or 1234
        server = subprocess.run([lms, "server", "status"], cwd=ROOT, env=env, check=False)
        if server.returncode != 0:
            _checked([lms, "server", "start", "--port", str(port)], env=env)
            server_started = True

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and ids is None:
            time.sleep(2)
            ids = _model_ids()
        if ids is None:
            raise RuntimeError("LM Studio server did not expose /v1/models")

    if loaded_ids is None:
        loaded_ids = set()
    if INFERENCE_MODEL not in loaded_ids:
        _checked(
            [
                lms,
                "load",
                INFERENCE_MODEL,
                "--identifier",
                INFERENCE_MODEL,
                "--ttl",
                str(model_ttl_seconds),
                "--parallel",
                "2",
                "--yes",
            ],
            env=env,
        )
        model_loaded = True
        loaded_ids = _wait_for_loaded_lms_model(
            lms,
            env=env,
            timeout_seconds=timeout_seconds,
        )

    return {
        "provider": INFERENCE_PROVIDER,
        "model": INFERENCE_MODEL,
        "lm_studio_started": server_started,
        "model_loaded": model_loaded,
        "loaded_models": sorted(loaded_ids),
    }


def ensure_job_embedding_ready(
    *,
    env: dict[str, str],
    model_ttl_seconds: int,
    timeout_seconds: int,
) -> dict:
    """Start LM Studio and load the fixed local job-embedding model."""
    lms = _lms_binary()
    ids = _embedding_model_ids()
    loaded_ids = _loaded_lms_model_ids(lms, env=env)
    server_started = False
    model_loaded = False

    if ids is None:
        daemon = subprocess.run([lms, "daemon", "status"], cwd=ROOT, env=env, check=False)
        if daemon.returncode != 0:
            _checked([lms, "daemon", "up"], env=env)

        parsed = urlparse(JOB_EMBEDDING_BASE_URL)
        port = parsed.port or 1234
        server = subprocess.run([lms, "server", "status"], cwd=ROOT, env=env, check=False)
        if server.returncode != 0:
            _checked([lms, "server", "start", "--port", str(port)], env=env)
            server_started = True

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and ids is None:
            time.sleep(2)
            ids = _embedding_model_ids()
        if ids is None:
            raise RuntimeError("LM Studio server did not expose the embeddings endpoint")

    if loaded_ids is None:
        loaded_ids = set()
    if JOB_EMBEDDING_MODEL not in loaded_ids:
        _checked(
            [
                lms,
                "load",
                JOB_EMBEDDING_MODEL,
                "--identifier",
                JOB_EMBEDDING_MODEL,
                "--ttl",
                str(model_ttl_seconds),
                "--yes",
            ],
            env=env,
        )
        model_loaded = True
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            loaded_ids = _loaded_lms_model_ids(lms, env=env) or set()
            if JOB_EMBEDDING_MODEL in loaded_ids:
                break
            time.sleep(2)
        else:
            raise RuntimeError(
                f"LM Studio embedding model {JOB_EMBEDDING_MODEL!r} was not loaded "
                f"within {timeout_seconds}s"
            )

    return {
        "provider": "local",
        "model": JOB_EMBEDDING_MODEL,
        "lm_studio_started": server_started,
        "model_loaded": model_loaded,
        "loaded_models": sorted(loaded_ids),
    }


def unload_embedding_model(*, env: dict[str, str]) -> dict:
    """Free the embedding model's slot before the generative model is loaded.

    Best-effort by design: if the unload fails the cycle should still continue
    and let `ensure_inference_ready` try, because a failed unload is a worse
    reason to abandon a completed scrape than a tight memory fit is.
    """
    try:
        lms = _lms_binary()
    except RuntimeError as exc:
        return {"unloaded": False, "reason": str(exc)}

    completed = subprocess.run(
        [lms, "unload", JOB_EMBEDDING_MODEL],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "model": JOB_EMBEDDING_MODEL,
        "unloaded": completed.returncode == 0,
        "returncode": completed.returncode,
    }


def _write_report(report: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"daily_cycle_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll, publish, embed jobs, start inference, and drain enrichment"
    )
    parser.add_argument("--scope", choices=["india", "global"], default="india")
    parser.add_argument("--company-cap", type=int, default=0,
                        help="Max jobs per company (default: 0 = unlimited).")
    parser.add_argument("--company", help="Run one company only")
    parser.add_argument("--max-messages", type=int, default=100000)
    parser.add_argument("--max-embeddings", type=int, default=100000)
    parser.add_argument("--model-ttl-seconds", type=int, default=3600)
    parser.add_argument("--inference-timeout-seconds", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.company_cap < 0:
        parser.error("--company-cap cannot be negative")
    if min(
        args.max_messages,
        args.max_embeddings,
        args.model_ttl_seconds,
    ) < 1:
        parser.error("max messages, max embeddings, and model TTL must be positive")

    poll, embeddings, worker = build_commands(
        python=sys.executable,
        scope=args.scope,
        company_cap=args.company_cap,
        company=args.company,
        max_messages=args.max_messages,
        max_embeddings=args.max_embeddings,
    )
    if args.dry_run:
        print(json.dumps({
            "poll": poll,
            "embeddings": embeddings,
            "job_embedding_model": JOB_EMBEDDING_MODEL,
            "inference_provider": INFERENCE_PROVIDER,
            "inference_model": INFERENCE_MODEL,
            "worker": worker,
        }, indent=2))
        return

    env = dict(os.environ)
    env["ENRICH_FORCE_LLM"] = "1"
    report = {
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(),
        "steps": {},
    }

    report["steps"]["poll_publish"] = _run(poll, env=env)
    if report["steps"]["poll_publish"]["returncode"] != 0:
        report["status"] = "failed"
        report["failed_step"] = "poll_publish"
        path = _write_report(report)
        raise SystemExit(f"Daily cycle failed during polling; report: {path}")

    try:
        report["steps"]["embedding_inference"] = ensure_job_embedding_ready(
            env=env,
            model_ttl_seconds=args.model_ttl_seconds,
            timeout_seconds=args.inference_timeout_seconds,
        )
    except Exception as exc:
        report["status"] = "failed"
        report["failed_step"] = "embedding_inference"
        report["error"] = str(exc)
        path = _write_report(report)
        raise SystemExit(f"Daily cycle could not start job embeddings; report: {path}") from exc

    report["steps"]["job_embeddings"] = _run(embeddings, env=env)
    if report["steps"]["job_embeddings"]["returncode"] != 0:
        report["status"] = "failed"
        report["failed_step"] = "job_embeddings"
        path = _write_report(report)
        raise SystemExit(f"Daily cycle failed during job embeddings; report: {path}")

    # Hand the model slot over explicitly. Loading the generative model while the
    # embedding model is still resident makes LM Studio evict one to fit the
    # other, and the evicted side then fails as an unrelated-looking network
    # error rather than anything naming the cause.
    report["steps"]["embedding_unload"] = unload_embedding_model(env=env)

    try:
        report["steps"]["inference"] = ensure_inference_ready(
            env=env,
            model_ttl_seconds=args.model_ttl_seconds,
            timeout_seconds=args.inference_timeout_seconds,
        )
    except Exception as exc:
        report["status"] = "failed"
        report["failed_step"] = "inference"
        report["error"] = str(exc)
        path = _write_report(report)
        raise SystemExit(f"Daily cycle could not start inference; report: {path}") from exc

    report["steps"]["enrichment"] = _run(worker, env=env)
    if report["steps"]["enrichment"]["returncode"] != 0:
        report["status"] = "failed"
        report["failed_step"] = "enrichment"
        path = _write_report(report)
        raise SystemExit(f"Daily cycle failed during enrichment; report: {path}")

    report["status"] = "complete"
    report["finished_at"] = datetime.now().astimezone().isoformat()
    path = _write_report(report)
    print(f"Daily poll + job embeddings + enrichment cycle complete; report: {path}")


if __name__ == "__main__":
    main()
