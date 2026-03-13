"""Smoke test for switching the configured OpenClaw wallet network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "switch_openclaw_wallet_network.py"


def main() -> None:
    temp_dir = Path("/tmp/openclaw-switch-network-smoke")
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "openclaw.json"
    config_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "entries": {
                        "agent-wallet": {
                            "enabled": True,
                            "config": {
                                "userId": "switch-user@example.com",
                                "backend": "solana_local",
                                "network": "devnet",
                                "signOnly": False,
                                "openclawHome": str(temp_dir / ".openclaw"),
                            },
                        }
                    }
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    show_only = subprocess.run(
        [sys.executable, str(SCRIPT), "--config-path", str(config_path), "--network", "mainnet", "--show-only"],
        check=True,
        capture_output=True,
        text=True,
    )
    show_payload = json.loads(show_only.stdout)
    assert show_payload["selected_network"] == "mainnet"
    assert show_payload["wallet_exists"] is False

    switched = subprocess.run(
        [sys.executable, str(SCRIPT), "--config-path", str(config_path), "--network", "mainnet"],
        check=True,
        capture_output=True,
        text=True,
    )
    switched_payload = json.loads(switched.stdout)
    assert switched_payload["selected_network"] == "mainnet"
    assert "backup_path" in switched_payload

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["plugins"]["entries"]["agent-wallet"]["config"]["network"] == "mainnet"

    print("smoke_switch_openclaw_wallet_network: ok")


if __name__ == "__main__":
    main()
