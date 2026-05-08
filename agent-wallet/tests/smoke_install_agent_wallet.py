"""Smoke test for the one-command agent-wallet installer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    temp_root = Path("/tmp/openclaw-install-agent-wallet-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    config_path = temp_root / "openclaw.json"
    env_path = temp_root / ".env"
    runtime_root = temp_root / "agent-wallet-runtime" / "current"
    runtime_env = runtime_root / "agent-wallet" / ".env"
    runtime_env.parent.mkdir(parents=True, exist_ok=True)
    runtime_env.write_text(
        "PROVIDER_GATEWAY_URL=https://preserved.example\n"
        "AGENT_WALLET_BOOT_KEY_FILE=/tmp/preserved-boot-key\n",
        encoding="utf-8",
    )
    boot_key_file = temp_root / "agent-wallet-runtime" / "boot-key"
    boot_key_file.parent.mkdir(parents=True, exist_ok=True)
    boot_key_file.write_text("test-boot-key-for-universal-installer\n", encoding="utf-8")
    stale_server = runtime_root / "wdk-evm-wallet" / "src" / "server.js"
    stale_server.parent.mkdir(parents=True, exist_ok=True)
    stale_server.write_text("// stale runtime without lido routes\n", encoding="utf-8")

    script = Path(__file__).resolve().parents[1] / "scripts" / "install_agent_wallet.py"
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-universal-installer"
    env["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-universal-installer"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval-secret-for-universal-installer"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(config_path),
            "--env-path",
            str(env_path),
            "--backend",
            "none",
            "--skip-python-setup",
            "--skip-node-setup",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["env_created"] is True
    assert payload["boot_key_file_env_updated"] is True
    assert payload["config_created"] is True
    assert payload["configured"] is False
    assert payload["pending_env"] == []
    assert payload["node_runtime"]["skipped"] is True
    assert payload["runtime_sync"]["enabled"] is True
    assert payload["runtime_sync"]["skipped"] is False
    assert Path(payload["runtime_root"]).resolve() == runtime_root.resolve()
    assert Path(payload["env_path"]).exists()
    assert Path(payload["config_path"]).exists()
    assert (
        "AGENT_WALLET_BOOT_KEY_FILE="
        + str(boot_key_file)
        in Path(payload["env_path"]).read_text(encoding="utf-8")
    )
    synced_server = runtime_root / "wdk-evm-wallet" / "src" / "server.js"
    assert synced_server.exists()
    assert synced_server.read_text(encoding="utf-8") == (
        repo_root / "wdk-evm-wallet" / "src" / "server.js"
    ).read_text(encoding="utf-8")
    assert "/v1/evm/lido/overview/get" in synced_server.read_text(encoding="utf-8")
    assert runtime_env.read_text(encoding="utf-8") == (
        "PROVIDER_GATEWAY_URL=https://preserved.example\n"
        "AGENT_WALLET_BOOT_KEY_FILE=/tmp/preserved-boot-key\n"
    )

    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["plugins"]["entries"] == {}

    dry_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(temp_root / "second-openclaw.json"),
            "--env-path",
            str(temp_root / "second.env"),
            "--skip-python-setup",
            "--skip-node-setup",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={k: v for k, v in env.items() if not k.startswith("AGENT_WALLET_")},
    )
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["configured"] is False
    assert dry_payload["pending_env"] == [
        "AGENT_WALLET_BOOT_KEY",
        "AGENT_WALLET_MASTER_KEY",
        "AGENT_WALLET_APPROVAL_SECRET",
    ]

    fresh_root = temp_root / "fresh-home"
    fresh_root.mkdir(parents=True, exist_ok=True)
    fresh = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(fresh_root / "openclaw.json"),
            "--env-path",
            str(fresh_root / ".env"),
            "--skip-python-setup",
            "--skip-node-setup",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "OPENCLAW_HOME" and not key.startswith("AGENT_WALLET_")
        }
        | {"OPENCLAW_HOME": str(fresh_root)},
    )
    fresh_payload = json.loads(fresh.stdout)
    assert fresh_payload["configured"] is False
    assert fresh_payload["pending_env"] == [
        "AGENT_WALLET_BOOT_KEY",
        "AGENT_WALLET_MASTER_KEY",
        "AGENT_WALLET_APPROVAL_SECRET",
    ]

    print("smoke_install_agent_wallet: ok")


if __name__ == "__main__":
    main()
