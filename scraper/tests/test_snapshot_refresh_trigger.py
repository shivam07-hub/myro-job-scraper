from __future__ import annotations

from unittest.mock import MagicMock

import csv_importer
import pytest
import requests


def test_scraper_requests_async_forced_refresh_and_accepts_202(monkeypatch) -> None:
    monkeypatch.setenv("MYRO_BACKEND_URL", "https://api.example.test")
    monkeypatch.setenv("MYRO_ANALYTICS_REFRESH_SECRET", "refresh-secret")
    response = MagicMock(status_code=202)
    post = MagicMock(return_value=response)
    monkeypatch.setattr(csv_importer.requests, "post", post)

    csv_importer._refresh_analytics_snapshot()

    post.assert_called_once_with(
        "https://api.example.test/jobs/analytics/refresh-snapshot?force=true",
        headers={"X-Myro-Refresh-Secret": "refresh-secret"},
        timeout=5,
    )


def test_scrape_landed_names_the_published_run(monkeypatch) -> None:
    monkeypatch.setenv("MYRO_BACKEND_URL", "https://api.example.test")
    monkeypatch.setenv("SCRAPE_WEBHOOK_TOKEN", "scrape-secret")
    response = MagicMock(status_code=200)
    response.json.return_value = {"skill_floor_enqueued": True}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(csv_importer.requests, "post", post)

    csv_importer._notify_scrape_landed("feed-run-123")

    post.assert_called_once_with(
        "https://api.example.test/internal/scrape/landed",
        json={"run_id": "feed-run-123"},
        headers={"X-Scrape-Token": "scrape-secret"},
        timeout=15,
    )


def test_scrape_landed_retries_transport_failure_then_requires_ack(monkeypatch) -> None:
    monkeypatch.setenv("MYRO_BACKEND_URL", "https://api.example.test")
    monkeypatch.setenv("SCRAPE_WEBHOOK_TOKEN", "scrape-secret")
    accepted = MagicMock(status_code=200)
    accepted.json.return_value = {"skill_floor_enqueued": True}
    post = MagicMock(side_effect=[requests.ConnectionError("offline"), accepted])
    sleep = MagicMock()
    monkeypatch.setattr(csv_importer.requests, "post", post)
    monkeypatch.setattr(csv_importer.time, "sleep", sleep)

    csv_importer._notify_scrape_landed("feed-run-123")

    assert post.call_count == 2
    sleep.assert_called_once_with(2)


def test_scrape_landed_fails_publish_without_durable_ack(monkeypatch) -> None:
    monkeypatch.setenv("MYRO_BACKEND_URL", "https://api.example.test")
    monkeypatch.setenv("SCRAPE_WEBHOOK_TOKEN", "scrape-secret")
    response = MagicMock(status_code=200)
    response.json.return_value = {"skill_floor_enqueued": False}
    monkeypatch.setattr(csv_importer.requests, "post", MagicMock(return_value=response))

    with pytest.raises(RuntimeError, match="did not accept Stage A"):
        csv_importer._notify_scrape_landed("feed-run-123")


def test_scrape_landed_configuration_is_required(monkeypatch) -> None:
    monkeypatch.delenv("MYRO_BACKEND_URL", raising=False)
    monkeypatch.delenv("SCRAPE_WEBHOOK_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="requires MYRO_BACKEND_URL"):
        csv_importer._notify_scrape_landed("feed-run-123")
