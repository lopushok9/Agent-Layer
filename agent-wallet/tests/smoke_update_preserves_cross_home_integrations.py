"""Legacy adoption never claims AgentLayer integrations from another runtime home."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-preserve-cross-home-"))
    try:
        home = temp_root / "isolated-home"
        runtime_base = home / "agent-wallet-runtime"
        old_release = runtime_base / "releases" / "0.0.9"
        old_release.mkdir(parents=True)
        (runtime_base / "current").symlink_to(old_release)

        external = temp_root / "production-runtime" / "releases" / "0.1.75"
        hermes_source = external / "hermes" / "plugins" / "agent_wallet"
        codex_source = external / "codex" / "plugins" / "agent-wallet"
        claude_source = external / "claude-code" / "plugins" / "agent-wallet"
        hermes_source.mkdir(parents=True)
        (hermes_source / "plugin.yaml").write_text("name: agent_wallet\n", encoding="utf-8")
        _write_json(codex_source / ".codex-plugin" / "plugin.json", {"name": "agent-wallet"})
        _write_json(claude_source / ".claude-plugin" / "plugin.json", {"name": "agent-wallet"})

        hermes_home = temp_root / "hermes"
        hermes_target = hermes_home / "plugins" / "agent_wallet"
        hermes_target.parent.mkdir(parents=True)
        hermes_target.symlink_to(hermes_source)

        codex_root = temp_root / "codex-plugins"
        codex_target = codex_root / "agent-wallet"
        codex_target.parent.mkdir(parents=True)
        codex_target.symlink_to(codex_source)
        codex_marketplace = temp_root / "marketplace.json"
        _write_json(
            codex_marketplace,
            {
                "name": "local",
                "plugins": [
                    {"name": "agent-wallet", "source": {"source": "local", "path": "./plugins/agent-wallet"}}
                ],
            },
        )

        claude_marketplace = temp_root / "claude-marketplace"
        claude_target = claude_marketplace / "plugins" / "agent-wallet"
        claude_target.parent.mkdir(parents=True)
        claude_target.symlink_to(claude_source)
        _write_json(
            claude_marketplace / ".claude-plugin" / "marketplace.json",
            {"name": "agentlayer-local", "plugins": [{"name": "agent-wallet"}]},
        )

        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(home),
                "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH": str(cli),
                "AGENT_WALLET_BOOT_KEY": "test-cross-home-boot-key",
                "AGENT_WALLET_MASTER_KEY": "test-cross-home-master-key",
                "AGENT_WALLET_APPROVAL_SECRET": "test-cross-home-approval",
                "AGENT_WALLET_VERIFY_DISABLE": "1",
                "HERMES_HOME": str(hermes_home),
                "CODEX_HOME": str(temp_root / "codex-home"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(codex_root),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(codex_marketplace),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(claude_marketplace),
                "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(temp_root / "claude-cache"),
            }
        )
        result = subprocess.run(
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
            timeout=300,
        )
        payload = json.loads(result.stdout)
        refreshed = {item["name"] for item in payload["integration_refresh"]}
        assert "hermes" not in refreshed, payload
        assert "codex" not in refreshed, payload
        assert "claude-code" not in refreshed, payload
        assert hermes_target.resolve() == hermes_source.resolve()
        assert codex_target.resolve() == codex_source.resolve()
        assert claude_target.resolve() == claude_source.resolve()

        registry = json.loads((runtime_base / "integrations.json").read_text(encoding="utf-8"))
        assert set(registry["integrations"]) == {"openclaw"}, registry

        print("smoke_update_preserves_cross_home_integrations: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
