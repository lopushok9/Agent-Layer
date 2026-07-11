"""Concurrent installs are serialized and a live lock is never stolen."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def _command(cli: Path) -> list[str]:
    return [
        "node",
        str(cli),
        "install",
        "--yes",
        "--backend",
        "none",
        "--skip-python-setup",
        "--skip-node-setup",
    ]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin" / "openclaw-agent-wallet.mjs"
    temp_root = Path(tempfile.mkdtemp(prefix="openclaw-update-lock-"))
    try:
        env = dict(os.environ)
        env.update(
            {
                "OPENCLAW_HOME": str(temp_root),
                "AGENT_WALLET_BOOT_KEY": "test-boot-key-update-lock",
                "AGENT_WALLET_MASTER_KEY": "test-master-key-update-lock",
                "AGENT_WALLET_APPROVAL_SECRET": "test-approval-update-lock",
                "AGENT_WALLET_VERIFY_DISABLE": "1",
                "HERMES_HOME": str(temp_root / "hermes"),
                "CODEX_HOME": str(temp_root / "codex-home"),
                "AGENT_WALLET_CODEX_PLUGIN_ROOT": str(temp_root / "codex-plugins"),
                "AGENT_WALLET_CODEX_MARKETPLACE_PATH": str(temp_root / "marketplace.json"),
                "AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR": str(temp_root / "claude-marketplace"),
                "AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT": str(temp_root / "claude-cache"),
            }
        )
        first = subprocess.Popen(
            _command(cli),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**env, "AGENT_WALLET_TEST_HOLD_LOCK_MS": "3000"},
        )
        owner_path = temp_root / "agent-wallet-runtime" / "update.lock" / "owner.json"
        for _ in range(100):
            if owner_path.exists():
                break
            time.sleep(0.05)
        assert owner_path.exists(), "first installer did not acquire the lock"

        second = subprocess.run(
            _command(cli), capture_output=True, text=True, env=env, timeout=30
        )
        assert second.returncode != 0, second.stderr
        assert '"category": "update_locked"' in second.stderr, second.stderr
        assert "test-boot-key" not in second.stderr

        first_stdout, first_stderr = first.communicate(timeout=300)
        assert first.returncode == 0, (first_stdout, first_stderr)
        assert not owner_path.parent.exists()

        print("smoke_update_lock: ok")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
