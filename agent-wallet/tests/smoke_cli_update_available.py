"""Smoke test: CLI status/doctor surface update_available from the shared cache.

The Node CLI reads the same ``update-check.json`` the Python runtime writes and
reports a newer-version availability flag to the human via ``status`` and
``doctor`` (informationally — it must not flip doctor's overall ``ok``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "bin/openclaw-agent-wallet.mjs"
TMP = Path("/tmp/openclaw-cli-update-available")


def _env(disable: bool = False) -> dict:
    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(TMP)
    env.pop("OPENCLAW_INSTALL_ROOT", None)
    if disable:
        env["AGENT_WALLET_DISABLE_UPDATE_CHECK"] = "1"
    else:
        env.pop("AGENT_WALLET_DISABLE_UPDATE_CHECK", None)
    return env


def _write_cache(latest: str) -> None:
    cache_dir = TMP / "agent-wallet-runtime"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "update-check.json").write_text(
        json.dumps({"latest_version": latest, "checked_at": 0}), encoding="utf-8"
    )


def _run(cmd: list[str], env: dict) -> dict:
    res = subprocess.run(
        ["node", str(CLI), *cmd], capture_output=True, text=True, env=env, timeout=60
    )
    # status/doctor pretty-print a single multi-line JSON object.
    return json.loads(res.stdout)


def main() -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True, exist_ok=True)
    try:
        # status reports availability when a newer version is cached.
        _write_cache("99.0.0")
        status = _run(["status"], _env())
        assert status["update_available"]["available"] is True, status
        assert status["update_available"]["latest"] == "99.0.0", status

        # doctor surfaces it as an informational check that stays ok:true.
        doctor = _run(["doctor"], _env())
        check = next(c for c in doctor["checks"] if c["name"] == "update_available")
        assert check["ok"] is True, check
        assert check["available"] is True, check
        assert check["latest"] == "99.0.0", check

        # No newer version -> not available.
        _write_cache("0.0.1")
        status = _run(["status"], _env())
        assert status["update_available"]["available"] is False, status

        # Opt-out env suppresses availability.
        _write_cache("99.0.0")
        status = _run(["status"], _env(disable=True))
        assert status["update_available"]["available"] is False, status

        print("OK smoke_cli_update_available")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
