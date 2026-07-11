"""Smoke test: wallet update rewires stale editor installs back to current/.

Older installs could pin Codex/Hermes to releases/<version>, so a later runtime
update left those editors executing stale code. The updater must repair existing
integrations to point at agent-wallet-runtime/current instead of a concrete
release path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    package_version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))["version"]

    temp_root = Path("/tmp/openclaw-update-repairs-editor-installs")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    home = temp_root / "home"
    runtime_base = home / "agent-wallet-runtime"
    old_release = runtime_base / "releases" / "0.0.9"
    current = runtime_base / "current"
    old_release.mkdir(parents=True, exist_ok=True)
    current.parent.mkdir(parents=True, exist_ok=True)
    current.symlink_to(old_release)

    openclaw_config = home / "openclaw.json"
    _write_json(
        openclaw_config,
        {
            "plugins": {
                "load": {
                    "paths": [
                        str(old_release / ".openclaw" / "extensions" / "agent-wallet")
                    ]
                },
                "entries": {
                    "agent-wallet": {
                        "enabled": True,
                        "config": {
                            "backend": "none",
                            "packageRoot": str(old_release / "agent-wallet"),
                        },
                    }
                },
            }
        },
    )

    (old_release / "agent-wallet" / "agent_wallet").mkdir(parents=True, exist_ok=True)
    (old_release / "agent-wallet" / "agent_wallet" / "__init__.py").write_text("__version__='0.0.9'\n", encoding="utf-8")
    (old_release / "hermes" / "plugins" / "agent_wallet").mkdir(parents=True, exist_ok=True)
    (old_release / "hermes" / "plugins" / "agent_wallet" / "plugin.yaml").write_text("name: agent_wallet\n", encoding="utf-8")
    (old_release / "codex" / "plugins" / "agent-wallet" / ".codex-plugin").mkdir(parents=True, exist_ok=True)
    _write_json(
        old_release / "codex" / "plugins" / "agent-wallet" / ".codex-plugin" / "plugin.json",
        {"name": "agent-wallet", "version": "0.0.9"},
    )
    (old_release / "claude-code" / "plugins" / "agent-wallet").mkdir(parents=True, exist_ok=True)
    _write_json(
        old_release
        / "claude-code"
        / "plugins"
        / "agent-wallet"
        / ".claude-plugin"
        / "plugin.json",
        {"name": "agent-wallet", "version": "0.0.9"},
    )
    _write_json(
        old_release / "claude-code" / "plugins" / "agent-wallet" / ".mcp.json",
        {"mcpServers": {"agent-wallet": {"command": "sh", "env": {}}}},
    )

    hermes_home = temp_root / "hermes-home"
    hermes_plugin_target = hermes_home / "plugins" / "agent_wallet"
    hermes_plugin_target.parent.mkdir(parents=True, exist_ok=True)
    hermes_plugin_target.symlink_to(old_release / "hermes" / "plugins" / "agent_wallet")
    (hermes_home / ".env").write_text(
        f"AGENT_WALLET_PACKAGE_ROOT={old_release / 'agent-wallet'}\n"
        f"AGENT_WALLET_PYTHON={old_release / 'agent-wallet' / '.runtime-venv' / 'bin' / 'python'}\n",
        encoding="utf-8",
    )

    codex_plugin_root = temp_root / "codex-plugins"
    codex_plugin_target = codex_plugin_root / "agent-wallet"
    codex_plugin_target.parent.mkdir(parents=True, exist_ok=True)
    codex_plugin_target.symlink_to(old_release / "codex" / "plugins" / "agent-wallet")
    marketplace_path = temp_root / "agents" / "plugins" / "marketplace.json"
    _write_json(
        marketplace_path,
        {
            "name": "local",
            "interface": {"displayName": "Local Plugins"},
            "plugins": [
                {
                    "name": "agent-wallet",
                    "source": {"source": "local", "path": "./plugins/agent-wallet"},
                }
            ],
        },
    )

    claude_marketplace = temp_root / "claude-marketplace"
    claude_plugin_target = claude_marketplace / "plugins" / "agent-wallet"
    claude_plugin_target.parent.mkdir(parents=True, exist_ok=True)
    claude_plugin_target.symlink_to(old_release / "claude-code" / "plugins" / "agent-wallet")
    _write_json(
        claude_marketplace / ".claude-plugin" / "marketplace.json",
        {
            "name": "agentlayer-local",
            "plugins": [{"name": "agent-wallet", "source": "./plugins/agent-wallet"}],
        },
    )
    claude_cache = temp_root / "claude-cache"
    claude_cache_mcp = claude_cache / "agentlayer-local" / "agent-wallet" / "0.1.0" / ".mcp.json"
    _write_json(
        claude_cache_mcp,
        {"mcpServers": {"agent-wallet": {"command": "sh", "env": {}}}},
    )
    source_mcp = repo_root / "claude-code" / "plugins" / "agent-wallet" / ".mcp.json"
    source_mcp_before = source_mcp.read_bytes()

    fake_bin = temp_root / "bin"
    fake_bin.mkdir()
    host_log = temp_root / "host-refresh.log"
    for command in ("codex", "claude"):
        script = fake_bin / command
        script.write_text(
            f"#!/bin/sh\nprintf '%s %s\\n' '{command}' \"$*\" >> '{host_log}'\n",
            encoding="utf-8",
        )
        script.chmod(0o755)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(home)
    env["HERMES_HOME"] = str(hermes_home)
    env["AGENT_WALLET_CODEX_PLUGIN_ROOT"] = str(codex_plugin_root)
    env["AGENT_WALLET_CODEX_MARKETPLACE_PATH"] = str(marketplace_path)
    env["AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR"] = str(claude_marketplace)
    env["AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT"] = str(claude_cache)
    env["OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH"] = str(cli)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-update-repair"
    env["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-update-repair"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval-secret-for-update-repair"
    env["AGENT_WALLET_VERIFY_DISABLE"] = "1"
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

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
    assert payload["ok"] is True, payload
    assert payload["command"] == "update", payload
    assert Path(payload["runtime_root"]).resolve() == (runtime_base / "releases" / package_version).resolve()

    refresh = {item["name"]: item for item in payload["integration_refresh"]}
    assert refresh["hermes"]["ok"] is True, refresh
    assert refresh["codex"]["ok"] is True, refresh
    assert refresh["claude-code"]["ok"] is True, refresh
    assert refresh["openclaw"]["ok"] is True, refresh

    registry = json.loads((runtime_base / "integrations.json").read_text(encoding="utf-8"))
    assert registry["integrations"]["openclaw"]["managed"] is True, registry
    updated_openclaw = json.loads(openclaw_config.read_text(encoding="utf-8"))
    assert updated_openclaw["plugins"]["load"]["paths"] == [
        str(current / ".openclaw" / "extensions" / "agent-wallet")
    ]
    assert updated_openclaw["plugins"]["entries"]["agent-wallet"]["config"][
        "packageRoot"
    ] == str(current / "agent-wallet")

    assert os.readlink(hermes_plugin_target) == str(current / "hermes" / "plugins" / "agent_wallet")
    assert os.readlink(codex_plugin_target) == str(current / "codex" / "plugins" / "agent-wallet")
    assert os.readlink(claude_plugin_target) == str(
        current / "claude-code" / "plugins" / "agent-wallet"
    )

    hermes_env = (hermes_home / ".env").read_text(encoding="utf-8")
    assert f"AGENT_WALLET_PACKAGE_ROOT={current / 'agent-wallet'}" in hermes_env
    assert f"AGENT_WALLET_PYTHON={old_release / 'agent-wallet' / '.runtime-venv' / 'bin' / 'python'}" not in hermes_env
    cache_env = json.loads(claude_cache_mcp.read_text(encoding="utf-8"))["mcpServers"][
        "agent-wallet"
    ]["env"]
    assert cache_env["OPENCLAW_HOME"] == str(home), cache_env
    assert source_mcp.read_bytes() == source_mcp_before
    host_commands = host_log.read_text(encoding="utf-8")
    assert "codex plugin add agent-wallet@local" in host_commands, host_commands
    assert "claude plugin marketplace add" in host_commands, host_commands
    assert "claude plugin install agent-wallet@agentlayer-local" in host_commands, host_commands

    print("smoke_update_repairs_editor_installs: ok")


if __name__ == "__main__":
    main()
