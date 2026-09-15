"""The declared environment surface must fail early, and never leak a value."""
import pytest

import environment
from environment import (
    CAPABILITIES,
    KEYS,
    EnvironmentError_,
    missing,
    report,
    require,
)


def test_every_key_belongs_to_a_declared_capability():
    for key in KEYS:
        assert key.capability in CAPABILITIES


def test_missing_reports_only_required_keys():
    env = {}
    absent = {key.name for key in missing("stage_a", env=env)}
    assert absent == {"MYRO_BACKEND_URL", "SCRAPE_WEBHOOK_TOKEN"}

    # analytics_refresh is optional: absence must not be reported as missing.
    assert missing("analytics_refresh", env=env) == []


def test_blank_and_whitespace_count_as_absent():
    env = {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": "   "}
    assert {key.name for key in missing("supabase", env=env)} == {
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
    }


def test_require_passes_when_configured():
    env = {"MYRO_BACKEND_URL": "https://api.example.test", "SCRAPE_WEBHOOK_TOKEN": "s"}
    require("stage_a", env=env)  # must not raise


def test_require_names_the_file_and_every_missing_key():
    with pytest.raises(EnvironmentError_) as excinfo:
        require("supabase", "stage_a", env={})
    message = str(excinfo.value)
    assert str(environment.ENV_FILE) in message
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "MYRO_BACKEND_URL",
        "SCRAPE_WEBHOOK_TOKEN",
    ):
        assert name in message


def test_unknown_capability_is_a_programming_error():
    with pytest.raises(KeyError):
        missing("not_a_capability", env={})


def test_report_never_prints_a_secret_value():
    secret = "super-secret-token-value"
    env = {name: secret for name in (key.name for key in KEYS)}
    rendered = report(env=env)
    assert secret not in rendered
    assert "blocked capabilities: none" in rendered


def test_report_lists_blocked_capabilities():
    rendered = report(env={})
    assert "stage_a" in rendered.split("blocked capabilities:")[1]


def test_load_environment_returns_none_when_file_absent(tmp_path):
    assert environment.load_environment(tmp_path / "nope.env") is None


def test_load_environment_reads_the_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("TEST_ENVIRONMENT_SEAM_KEY=loaded\n", encoding="utf-8")
    monkeypatch.delenv("TEST_ENVIRONMENT_SEAM_KEY", raising=False)
    assert environment.load_environment(path) == path
    import os

    assert os.environ["TEST_ENVIRONMENT_SEAM_KEY"] == "loaded"
