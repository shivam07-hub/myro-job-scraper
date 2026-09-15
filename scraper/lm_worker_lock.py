"""One local-inference worker at a time.

LM Studio holds a small number of models resident. When the embedding worker and
the enrichment worker run at once, loading one model evicts the other's, and both
sides then fail in ways that look like unrelated network faults — that is exactly
what happened on 2026-08-08, where the two workers running together produced
`nodename nor servname provided` and `Server disconnected` rather than anything
naming the real cause.

The workers are already safe to interrupt and re-run: their claims are token- and
attempt-guarded, so refusing to start is always cheaper than colliding.

This mirrors the flock daily_poll.py already uses to refuse overlapping polls.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
from typing import Iterator

LOCK_DIR = Path(__file__).resolve().parent.parent / "logs"
LOCK_NAME = "lm_inference_worker.lock"

# Exit code for "another local-inference worker holds the lock". Distinct from
# argparse's 2 and from a genuine drain failure, so a supervising loop can tell
# "wait your turn" apart from "this run is broken".
BUSY_EXIT_CODE = 3


class WorkerBusy(RuntimeError):
    """Another local-inference worker already holds the lock."""


@contextlib.contextmanager
def local_inference_lock(worker_name: str) -> Iterator[None]:
    """Hold the exclusive local-inference lock for the duration of the block.

    Raises WorkerBusy if another worker holds it. Never blocks: a queued second
    worker would sit idle holding a model slot hostage, which is the problem this
    exists to prevent.
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_DIR / LOCK_NAME
    handle = lock_path.open("w", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkerBusy(
                f"another local-inference worker holds {lock_path}; "
                f"{worker_name} is refusing to start so it cannot evict the "
                "other worker's model"
            ) from exc
        handle.write(f"{worker_name} pid={os.getpid()}\n")
        handle.flush()
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
