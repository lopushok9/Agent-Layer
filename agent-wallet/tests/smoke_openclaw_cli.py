"""Smoke test for the OpenClaw CLI bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "agent_wallet.openclaw_cli", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(completed.stdout)


def main() -> None:
    temp_home = Path("/tmp/openclaw-cli-wallet-smoke")
    os.environ["OPENCLAW_HOME"] = str(temp_home)

    config = {
        "backend": "solana_local",
        "network": "devnet",
        "rpcUrls": ["https://primary.devnet.invalid", "https://api.devnet.solana.com"],
        "signOnly": False,
        "masterKey": "test-master-key-for-cli-smoke",
        "encryptUserWallets": True,
        "migratePlaintextUserWallets": True,
    }

    onboard = _run(
        "onboard",
        "--user-id",
        "cli-user@example.com",
        "--config-json",
        json.dumps(config),
    )
    assert onboard["manifest"]["id"] == "agent-wallet"
    assert onboard["session"]["storage_format"] == "encrypted"
    assert "get_wallet_address" in {tool["name"] for tool in onboard["tools"]}

    result = _run(
        "invoke",
        "--user-id",
        "cli-user@example.com",
        "--tool",
        "get_wallet_address",
        "--arguments-json",
        "{}",
        "--config-json",
        json.dumps(config),
    )
    assert result["ok"] is True
    assert result["data"]["configured"] is True

    print("smoke_openclaw_cli: ok")


if __name__ == "__main__":
    main()
