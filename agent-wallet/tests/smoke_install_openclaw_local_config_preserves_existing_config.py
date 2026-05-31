"""Smoke test that install_openclaw_local_config preserves existing plugin fields."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    temp_root = Path("/tmp/openclaw-install-config-preserve-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    runtime_root = temp_root / "agent-wallet-runtime" / "current"
    runtime_extension = runtime_root / ".openclaw" / "extensions" / "agent-wallet"
    runtime_package = runtime_root / "agent-wallet"
    runtime_venv_bin = runtime_package / ".runtime-venv" / "bin"
    runtime_extension.mkdir(parents=True, exist_ok=True)
    runtime_package.mkdir(parents=True, exist_ok=True)
    runtime_venv_bin.mkdir(parents=True, exist_ok=True)

    (runtime_extension / "openclaw.plugin.json").write_text('{"id":"agent-wallet"}\n', encoding="utf-8")
    wrapper = runtime_venv_bin / "openclaw-agent-wallet-python"
    wrapper.write_text('#!/bin/sh\nexec "$(dirname "$0")/python" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)

    config_path = temp_root / "openclaw.json"
    config_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "allow": ["agent-wallet"],
                    "load": {
                        "paths": [
                            str((temp_root / "agent-wallet-runtime" / "releases" / "0.1.22" / ".openclaw" / "extensions" / "agent-wallet").resolve()),
                            str((temp_root / "plugins" / "other-plugin").resolve()),
                        ]
                    },
                    "entries": {
                        "agent-wallet": {
                            "enabled": True,
                            "config": {
                                "userId": "existing-user",
                                "providerGatewayUrl": "https://example.gateway",
                                "keypairPath": "/tmp/existing-wallet.json",
                                "refuseMainnetWalletRecreation": True,
                            },
                        },
                        "pay-bridge": {
                            "enabled": True,
                            "config": {
                                "payBinary": "/tmp/pay",
                                "requireHttps": False,
                            },
                        },
                    }
                },
                "tools": {"alsoAllow": ["get_wallet_balance", "pay_status", "pay_api_request"]},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-preserve-smoke"
    env["AGENT_WALLET_MASTER_KEY"] = "preserve-smoke-master-key"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "preserve-smoke-approval-secret"

    script = Path(__file__).resolve().parents[1] / "scripts" / "install_openclaw_local_config.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(config_path),
            "--backend",
            "solana_local",
            "--network",
            "mainnet",
            "--no-encrypt-user-wallets",
            "--no-migrate-plaintext-user-wallets",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    payload = json.loads(completed.stdout)
    assert payload["ok"] is True

    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    plugin_config = config_data["plugins"]["entries"]["agent-wallet"]["config"]
    assert plugin_config["providerGatewayUrl"] == "https://example.gateway"
    assert plugin_config["keypairPath"] == "/tmp/existing-wallet.json"
    assert plugin_config["refuseMainnetWalletRecreation"] is True
    assert plugin_config["userId"] == "existing-user"
    assert plugin_config["backend"] == "solana_local"
    assert plugin_config["network"] == "mainnet"
    assert "agent-wallet" in config_data["plugins"]["allow"]
    assert "pay-bridge" not in config_data["plugins"]["allow"]
    assert "pay-bridge" not in config_data["plugins"]["entries"]
    assert config_data["plugins"]["load"]["paths"] == [
        str((temp_root / "plugins" / "other-plugin").resolve()),
        str(runtime_extension.resolve()),
    ]

    also_allow = config_data["tools"]["alsoAllow"]
    assert "get_evm_network" in also_allow
    assert "set_evm_network" in also_allow
    assert "get_evm_swap_quote" in also_allow
    assert "swap_evm_tokens" in also_allow
    assert "transfer_evm_native" in also_allow
    assert "transfer_evm_token" in also_allow
    assert "kamino_lend_deposit" in also_allow
    assert "kamino_lend_repay" in also_allow
    assert "pay_status" not in also_allow
    assert "pay_api_request" not in also_allow
    assert "x402_search_services" in also_allow
    assert "x402_pay_request" in also_allow

    print("smoke_install_openclaw_local_config_preserves_existing_config: ok")


if __name__ == "__main__":
    main()
