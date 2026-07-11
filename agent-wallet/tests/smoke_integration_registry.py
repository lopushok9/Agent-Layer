"""Explicit host installs record non-secret AgentLayer ownership metadata."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-integration-registry-"))
    try:
        home = temp_root / "home"
        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(home),
                "HERMES_HOME": str(temp_root / "hermes"),
                "CODEX_HOME": str(temp_root / "codex-home"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(temp_root / "codex-plugins"),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(
                    temp_root / "agents" / "plugins" / "marketplace.json"
                ),
                "AGENT_WALLET_CODEX_PLUGIN_SOURCE": str(
                    repo_root / "codex" / "plugins" / "agent-wallet"
                ),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(
                    temp_root / "claude-marketplace"
                ),
                "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(temp_root / "claude-cache"),
                "AGENT_WALLET_CLAUDE_CODE_PLUGIN_SOURCE": str(
                    repo_root / "claude-code" / "plugins" / "agent-wallet"
                ),
            }
        )

        for command in (
            ["hermes", "install", "--yes", "--skip-enable"],
            ["codex", "install", "--yes", "--skip-enable"],
            ["claude-code", "install", "--yes", "--skip-enable"],
        ):
            subprocess.run(
                ["node", str(cli), *command],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

        registry_path = home / "agent-wallet-runtime" / "integrations.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        assert registry["schema_version"] == 1, registry
        integrations = registry["integrations"]
        assert set(integrations) == {"hermes", "codex", "claude-code"}, integrations
        for name, entry in integrations.items():
            assert entry["managed"] is True, (name, entry)
            assert entry["installed_version"], (name, entry)
            assert not any("key" in field.lower() or "secret" in field.lower() for field in entry)

        print("smoke_integration_registry: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
