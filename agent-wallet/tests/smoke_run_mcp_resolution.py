"""Smoke test: run_mcp.sh resolves server.py and self-checks it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(launcher: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(launcher)],
        input="",
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    launcher = repo_root / "claude-code/plugins/agent-wallet/scripts/run_mcp.sh"
    tmp = Path("/tmp/openclaw-run-mcp-resolution")
    if tmp.exists():
        shutil.rmtree(tmp)
    home = tmp / "openclaw"
    runtime_codex = home / "agent-wallet-runtime/current/codex/plugins/agent-wallet"
    runtime_codex.mkdir(parents=True, exist_ok=True)

    base_env = dict(os.environ)
    base_env["OPENCLAW_HOME"] = str(home)
    base_env["AGENT_WALLET_PYTHON"] = sys.executable

    # Case A: no server.py anywhere -> structured "not found" error, exit 1.
    res = _run(launcher, base_env)
    assert res.returncode == 1, f"expected exit 1, got {res.returncode}: {res.stderr}"
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert "not found" in payload["error"].lower(), payload
    assert "install --yes" in payload["fix"], payload

    # Case B: server.py present but broken -> structured "failed to parse" error, exit 1.
    (runtime_codex / "server.py").write_text("def broken(\n", encoding="utf-8")
    res = _run(launcher, base_env)
    assert res.returncode == 1, f"expected exit 1, got {res.returncode}: {res.stderr}"
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert "parse" in payload["error"].lower(), payload
    assert payload["server_py"].endswith("server.py"), payload

    print("OK smoke_run_mcp_resolution")


if __name__ == "__main__":
    main()
