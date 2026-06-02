"""Smoke test: doctor/status flag when the installed runtime lags the repo.

After bumping the version locally you must run `release:local` to reinstall the
runtime into every framework. doctor/status surface a `runtime_in_sync` signal
comparing the active installed runtime against the CLI's own version, so a
forgotten reinstall is visible. It is informational and never flips doctor's ok.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "bin/openclaw-agent-wallet.mjs"
TMP = Path("/tmp/openclaw-doctor-version-sync")


def _cli_version() -> str:
    res = subprocess.run(["node", str(CLI), "--version"], capture_output=True, text=True, timeout=30)
    return res.stdout.strip()


def _stage(release_version: str) -> dict:
    if TMP.exists():
        shutil.rmtree(TMP)
    home = TMP / "openclaw"
    release = home / f"agent-wallet-runtime/releases/{release_version}"
    release.mkdir(parents=True, exist_ok=True)
    current = home / "agent-wallet-runtime/current"
    current.symlink_to(release)
    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(home)
    return env


def _run(cmd: list[str], env: dict) -> dict:
    res = subprocess.run(
        ["node", str(CLI), *cmd], capture_output=True, text=True, env=env, timeout=60
    )
    return json.loads(res.stdout)


def main() -> None:
    cli_version = _cli_version()
    assert cli_version, "cli --version empty"
    try:
        # Active runtime == CLI version -> in sync.
        env = _stage(cli_version)
        doctor = _run(["doctor"], env)
        check = next(c for c in doctor["checks"] if c["name"] == "runtime_in_sync")
        assert check["ok"] is True, check
        assert check["in_sync"] is True, check
        assert check["active_version"] == cli_version, check

        status = _run(["status"], env)
        assert status["runtime_in_sync"]["in_sync"] is True, status

        # Active runtime behind the repo/CLI -> flagged with a fix, ok stays true.
        env = _stage("0.0.1-old")
        doctor = _run(["doctor"], env)
        check = next(c for c in doctor["checks"] if c["name"] == "runtime_in_sync")
        assert check["ok"] is True, check
        assert check["in_sync"] is False, check
        assert "release:local" in check["fix"], check

        print("OK smoke_doctor_version_sync")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
