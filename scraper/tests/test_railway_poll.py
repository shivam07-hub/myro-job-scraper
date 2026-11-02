"""The Railway entry point keeps a run's output on the volume.

Railway holds container logs for about a week and csv_importer logs only to
stdout, so the cause of the 2026-10-21 publish crash was gone by the time anyone
looked. The copy to the volume must not change the poll's exit code: a failed
publish has to stay a failed Railway run.
"""
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "railway_poll.sh"


def _run(tmp_path: Path, *, poll_exit: int) -> tuple[subprocess.CompletedProcess, Path]:
    data = tmp_path / "data"
    data.mkdir()
    workdir = tmp_path / "scraper"
    workdir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    stub = bin_dir / "python"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "environment.py" ]; then exit 0; fi\n'
        'echo "stdout from $1"\n'
        'echo "Traceback from $1" >&2\n'
        f"exit {poll_exit}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    script = tmp_path / "railway_poll.sh"
    script.write_text(
        SCRIPT.read_text(encoding="utf-8")
        .replace("/app/scraper", str(workdir))
        .replace("/data", str(data)),
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        check=False,
    )
    return completed, data / "logs"


@pytest.mark.parametrize("poll_exit", [0, 1, 137])
def test_poll_exit_code_survives_the_copy_to_the_volume(tmp_path, poll_exit) -> None:
    completed, _logs = _run(tmp_path, poll_exit=poll_exit)

    assert completed.returncode == poll_exit


def test_run_output_reaches_both_railway_and_the_volume(tmp_path) -> None:
    completed, logs = _run(tmp_path, poll_exit=1)

    [log] = logs.glob("railway_poll_*.log")
    saved = log.read_text(encoding="utf-8")
    assert "stdout from daily_poll.py" in saved
    assert "Traceback from daily_poll.py" in saved
    assert "stdout from daily_poll.py" in completed.stdout
    assert "Traceback from daily_poll.py" in completed.stdout


def test_an_unwritable_log_does_not_fail_the_poll(tmp_path) -> None:
    (tmp_path / "data").mkdir()
    script_text = SCRIPT.read_text(encoding="utf-8")
    assert 'log="/data/logs/railway_poll_' in script_text
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "python"
    stub.write_text("#!/bin/sh\necho ok\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    script = tmp_path / "railway_poll.sh"
    script.write_text(
        script_text
        .replace('log="/data/logs/railway_poll_', f'log="{tmp_path}/no/such/dir/railway_poll_')
        .replace("/app/scraper", str(tmp_path))
        .replace("/data", str(tmp_path / "data")),
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        check=False,
    )

    assert completed.returncode == 0
    assert "ok" in completed.stdout
