"""Smoke test that install_openclaw_local_config migrates the legacy TCP EVM URL.

Installs from before the unix-socket transport persisted http://127.0.0.1:8081
as an explicit wdkEvmServiceUrl, which kept them off the per-home socket and
left a second daemon on the shared port. Only that exact legacy default is
dropped; a custom URL or an explicit WDK_EVM_TRANSPORT=tcp opt-out is kept.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_openclaw_local_config.py"


def _run(temp_root: Path, service_url: str, extra_env: dict[str, str] | None = None) -> dict:
    if temp_root.exists():
        shutil.rmtree(temp_root)
    runtime_root = temp_root / "agent-wallet-runtime" / "current"
    runtime_extension = runtime_root / ".openclaw" / "extensions" / "agent-wallet"
    runtime_venv_bin = runtime_root / "agent-wallet" / ".runtime-venv" / "bin"
    runtime_extension.mkdir(parents=True, exist_ok=True)
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
                    "entries": {
                        "agent-wallet": {
                            "enabled": True,
                            "config": {
                                "userId": "existing-user",
                                "wdkEvmServiceUrl": service_url,
                                "wdkEvmWalletId": "wallet-1",
                            },
                        }
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env.pop("WDK_EVM_TRANSPORT", None)
    env.pop("WDK_EVM_SERVICE_URL", None)
    env["OPENCLAW_HOME"] = str(temp_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-legacy-evm-url-smoke"
    env["AGENT_WALLET_MASTER_KEY"] = "legacy-evm-url-smoke-master-key"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "legacy-evm-url-smoke-approval-secret"
    env.update(extra_env or {})

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
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
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return data["plugins"]["entries"]["agent-wallet"]["config"]


def main() -> None:
    temp_root = Path("/tmp/openclaw-install-config-legacy-evm-url-smoke")
    try:
        for legacy in ("http://127.0.0.1:8081", "http://localhost:8081/", "HTTP://127.0.0.1:8081"):
            config = _run(temp_root, legacy)
            assert "wdkEvmServiceUrl" not in config, (legacy, config)
            assert config["wdkEvmWalletId"] == "wallet-1"

        config = _run(temp_root, "http://127.0.0.1:9090")
        assert config["wdkEvmServiceUrl"] == "http://127.0.0.1:9090"

        config = _run(temp_root, "unix:///tmp/custom/daemon.sock")
        assert config["wdkEvmServiceUrl"] == "unix:///tmp/custom/daemon.sock"

        config = _run(temp_root, "http://127.0.0.1:8081", {"WDK_EVM_TRANSPORT": "tcp"})
        assert config["wdkEvmServiceUrl"] == "http://127.0.0.1:8081"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("smoke_install_openclaw_local_config_migrates_legacy_evm_url: ok")


if __name__ == "__main__":
    main()
