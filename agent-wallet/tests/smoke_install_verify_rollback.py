"""Smoke test: a release that fails verification is auto-rolled-back."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _install(cli: Path, env: dict):
    return subprocess.run(
        ["node", str(cli), "install", "--yes", "--backend", "none",
         "--skip-python-setup", "--skip-node-setup"],
        capture_output=True, text=True, env=env, timeout=600,
    )


def _last_json(text: str) -> dict:
    depth = 0
    start = None
    chunks = []
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunks.append(text[start:i + 1])
                start = None
    for chunk in reversed(chunks):
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"no JSON object found in: {text!r}")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    version = json.loads((repo_root / "package.json").read_text())["version"]
    tmp = Path("/tmp/openclaw-install-rollback")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(tmp)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot"
    env["AGENT_WALLET_MASTER_KEY"] = "test-master"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval"

    current = tmp / "agent-wallet-runtime/current"

    try:
        # 1) First install with verify disabled -> establishes a known-good current.
        env1 = {**env, "AGENT_WALLET_VERIFY_DISABLE": "1"}
        res = _install(cli, env1)
        assert res.returncode == 0, res.stderr
        good_target = os.readlink(current)
        assert version in good_target, good_target

        # 2) Second install with forced verify failure -> must roll back to good target.
        env2 = {**env, "AGENT_WALLET_VERIFY_FORCE_FAIL": "1"}
        res = _install(cli, env2)
        assert res.returncode != 0, "install should fail when verify fails"
        payload = _last_json(res.stderr)
        assert payload["ok"] is False, payload
        assert payload["rolled_back"] is True, payload
        assert payload["category"] == "broken_release", payload
        assert version in (payload["kept_version"] or ""), payload
        assert "message" in payload and "fix" in payload, payload
        after = os.readlink(current)
        assert after == good_target, f"current not rolled back: {after} != {good_target}"

        print("OK smoke_install_verify_rollback")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
