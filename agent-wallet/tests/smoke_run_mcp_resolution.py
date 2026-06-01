"""Smoke test: run_mcp.sh resolves server.py and self-checks it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    tmp = Path(tempfile.mkdtemp())
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

    # Case C: server.py present and valid -> launcher exits 0, no JSON error on stderr.
    (runtime_codex / "server.py").write_text("pass\n", encoding="utf-8")
    res = _run(launcher, base_env)
    assert res.returncode == 0, f"expected exit 0, got {res.returncode}: {res.stderr}"
    assert res.stderr.strip() == "" or '"error"' not in res.stderr, (
        f"unexpected error in stderr: {res.stderr}"
    )

    # --- Codex launcher section ---
    codex_launcher = repo_root / "codex/plugins/agent-wallet/scripts/run_mcp.sh"
    codex_tmp = Path(tempfile.mkdtemp())
    plugin_dir = codex_tmp / "codexplugin"
    scripts_dir = plugin_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    dest_launcher = scripts_dir / "run_mcp.sh"
    shutil.copy(str(codex_launcher), str(dest_launcher))
    os.chmod(str(dest_launcher), 0o755)

    codex_env = dict(os.environ)
    codex_env["OPENCLAW_HOME"] = str(codex_tmp / "openclaw_home")
    codex_env["AGENT_WALLET_PYTHON"] = sys.executable

    # Codex Case 1: no server.py -> "not found" error, exit 1.
    res = _run(dest_launcher, codex_env)
    assert res.returncode == 1, f"codex: expected exit 1, got {res.returncode}: {res.stderr}"
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert "not found" in payload["error"].lower(), payload

    # Codex Case 2: broken server.py -> "parse" error with server_py key, exit 1.
    (plugin_dir / "server.py").write_text("def broken(\n", encoding="utf-8")
    res = _run(dest_launcher, codex_env)
    assert res.returncode == 1, f"codex: expected exit 1, got {res.returncode}: {res.stderr}"
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert "parse" in payload["error"].lower(), payload
    assert payload["server_py"].endswith("server.py"), payload

    print("OK smoke_run_mcp_resolution")


if __name__ == "__main__":
    main()
