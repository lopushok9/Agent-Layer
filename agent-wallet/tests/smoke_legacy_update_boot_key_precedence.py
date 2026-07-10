"""A pre-resolver runtime env beats a conflicting legacy boot-key file."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_home = Path(tempfile.mkdtemp(prefix="openclaw-legacy-update-precedence-"))
    atexit.register(shutil.rmtree, temp_home, ignore_errors=True)
    runtime_base = temp_home / "agent-wallet-runtime"
    old_release = runtime_base / "releases" / "0.1.53"
    old_agent_wallet = old_release / "agent-wallet"
    old_agent_wallet.mkdir(parents=True)
    (old_agent_wallet / ".env").write_text(
        "AGENT_WALLET_BOOT_KEY=correct-key-from-current-runtime\n",
        encoding="utf-8",
    )
    (runtime_base / "current").symlink_to(old_release)
    (runtime_base / "boot-key").write_text("stale-shared-file-key\n", encoding="utf-8")
    (temp_home / "sealed_keys.json").write_text('{"legacy":"fixture"}\n', encoding="utf-8")

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE"}
    }
    env["OPENCLAW_HOME"] = str(temp_home)
    env["OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH"] = str(cli)
    env["AGENT_WALLET_VERIFY_DISABLE"] = "1"
    env["HERMES_HOME"] = str(temp_home / "hermes")
    env["AGENT_WALLET_CODEX_PLUGIN_ROOT"] = str(temp_home / "codex-plugins")
    env["AGENT_WALLET_CODEX_MARKETPLACE_PATH"] = str(temp_home / "codex-marketplace.json")
    env["AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR"] = str(temp_home / "claude-marketplace")
    env["AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT"] = str(temp_home / "claude-cache")

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
    assert payload["boot_key_source"] == "current_runtime_env", payload
    assert payload["active_version"] == json.loads(
        (repo_root / "package.json").read_text(encoding="utf-8")
    )["version"]
    assert not list((runtime_base / "releases").glob(".staging-*"))

    print("smoke_legacy_update_boot_key_precedence: ok")


if __name__ == "__main__":
    main()
