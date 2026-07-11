"""Smoke test: wallet update leaves unowned host integrations untouched."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path("/tmp/openclaw-update-preserves-unmanaged-integrations")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True)

    home = temp_root / "home"
    runtime_base = home / "agent-wallet-runtime"
    old_release = runtime_base / "releases" / "0.0.9"
    old_release.mkdir(parents=True)
    (runtime_base / "current").symlink_to(old_release)

    external = temp_root / "external"
    hermes_source = external / "hermes"
    codex_source = external / "codex"
    claude_source = external / "claude"
    hermes_source.mkdir(parents=True)
    (hermes_source / "plugin.yaml").write_text("name: custom_wallet\n", encoding="utf-8")
    _write_json(codex_source / ".codex-plugin" / "plugin.json", {"name": "custom-wallet"})
    _write_json(claude_source / ".claude-plugin" / "plugin.json", {"name": "custom-wallet"})

    hermes_home = temp_root / "hermes"
    hermes_target = hermes_home / "plugins" / "agent_wallet"
    hermes_target.parent.mkdir(parents=True)
    hermes_target.symlink_to(hermes_source)

    codex_root = temp_root / "codex-plugins"
    codex_target = codex_root / "agent-wallet"
    codex_target.parent.mkdir(parents=True)
    codex_target.symlink_to(codex_source)
    codex_marketplace = temp_root / "marketplace.json"
    _write_json(codex_marketplace, {"name": "local", "plugins": []})

    claude_marketplace = temp_root / "claude-marketplace"
    claude_target = claude_marketplace / "plugins" / "agent-wallet"
    claude_target.parent.mkdir(parents=True)
    claude_target.symlink_to(claude_source)
    _write_json(
        claude_marketplace / ".claude-plugin" / "marketplace.json",
        {"name": "another-marketplace", "plugins": []},
    )

    env = dict(os.environ)
    env.update(
        {
            "OPENCLAW_HOME": str(home),
            "HERMES_HOME": str(hermes_home),
            "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(codex_root),
            "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(codex_marketplace),
            "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(claude_marketplace),
            "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH": str(cli),
            "AGENT_WALLET_BOOT_KEY": "test-boot-key-preserve-unmanaged",
            "AGENT_WALLET_MASTER_KEY": "test-master-key-preserve-unmanaged",
            "AGENT_WALLET_APPROVAL_SECRET": "test-approval-secret-preserve-unmanaged",
            "AGENT_WALLET_VERIFY_DISABLE": "1",
        }
    )
    completed = subprocess.run(
        [
            "node",
            str(cli),
            "update",
            "--yes",
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
    payload = json.loads(completed.stdout)
    refreshed = {item["name"] for item in payload["integration_refresh"]}
    assert "hermes" not in refreshed, payload
    assert "codex" not in refreshed, payload
    assert "claude-code" not in refreshed, payload
    assert hermes_target.resolve() == hermes_source.resolve()
    assert codex_target.resolve() == codex_source.resolve()
    assert claude_target.resolve() == claude_source.resolve()

    print("smoke_update_preserves_unmanaged_integrations: ok")


if __name__ == "__main__":
    main()
