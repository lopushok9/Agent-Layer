"""Smoke test: codex/claude install pins OPENCLAW_HOME into .mcp.json env."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    tmp = Path("/tmp/openclaw-mcp-env-pin")
    if tmp.exists():
        shutil.rmtree(tmp)
    home = tmp / "home"
    # Pre-stage a current runtime so the resolver has a venv python to pin.
    release = home / "agent-wallet-runtime/releases/9.9.9"
    venv_bin = release / "agent-wallet/.runtime-venv/bin"
    mcp_dir = release / "claude-code/plugins/agent-wallet"
    venv_bin.mkdir(parents=True, exist_ok=True)
    mcp_dir.mkdir(parents=True, exist_ok=True)
    (venv_bin / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (mcp_dir / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"agent-wallet": {"command": "sh",
            "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/run_mcp.sh"],
            "env": {"FASTMCP_LOG_LEVEL": "ERROR"}}}}), encoding="utf-8")
    (home / "agent-wallet-runtime/current").symlink_to(release)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(home)
    env["AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR"] = str(tmp / "marketplace")
    env["AGENT_WALLET_CLAUDE_CODE_PLUGIN_SOURCE"] = str(mcp_dir)

    try:
        res = subprocess.run(
            ["node", str(cli), "claude-code", "install", "--yes", "--skip-enable"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert res.returncode == 0, res.stderr + res.stdout

        pinned = json.loads((mcp_dir / ".mcp.json").read_text())
        server_env = pinned["mcpServers"]["agent-wallet"]["env"]
        assert server_env["OPENCLAW_HOME"] == str(home), server_env
        assert server_env["AGENT_WALLET_PYTHON"].endswith("python"), server_env
        # Pre-existing env keys must be preserved.
        assert server_env["FASTMCP_LOG_LEVEL"] == "ERROR", server_env

        print("OK smoke_editor_mcp_env_pin")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
