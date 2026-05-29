"""Smoke test for the OpenClaw CLI bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.bootstrap import generate_solana_wallet_material  # noqa: E402


def _run(*args: str) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT)
    for key in (
        "SOLANA_RPC_URL",
        "SOLANA_RPC_URLS",
        "SOLANA_RPC_PROVIDER_MODE",
        "SOLANA_SWAP_PROVIDER",
        "PROVIDER_GATEWAY_URL",
        "PROVIDER_GATEWAY_BEARER_TOKEN",
        "PROVIDER_GATEWAY_RPC_PROVIDER",
        "HELIUS_API_KEY",
        "ALCHEMY_API_KEY",
    ):
        env.pop(key, None)
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
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-cli-smoke",
        master_key="test-master-key-for-cli-smoke",
    )

    config = {
        "backend": "solana_local",
        "network": "mainnet",
        "rpcUrls": ["https://primary.mainnet.invalid", "https://api.mainnet-beta.solana.com"],
        "signOnly": False,
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
    assert onboard["session"]["rpc_provider_mode"] == "user_direct"
    assert onboard["session"]["rpc_provider"] == "custom"
    assert onboard["session"]["rpc_transport"] == "direct"
    assert onboard["session"]["swap_provider"] == "jupiter"
    assert onboard["session"]["swap_transport"] == "direct"
    assert "get_wallet_address" in {tool["name"] for tool in onboard["tools"]}
    assert "launch_bags_token" in {tool["name"] for tool in onboard["tools"]}

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

    explicit_material = generate_solana_wallet_material()
    explicit_path = temp_home / "external-wallet.json"
    explicit_path.write_text(explicit_material["secret_material"], encoding="utf-8")

    explicit_config = {
        **config,
        "network": "mainnet",
        "keypairPath": str(explicit_path),
    }
    seeded = _run(
        "onboard",
        "--user-id",
        "cli-keypair-user@example.com",
        "--config-json",
        json.dumps({"backend": "solana_local", "network": "mainnet"}),
    )
    assert seeded["session"]["address"] != explicit_material["address"]

    explicit_onboard = _run(
        "onboard",
        "--user-id",
        "cli-keypair-user@example.com",
        "--config-json",
        json.dumps(explicit_config),
    )
    assert explicit_onboard["session"]["address"] == explicit_material["address"]
    assert explicit_onboard["session"]["wallet_path"] == str(explicit_path)
    assert explicit_onboard["session"]["storage_format"] == "plaintext"

    explicit_result = _run(
        "invoke",
        "--user-id",
        "cli-keypair-user@example.com",
        "--tool",
        "get_wallet_address",
        "--arguments-json",
        "{}",
        "--config-json",
        json.dumps(explicit_config),
    )
    assert explicit_result["ok"] is True
    assert explicit_result["data"]["address"] == explicit_material["address"]

    print("smoke_openclaw_cli: ok")


if __name__ == "__main__":
    main()
