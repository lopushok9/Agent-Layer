"""Smoke test for the OpenClaw CLI bridge with the EVM backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402


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
    with FakeWdkEvmWalletServer(network="sepolia") as server:
        os.environ["WDK_EVM_LOCAL_TOKEN"] = server.auth_token
        config = {
            "backend": "wdk_evm_local",
            "network": "sepolia",
            "wdkEvmServiceUrl": server.base_url,
            "wdkEvmAccountIndex": 0,
            "signOnly": False,
        }

        created = _run(
            config,
            "evm-wallet-create",
            "--user-id",
            "evm-cli-user@example.com",
            "--label",
            "CLI EVM Wallet",
            "--password-stdin",
            "--config-json",
            json.dumps(config),
            stdin_text="cli-evm-password\n",
        )
        assert created["wallet"]["wallet_id"] == server.wallet_id

        binding = _run(
            config,
            "evm-wallet-get",
            "--user-id",
            "evm-cli-user@example.com",
            "--config-json",
            json.dumps(config),
        )
        assert binding["wallet"]["wallet_id"] == server.wallet_id

        locked = _run(
            config,
            "evm-wallet-lock",
            "--user-id",
            "evm-cli-user@example.com",
            "--config-json",
            json.dumps(config),
        )
        assert locked["wallet"]["unlocked"] is False

        unlocked = _run(
            config,
            "evm-wallet-unlock",
            "--user-id",
            "evm-cli-user@example.com",
            "--password-stdin",
            "--config-json",
            json.dumps(config),
            stdin_text="cli-evm-password\n",
        )
        assert unlocked["wallet"]["unlocked"] is True

        onboard = _run(
            config,
            "onboard",
            "--user-id",
            "evm-cli-user@example.com",
            "--config-json",
            json.dumps(config),
        )
        assert onboard["session"]["backend"] == "wdk_evm_local"
        assert onboard["session"]["chain"] == "evm"
        assert onboard["session"]["network"] == "sepolia"
        assert "get_evm_swap_quote" in {tool["name"] for tool in onboard["tools"]}
        assert "transfer_evm_native" in {tool["name"] for tool in onboard["tools"]}
        assert "transfer_sol" not in {tool["name"] for tool in onboard["tools"]}

        result = _run(
            config,
            "invoke",
            "--user-id",
            "evm-cli-user@example.com",
            "--tool",
            "get_wallet_address",
            "--arguments-json",
            "{}",
            "--config-json",
            json.dumps(config),
        )
        assert result["ok"] is True
        assert result["data"]["address"].startswith("0x")

    print("smoke_openclaw_evm_cli: ok")


if __name__ == "__main__":
    main()
