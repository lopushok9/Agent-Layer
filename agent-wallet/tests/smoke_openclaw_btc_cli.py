"""Smoke test for the OpenClaw CLI bridge with the BTC backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from _wdk_btc_test_server import FakeWdkBtcWalletServer  # noqa: E402


def _run(config: dict, *args: str, stdin_text: str | None = None) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "agent_wallet.openclaw_cli", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        input=stdin_text,
    )
    return json.loads(completed.stdout)


def main() -> None:
    with FakeWdkBtcWalletServer(network="testnet") as server:
        os.environ["WDK_BTC_LOCAL_TOKEN"] = server.auth_token
        config = {
            "backend": "wdk_btc_local",
            "network": "testnet",
            "wdkBtcServiceUrl": server.base_url,
            "wdkBtcAccountIndex": 0,
            "signOnly": False,
        }

        created = _run(
            config,
            "btc-wallet-create",
            "--user-id",
            "btc-cli-user@example.com",
            "--label",
            "CLI BTC Wallet",
            "--password-stdin",
            "--config-json",
            json.dumps(config),
            stdin_text="cli-btc-password\n",
        )
        assert created["wallet"]["wallet_id"] == server.wallet_id

        binding = _run(
            config,
            "btc-wallet-get",
            "--user-id",
            "btc-cli-user@example.com",
            "--config-json",
            json.dumps(config),
        )
        assert binding["wallet"]["wallet_id"] == server.wallet_id

        locked = _run(
            config,
            "btc-wallet-lock",
            "--user-id",
            "btc-cli-user@example.com",
            "--config-json",
            json.dumps(config),
        )
        assert locked["wallet"]["unlocked"] is False

        unlocked = _run(
            config,
            "btc-wallet-unlock",
            "--user-id",
            "btc-cli-user@example.com",
            "--password-stdin",
            "--config-json",
            json.dumps(config),
            stdin_text="cli-btc-password\n",
        )
        assert unlocked["wallet"]["unlocked"] is True

        onboard = _run(
            config,
            "onboard",
            "--user-id",
            "btc-cli-user@example.com",
            "--config-json",
            json.dumps(config),
        )
        assert onboard["session"]["backend"] == "wdk_btc_local"
        assert onboard["session"]["chain"] == "bitcoin"
        assert onboard["session"]["network"] == "testnet"
        assert "transfer_btc" in {tool["name"] for tool in onboard["tools"]}
        assert "transfer_sol" not in {tool["name"] for tool in onboard["tools"]}

        result = _run(
            config,
            "invoke",
            "--user-id",
            "btc-cli-user@example.com",
            "--tool",
            "get_wallet_address",
            "--arguments-json",
            "{}",
            "--config-json",
            json.dumps(config),
        )
        assert result["ok"] is True
        assert result["data"]["address"].startswith("tb1")

    print("smoke_openclaw_btc_cli: ok")


if __name__ == "__main__":
    main()
