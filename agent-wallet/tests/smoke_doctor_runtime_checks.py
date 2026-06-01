"""Smoke test: doctor validates the live runtime and reports fixes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVER_STUB = '''import sys, json
req = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":{"serverInfo":{"name":"Agent Wallet","version":"t"}}}))
sys.stdout.flush()
'''


def _doctor(cli: Path, env: dict):
    res = subprocess.run(["node", str(cli), "doctor", "--deep"],
                         capture_output=True, text=True, env=env, timeout=60)
    return json.loads(res.stdout.strip()), res.returncode


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    tmp = Path("/tmp/openclaw-doctor-runtime")
    if tmp.exists():
        shutil.rmtree(tmp)
    home = tmp / "openclaw"
    release = home / "agent-wallet-runtime/releases/9.9.9"
    codex_dir = release / "codex/plugins/agent-wallet"
    venv_bin = release / "agent-wallet/.runtime-venv/bin"
    codex_dir.mkdir(parents=True, exist_ok=True)
    venv_bin.mkdir(parents=True, exist_ok=True)
    (venv_bin / "python").symlink_to(sys.executable)
    current = home / "agent-wallet-runtime/current"
    current.symlink_to(release)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(home)

    try:
        # Healthy runtime -> all checks ok, exit 0.
        (codex_dir / "server.py").write_text(SERVER_STUB, encoding="utf-8")
        payload, code = _doctor(cli, env)
        names = {c["name"]: c for c in payload["checks"]}
        assert names["current_symlink"]["ok"] is True, payload
        assert names["server_py_parses"]["ok"] is True, payload
        assert names["mcp_initialize_handshake"]["ok"] is True, payload
        assert payload["ok"] is True and code == 0, payload

        # Broken server.py -> handshake/parse fail with a fix string, exit 1.
        (codex_dir / "server.py").write_text("def broken(\n", encoding="utf-8")
        payload, code = _doctor(cli, env)
        names = {c["name"]: c for c in payload["checks"]}
        assert names["server_py_parses"]["ok"] is False, payload
        assert "install --yes" in names["server_py_parses"]["fix"], payload
        assert payload["ok"] is False and code == 1, payload

        print("OK smoke_doctor_runtime_checks")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
