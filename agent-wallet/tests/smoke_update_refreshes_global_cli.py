"""Smoke test: an npm-exec installer refreshes an existing stale global CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    package = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    temp_root = Path("/tmp/openclaw-update-refreshes-global-cli")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True)

    global_root = temp_root / "global-node-modules"
    global_package = global_root / "@agentlayer.tech" / "wallet"
    global_package.mkdir(parents=True)
    (global_package / "package.json").write_text(
        json.dumps({"name": package["name"], "version": "0.0.1"}) + "\n",
        encoding="utf-8",
    )

    fake_bin = temp_root / "bin"
    fake_bin.mkdir()
    npm_log = temp_root / "npm.log"
    npm = fake_bin / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        "if [ \"$1 $2\" = \"root --global\" ]; then\n"
        f"  printf '%s\\n' '{global_root}'\n"
        "  exit 0\n"
        "fi\n"
        f"printf '%s\\n' \"$*\" >> '{npm_log}'\n",
        encoding="utf-8",
    )
    npm.chmod(0o755)

    home = temp_root / "home"
    env = dict(os.environ)
    env.update(
        {
            "OPENCLAW_HOME": str(home),
            "HERMES_HOME": str(temp_root / "hermes"),
            "CODEX_HOME": str(temp_root / "codex-home"),
            "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(temp_root / "codex-plugins"),
            "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(temp_root / "marketplace.json"),
            "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(temp_root / "claude-marketplace"),
            "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(temp_root / "claude-cache"),
            "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH": str(cli),
            "AGENT_WALLET_FORCE_GLOBAL_CLI_REFRESH": "1",
            "AGENT_WALLET_BOOT_KEY": "test-boot-key-global-cli-refresh",
            "AGENT_WALLET_MASTER_KEY": "test-master-key-global-cli-refresh",
            "AGENT_WALLET_APPROVAL_SECRET": "test-approval-secret-global-cli-refresh",
            "AGENT_WALLET_VERIFY_DISABLE": "1",
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
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
        check=False,
        env=env,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    payload = json.loads(completed.stdout)
    refresh = payload["global_cli_refresh"]
    assert refresh["attempted"] is True, refresh
    assert refresh["ok"] is True, refresh
    assert refresh["previous_version"] == "0.0.1", refresh
    assert refresh["target_version"] == package["version"], refresh
    command = npm_log.read_text(encoding="utf-8")
    assert (
        f"install --global --no-audit --no-fund {package['name']}@{package['version']}" in command
    ), command

    print("smoke_update_refreshes_global_cli: ok")


if __name__ == "__main__":
    main()
