"""Smoke test: CLI install prefers keystore over a stale boot-key file."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    installer = repo_root / "agent-wallet" / "scripts" / "install_agent_wallet.py"

    temp_root = Path("/tmp/openclaw-cli-install-keystore-precedence-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    config_path = temp_root / "openclaw.json"
    env_path = temp_root / ".env"
    initial_env = dict(os.environ)
    initial_env["OPENCLAW_HOME"] = str(temp_root)
    initial_env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-cli-install-keystore"
    initial_env["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-cli-install-keystore"
    initial_env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval-secret-for-cli-install-keystore"
    initial_env["AGENT_WALLET_KEYSTORE_BACKEND"] = "plaintext"

    initial = subprocess.run(
        [
            sys.executable,
            str(installer),
            "--config-path",
            str(config_path),
            "--env-path",
            str(env_path),
            "--runtime-root",
            str(temp_root / "agent-wallet-runtime" / "current"),
            "--skip-python-setup",
            "--skip-node-setup",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=initial_env,
    )
    initial_payload = json.loads(initial.stdout)
    assert initial_payload["ok"] is True
    assert initial_payload["configured"] is True

    runtime_bin = temp_root / "agent-wallet-runtime" / "current" / "agent-wallet" / ".runtime-venv" / "bin"
    runtime_bin.mkdir(parents=True, exist_ok=True)
    runtime_python = runtime_bin / "python"
    runtime_python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    runtime_python.chmod(0o755)
    runtime_wrapper = runtime_bin / "openclaw-agent-wallet-python"
    runtime_wrapper.write_text('#!/bin/sh\nexec "$(dirname "$0")/python" "$@"\n', encoding="utf-8")
    runtime_wrapper.chmod(0o755)

    keystore_path = temp_root / "keystore" / "boot_key.plaintext"
    keystore_path.parent.mkdir(parents=True, exist_ok=True)
    keystore_path.write_text(initial_env["AGENT_WALLET_BOOT_KEY"] + "\n", encoding="utf-8")

    stale_boot_key_path = temp_root / "agent-wallet-runtime" / "boot-key"
    stale_boot_key_path.parent.mkdir(parents=True, exist_ok=True)
    stale_boot_key_path.write_text("stale-wrong-boot-key\n", encoding="utf-8")

    cli_env = {
        key: value
        for key, value in initial_env.items()
        if key
        not in {
            "AGENT_WALLET_BOOT_KEY",
            "AGENT_WALLET_MASTER_KEY",
            "AGENT_WALLET_APPROVAL_SECRET",
        }
    }
    cli_env["AGENT_WALLET_VERIFY_DISABLE"] = "1"

    updated = subprocess.run(
        [
            "node",
            str(cli),
            "install",
            "--yes",
            "--config-path",
            str(config_path),
            "--env-path",
            str(env_path),
            "--skip-python-setup",
            "--skip-node-setup",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=cli_env,
    )
    updated_payload = json.loads(updated.stdout)
    assert updated_payload["ok"] is True

    status = subprocess.run(
        ["node", str(cli), "status"],
        capture_output=True,
        text=True,
        check=True,
        env=cli_env,
    )
    status_payload = json.loads(status.stdout)
    package_version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))["version"]
    assert status_payload["active_version"] == package_version

    print("smoke_cli_install_prefers_keystore_over_stale_boot_file: ok")


if __name__ == "__main__":
    main()
