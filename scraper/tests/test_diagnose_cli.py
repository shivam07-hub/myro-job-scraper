from __future__ import annotations

import json
import sys

import diagnose as diagnose_module
from heal.classifier import Verdict
from heal.probe import ProbeResult


def test_find_run_summary_resolves_persisted_run_id(monkeypatch, tmp_path):
    path = tmp_path / "run_summary_20260808_082559_997076.json"
    path.write_text(json.dumps({"run_id": "20260807_232810_285813"}), encoding="utf-8")
    monkeypatch.setattr(diagnose_module, "LOGS_DIR", str(tmp_path))

    assert diagnose_module.find_run_summary("20260807_232810_285813") == str(path)


def test_json_probe_executes_probe_and_emits_both_sections(monkeypatch, capsys):
    verdict = Verdict("Micron", "pcsx", "REGRESSION", 0, 294, "no_jobs", "drop", "retry")
    probe = ProbeResult("Micron", "pcsx", True, 25, 294, "RECOVERED")
    called = []
    monkeypatch.setattr(diagnose_module, "diagnose", lambda run_id: ({"run_id": "r"}, [verdict]))
    monkeypatch.setattr(diagnose_module, "load_ledger", lambda: {})
    monkeypatch.setattr(diagnose_module, "run_probes", lambda verdicts, baseline: called.append(True) or [probe])
    monkeypatch.setattr(sys, "argv", ["diagnose.py", "--json", "--probe"])

    diagnose_module.main()

    payload = json.loads(capsys.readouterr().out)
    assert called == [True]
    assert payload["verdicts"][0]["company"] == "Micron"
    assert payload["probes"][0]["verdict"] == "RECOVERED"
