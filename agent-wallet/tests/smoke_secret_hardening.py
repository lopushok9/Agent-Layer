"""Smoke tests for secret-handling hardening."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _run_cli_expect_fail(*args: str) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "agent_wallet.openclaw_cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    return completed.stderr


def main() -> None:
    err = _run_cli_expect_fail(
        "onboard",
        "--user-id",
        "smoke-user",
        "--config-json",
        json.dumps({"backend": "solana_local", "masterKey": "should-not-work"}),
    )
    assert "Sensitive keys are not allowed in --config-json" in err
    print("smoke_secret_hardening: ok")


if __name__ == "__main__":
    main()
