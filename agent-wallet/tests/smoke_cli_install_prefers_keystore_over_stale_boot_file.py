"""Smoke test: CLI install prefers keystore over a stale boot-key file."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    installer = repo_root / "agent-wallet" / "scripts" / "install_agent_wallet.py"

    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-cli-install-keystore-precedence-"))
    atexit.register(shutil.rmtree, temp_root, ignore_errors=True)

    config_path = temp_root / "openclaw.json"
    env_path = temp_root / ".env"
    initial_env = dict(os.environ)
    initial_env["OPENCLAW_HOME"] = str(temp_root)
    initial_env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-cli-install-keystore"
    initial_env["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-cli-install-keystore"
    initial_env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval-secret-for-cli-install-keystore"
    initial_env["AGENT_WALLET_KEYSTORE_BACKEND"] = "plaintext"
    initial_env["HERMES_HOME"] = str(temp_root / "hermes-home")
    initial_env["CODEX_HOME"] = str(temp_root / "codex-home")
    initial_env["AGENT_WALLET_CODEX_PLUGIN_ROOT"] = str(temp_root / "codex-plugins")
    initial_env["AGENT_WALLET_CODEX_MARKETPLACE_PATH"] = str(
        temp_root / "codex-marketplace.json"
    )
    initial_env["AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR"] = str(
        temp_root / "claude-marketplace"
    )
    initial_env["AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT"] = str(temp_root / "claude-cache")

    claude_mcp = repo_root / "claude-code" / "plugins" / "agent-wallet" / ".mcp.json"
    claude_mcp_before = claude_mcp.read_bytes()

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
    assert claude_mcp.read_bytes() == claude_mcp_before

    print("smoke_cli_install_prefers_keystore_over_stale_boot_file: ok")


if __name__ == "__main__":
    main()
