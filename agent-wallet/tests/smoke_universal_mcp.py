"""Smoke test for the framework-neutral local MCP entry point."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path("/tmp/agentlayer-universal-mcp-smoke")
    shutil.rmtree(temp_root, ignore_errors=True)
    openclaw_home = temp_root / "openclaw-home"
    release = temp_root / "release"
    current = openclaw_home / "agent-wallet-runtime" / "current"
    shutil.copytree(repo_root / "mcp", release / "mcp")
    stub = release / "codex" / "plugins" / "agent-wallet" / "server.py"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        """import json, sys
line = sys.stdin.readline()
request = json.loads(line)
print(json.dumps({\"jsonrpc\": \"2.0\", \"id\": request[\"id\"], \"result\": {\"serverInfo\": {\"name\": \"Agent Wallet\", \"version\": \"test\"}}}))
sys.stdout.flush()
""",
        encoding="utf-8",
    )
    venv_python = release / "agent-wallet" / ".runtime-venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(sys.executable)
    current.parent.mkdir(parents=True)
    current.symlink_to(release, target_is_directory=True)

    env = {
        **os.environ,
        "OPENCLAW_HOME": str(openclaw_home),
        "AGENT_WALLET_DISABLE_UPDATE_CHECK": "1",
        "AGENT_WALLET_NO_TELEMETRY": "1",
    }
    try:
        config_result = subprocess.run(
            ["node", str(cli), "mcp", "config"],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=20,
        )
        config = json.loads(config_result.stdout)
        entry = config["mcpServers"]["agent-wallet"]
        launcher = current / "mcp" / "scripts" / "run_mcp.sh"
        assert entry["command"] == "sh", entry
        assert entry["args"] == [str(launcher)], entry
        assert entry["env"]["OPENCLAW_HOME"] == str(openclaw_home), entry
        assert entry["env"]["AGENT_WALLET_HOST"] == "mcp", entry

        path_result = subprocess.run(
            ["node", str(cli), "mcp", "path"],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            timeout=20,
        )
        assert path_result.stdout.strip() == str(launcher)

        init = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "universal-mcp-smoke", "version": "0"},
                },
            }
        )
        serve_result = subprocess.run(
            ["node", str(cli), "mcp", "serve"],
            input=f"{init}\n",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert serve_result.returncode == 0, serve_result.stderr
        assert '"serverInfo"' in serve_result.stdout, serve_result.stdout
        print("smoke_universal_mcp: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
