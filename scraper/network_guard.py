"""Pause a scrape while this machine has no network, instead of racing through it.

The daily poll runs on a laptop. On 2026-09-30 the Mac slept mid-run; on each
brief dark wake DNS was down, and the scraper recorded 20 companies (Oracle
HCM, SAP Jobs2Web, ...) as empty within milliseconds. Those were network
failures, not source observations.

``main.run`` calls ``wait_for_network`` before each company, and again after a
failed company to decide whether that failure deserves one retry.
"""
from __future__ import annotations

import logging
import socket
import time
from typing import Callable

# Resolved by name on purpose: the observed failure was DNS, and macOS flushes
# its resolver cache on a network change, so a cached answer can't mask it.
CANARY_HOSTS = ("www.google.com", "www.cloudflare.com", "api.github.com")
POLL_SECONDS = 30
# Measured on time.monotonic(), which does not advance while the Mac sleeps:
# a closed lid pauses the run rather than spending this budget.
MAX_WAIT_SECONDS = 2 * 60 * 60

_sleep = time.sleep
_monotonic = time.monotonic


def network_available(
    hosts: tuple[str, ...] = CANARY_HOSTS,
    *,
    resolver: Callable[..., object] = socket.getaddrinfo,
) -> bool:
    for host in hosts:
        try:
            resolver(host, 443)
            return True
        except OSError:
            continue
    return False


def wait_for_network(
    log: logging.Logger,
    *,
    check: Callable[[], bool] | None = None,
    sleep: Callable[[float], object] | None = None,
    monotonic: Callable[[], float] | None = None,
    poll_seconds: float | None = None,
    max_wait_seconds: float | None = None,
) -> bool:
    """Return True once the network is up; False if it stays down too long."""
    check = check or network_available
    sleep = sleep or _sleep
    monotonic = monotonic or _monotonic
    poll_seconds = POLL_SECONDS if poll_seconds is None else poll_seconds
    max_wait_seconds = MAX_WAIT_SECONDS if max_wait_seconds is None else max_wait_seconds
    if check():
        return True
    log.warning("  Network unavailable (DNS) — pausing the run until it returns")
    started = monotonic()
    while monotonic() - started < max_wait_seconds:
        sleep(poll_seconds)
        if check():
            log.info("  Network back after %.0fs awake — resuming", monotonic() - started)
            return True
    log.error("  Network still unavailable after %.0fs awake — stopping the run", max_wait_seconds)
    return False
