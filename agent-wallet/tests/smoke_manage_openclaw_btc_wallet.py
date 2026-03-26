"""Smoke test for the host-side BTC wallet management script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_btc_test_server import FakeWdkBtcWalletServer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "manage_openclaw_btc_wallet.py"


def _run(*args: str, stdin_text: str | None = None) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        input=stdin_text,
    )
    return json.loads(completed.stdout)


def main() -> None:
    with FakeWdkBtcWalletServer(network="testnet") as server:
        os.environ["OPENCLAW_HOME"] = "/tmp/openclaw-btc-script-smoke"

        created = _run(
            "create",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "testnet",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-btc-password\n",
        )
        assert created["wallet"]["wallet_id"] == server.wallet_id

        binding = _run(
            "get",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "testnet",
        )
        assert binding["wallet"]["wallet_id"] == server.wallet_id

        locked = _run(
            "lock",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "testnet",
            "--service-url",
            server.base_url,
        )
        assert locked["wallet"]["unlocked"] is False

        unlocked = _run(
            "unlock",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "testnet",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-btc-password\n",
        )
        assert unlocked["wallet"]["unlocked"] is True

    print("smoke_manage_openclaw_btc_wallet: ok")


if __name__ == "__main__":
    main()
