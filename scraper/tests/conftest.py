"""Make the flat scraper modules importable from tests/.

The providers and top-level modules use flat imports (`from schema import ...`,
`import providers.zwayam`), which assume the scraper/ directory is on sys.path.
With the tests now in scraper/tests/, add the parent (scraper/) so those imports
resolve no matter where pytest is invoked from.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _keep_reports_out_of_real_logs(tmp_path, monkeypatch):
    # Test reports in the real logs/ look like production runs; a fixture
    # report dated 2026_08_07 was misread as a crashed poll in 2026-09.
    monkeypatch.setattr("source_matching_facts.LOG_DIR", tmp_path / "logs")
