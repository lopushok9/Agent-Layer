"""Smoke test for the one-command agent-wallet installer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    temp_root = Path("/tmp/openclaw-install-agent-wallet-smoke")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    config_path = temp_root / "openclaw.json"
    env_path = temp_root / ".env"

    script = Path(__file__).resolve().parents[1] / "scripts" / "install_agent_wallet.py"
    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(temp_root)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot-key-for-universal-installer"
    env["AGENT_WALLET_MASTER_KEY"] = "test-master-key-for-universal-installer"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval-secret-for-universal-installer"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(config_path),
            "--env-path",
            str(env_path),
            "--skip-python-setup",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["env_created"] is True
    assert payload["config_created"] is True
    assert payload["configured"] is True
    assert payload["pending_env"] == []
    assert Path(payload["env_path"]).exists()
    assert Path(payload["config_path"]).exists()

    config = json.loads(config_path.read_text(encoding="utf-8"))
    plugin = config["plugins"]["entries"]["agent-wallet"]
    assert plugin["enabled"] is True
    assert plugin["config"]["backend"] == "solana_local"

    dry_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(temp_root / "second-openclaw.json"),
            "--env-path",
            str(temp_root / "second.env"),
            "--skip-python-setup",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={k: v for k, v in env.items() if not k.startswith("AGENT_WALLET_")},
    )
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["configured"] is False
    assert dry_payload["pending_env"] == ["AGENT_WALLET_BOOT_KEY"]

    fresh_root = temp_root / "fresh-home"
    fresh_root.mkdir(parents=True, exist_ok=True)
    fresh = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config-path",
            str(fresh_root / "openclaw.json"),
            "--env-path",
            str(fresh_root / ".env"),
            "--skip-python-setup",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={
            key: value
            for key, value in os.environ.items()
            if key != "OPENCLAW_HOME" and not key.startswith("AGENT_WALLET_")
        }
        | {"OPENCLAW_HOME": str(fresh_root)},
    )
    fresh_payload = json.loads(fresh.stdout)
    assert fresh_payload["configured"] is False
    assert fresh_payload["pending_env"] == [
        "AGENT_WALLET_BOOT_KEY",
        "AGENT_WALLET_MASTER_KEY",
        "AGENT_WALLET_APPROVAL_SECRET",
    ]

    print("smoke_install_agent_wallet: ok")


if __name__ == "__main__":
    main()
