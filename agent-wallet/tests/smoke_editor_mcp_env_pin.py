"""Smoke test: claude install pins OPENCLAW_HOME into bundle + cache .mcp.json."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _mcp_doc():
    return {"mcpServers": {"agent-wallet": {"command": "sh",
            "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/run_mcp.sh"],
            "env": {"FASTMCP_LOG_LEVEL": "ERROR"}}}}


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    tmp = Path("/tmp/openclaw-mcp-env-pin")
    if tmp.exists():
        shutil.rmtree(tmp)
    home = tmp / "home"
    release = home / "agent-wallet-runtime/releases/9.9.9"
    mcp_dir = release / "claude-code/plugins/agent-wallet"
    mcp_dir.mkdir(parents=True, exist_ok=True)
    (mcp_dir / ".mcp.json").write_text(json.dumps(_mcp_doc()), encoding="utf-8")
    (home / "agent-wallet-runtime/current").symlink_to(release)

    # Pre-stage a Claude cache copy (simulating a prior install) under a temp cache root.
    cache_root = tmp / "cache"
    cache_mcp = cache_root / "agentlayer-local/agent-wallet/0.1.0/.mcp.json"
    cache_mcp.parent.mkdir(parents=True, exist_ok=True)
    cache_mcp.write_text(json.dumps(_mcp_doc()), encoding="utf-8")

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(home)
    env["AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR"] = str(tmp / "marketplace")
    env["AGENT_WALLET_CLAUDE_CODE_PLUGIN_SOURCE"] = str(mcp_dir)
    env["AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT"] = str(cache_root)

    try:
        res = subprocess.run(
            ["node", str(cli), "claude-code", "install", "--yes", "--skip-enable"],
            capture_output=True, text=True, env=env, timeout=120,
        )
        assert res.returncode == 0, res.stderr + res.stdout

        # Bundle .mcp.json pinned with OPENCLAW_HOME, existing key preserved, python NOT pinned.
        bundle_env = json.loads((mcp_dir / ".mcp.json").read_text())["mcpServers"]["agent-wallet"]["env"]
        assert bundle_env["OPENCLAW_HOME"] == str(home), bundle_env
        assert bundle_env["FASTMCP_LOG_LEVEL"] == "ERROR", bundle_env
        assert "AGENT_WALLET_PYTHON" not in bundle_env, bundle_env

        # Cache copy also pinned.
        cache_env = json.loads(cache_mcp.read_text())["mcpServers"]["agent-wallet"]["env"]
        assert cache_env["OPENCLAW_HOME"] == str(home), cache_env

        print("OK smoke_editor_mcp_env_pin")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
