"""A host integration failure cannot fail an already committed runtime update."""

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
    version = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))["version"]
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-isolate-integration-failure-"))
    try:
        runtime_base = temp_root / "agent-wallet-runtime"
        old_release = runtime_base / "releases" / "0.0.9"
        old_plugin = old_release / "codex" / "plugins" / "agent-wallet"
        _write_json(
            old_plugin / ".codex-plugin" / "plugin.json",
            {"name": "agent-wallet", "version": "0.0.9"},
        )
        (runtime_base / "current").symlink_to(old_release)

        plugin_target = temp_root / "codex-plugins" / "agent-wallet"
        plugin_target.parent.mkdir(parents=True)
        plugin_target.symlink_to(old_plugin)
        marketplace = temp_root / "marketplace.json"
        marketplace.write_text("{not-json\n", encoding="utf-8")
        _write_json(
            runtime_base / "integrations.json",
            {
                "schema_version": 1,
                "integrations": {
                    "codex": {
                        "managed": True,
                        "installed_version": "0.0.9",
                        "plugin_target": str(plugin_target),
                        "marketplace_path": str(marketplace),
                        "codex_home": str(temp_root / "codex-home"),
                    }
                },
            },
        )

        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(temp_root),
                "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH": str(cli),
                "AGENT_WALLET_BOOT_KEY": "test-boot-key-integration-failure",
                "AGENT_WALLET_MASTER_KEY": "test-master-key-integration-failure",
                "AGENT_WALLET_APPROVAL_SECRET": "test-approval-integration-failure",
                "AGENT_WALLET_VERIFY_DISABLE": "1",
                "HERMES_HOME": str(temp_root / "hermes"),
                "CODEX_HOME": str(temp_root / "codex-home"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(temp_root / "codex-plugins"),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(marketplace),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(temp_root / "claude-marketplace"),
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
            env=env,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        codex = next(item for item in payload["integration_refresh"] if item["name"] == "codex")
        assert codex["ok"] is False, codex
        assert "JSON" in codex["error"], codex
        assert payload["active_version"] == version, payload
        assert (runtime_base / "current").resolve() == (
            runtime_base / "releases" / version
        ).resolve()

        print("smoke_update_isolates_integration_failures: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
