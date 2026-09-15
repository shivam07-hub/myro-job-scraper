from __future__ import annotations

import requests

import enrichment_worker


class _Resp:
    def __init__(self, payload=None, *, ok: bool = True) -> None:
        self._payload = payload or {}
        self._ok = ok

    def raise_for_status(self) -> None:
        if not self._ok:
            raise requests.HTTPError("boom")

    def json(self):
        return self._payload


def _listing_with_model():
    return _Resp({"data": [{"id": enrichment_worker.INFERENCE_MODEL}]})


def test_listed_but_unloaded_model_is_not_ready(monkeypatch) -> None:
    """`/v1/models` lists DOWNLOADED models, not loaded ones.

    Trusting the listing alone let a whole drain start with nothing loaded and
    grind through the queue retrying /chat/completions after the model's TTL
    expired mid-run (observed 2026-08-08). The probe is what catches it.
    """
    monkeypatch.setattr(enrichment_worker, "INFERENCE_PROVIDER", "local")
    monkeypatch.setattr(enrichment_worker.requests, "get", lambda *a, **k: _listing_with_model())

    def dead_probe(*args, **kwargs):
        raise requests.ReadTimeout("model is not loaded")

    monkeypatch.setattr(enrichment_worker.requests, "post", dead_probe)

    assert enrichment_worker.local_inference_ready() is False


def test_loaded_model_answering_the_probe_is_ready(monkeypatch) -> None:
    monkeypatch.setattr(enrichment_worker, "INFERENCE_PROVIDER", "local")
    monkeypatch.setattr(enrichment_worker.requests, "get", lambda *a, **k: _listing_with_model())
    monkeypatch.setattr(enrichment_worker.requests, "post", lambda *a, **k: _Resp({"choices": []}))

    assert enrichment_worker.local_inference_ready() is True


def test_model_absent_from_listing_skips_the_probe(monkeypatch) -> None:
    monkeypatch.setattr(enrichment_worker, "INFERENCE_PROVIDER", "local")
    monkeypatch.setattr(enrichment_worker.requests, "get", lambda *a, **k: _Resp({"data": []}))

    def unexpected(*args, **kwargs):
        raise AssertionError("probe must not run when the model is not even listed")

    monkeypatch.setattr(enrichment_worker.requests, "post", unexpected)

    assert enrichment_worker.local_inference_ready() is False


def test_remote_provider_needs_no_local_probe(monkeypatch) -> None:
    monkeypatch.setattr(enrichment_worker, "INFERENCE_PROVIDER", "remote")

    def unexpected(*args, **kwargs):
        raise AssertionError("remote provider must not be probed locally")

    monkeypatch.setattr(enrichment_worker.requests, "get", unexpected)
    monkeypatch.setattr(enrichment_worker.requests, "post", unexpected)

    assert enrichment_worker.local_inference_ready() is True
