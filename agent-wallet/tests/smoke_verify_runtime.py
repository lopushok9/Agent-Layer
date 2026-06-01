"""Smoke test: verifyRuntime gate via the hidden --self-verify command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVER_STUB = '''import sys, json
line = sys.stdin.readline()
req = json.loads(line)
print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":{"serverInfo":{"name":"Agent Wallet","version":"test"}}}))
sys.stdout.flush()
'''


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    tmp = Path("/tmp/openclaw-verify-runtime")
    if tmp.exists():
        shutil.rmtree(tmp)
    release = tmp / "release"
    codex_dir = release / "codex/plugins/agent-wallet"
    venv_bin = release / "agent-wallet/.runtime-venv/bin"
    codex_dir.mkdir(parents=True, exist_ok=True)
    venv_bin.mkdir(parents=True, exist_ok=True)
    # Symlink the venv python to the host python so the handshake can run.
    (venv_bin / "python").symlink_to(sys.executable)

    env = dict(os.environ)

    # Good server -> ok true.
    (codex_dir / "server.py").write_text(SERVER_STUB, encoding="utf-8")
    res = subprocess.run(
        ["node", str(cli), "--self-verify", str(release)],
        capture_output=True, text=True, env=env, timeout=40,
    )
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True, payload
    assert res.returncode == 0

    # Broken server -> ok false, exit 1.
    (codex_dir / "server.py").write_text("def broken(\n", encoding="utf-8")
    res = subprocess.run(
        ["node", str(cli), "--self-verify", str(release)],
        capture_output=True, text=True, env=env, timeout=40,
    )
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False, payload
    assert res.returncode == 1

    print("OK smoke_verify_runtime")


if __name__ == "__main__":
    main()
