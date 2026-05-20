"""Smoke test for the OpenClaw CLI bridge with the EVM backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
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
    with FakeWdkEvmWalletServer(network="ethereum") as server:
        temp_home = Path("/tmp/openclaw-evm-cli-smoke")
        install_test_sealed_secrets(
            temp_home,
            boot_key="cli-evm-boot-key",
            evm_wallet_password="cli-evm-password",
        )
        os.environ["OPENCLAW_HOME"] = str(temp_home)
        os.environ["WDK_EVM_LOCAL_TOKEN"] = server.auth_token
        config = {
            "backend": "wdk_evm_local",
            "network": "ethereum",
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

        from agent_wallet.evm_user_wallets import resolve_user_evm_wallet_path  # noqa: E402

        locked = _run(
            config,
            "evm-wallet-lock",
            "--user-id",
            "evm-cli-user@example.com",
            "--config-json",
            json.dumps(config),
        )
        assert locked["wallet"]["unlocked"] is False

        binding_path = resolve_user_evm_wallet_path("evm-cli-user@example.com", network="ethereum")
        stale_binding = json.loads(binding_path.read_text(encoding="utf-8"))
        stale_binding["wallet_id"] = "stale-wallet-456"
        binding_path.write_text(json.dumps(stale_binding, indent=2), encoding="utf-8")

        unlocked = _run(
            config,
            "evm-wallet-unlock",
            "--user-id",
            "evm-cli-user@example.com",
            "--password-stdin",
            "--config-json",
            json.dumps(
                {
                    **config,
                    "wdkEvmWalletId": server.wallet_id,
                }
            ),
            stdin_text="cli-evm-password\n",
        )
        assert unlocked["wallet"]["unlocked"] is True
        assert unlocked["wallet"]["wallet_id"] == server.wallet_id

        balance = _run(
            config,
            "invoke",
            "--user-id",
            "evm-cli-user@example.com",
            "--tool",
            "get_wallet_balance",
            "--arguments-json",
            "{}",
            "--config-json",
            json.dumps(config),
        )
        assert balance["ok"] is True
        assert balance["data"]["balance_native"] == "1.23"

        swap_quote = _run(
            config,
            "invoke",
            "--user-id",
            "evm-cli-user@example.com",
            "--tool",
            "get_evm_swap_quote",
            "--arguments-json",
            json.dumps(
                {
                    "token_in": "0x2222222222222222222222222222222222222222",
                    "token_out": "0x3333333333333333333333333333333333333333",
                    "amount_in_raw": "1000000",
                }
            ),
            "--config-json",
            json.dumps(config),
        )
        assert swap_quote["ok"] is True
        assert swap_quote["data"]["allowance"]["approval_required"] is True

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
        assert onboard["session"]["network"] == "ethereum"
        assert "get_evm_token_metadata" in {tool["name"] for tool in onboard["tools"]}
        assert "get_evm_swap_quote" in {tool["name"] for tool in onboard["tools"]}
        assert "swap_evm_tokens" in {tool["name"] for tool in onboard["tools"]}
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

        auto_balance = _run(
            config,
            "invoke",
            "--user-id",
            "evm-cli-autoprovision@example.com",
            "--tool",
            "get_wallet_balance",
            "--arguments-json",
            "{}",
            "--config-json",
            json.dumps(config),
        )
        assert auto_balance["ok"] is True
        assert auto_balance["data"]["balance_native"] == "1.23"

    print("smoke_openclaw_evm_cli: ok")


if __name__ == "__main__":
    main()
