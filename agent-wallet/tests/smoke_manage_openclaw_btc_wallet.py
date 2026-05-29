"""Smoke test for the host-side BTC wallet management script."""

from __future__ import annotations

import json
import os
import shutil
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
    with FakeWdkBtcWalletServer(network="bitcoin") as server:
        temp_home = Path("/tmp/openclaw-btc-script-smoke")
        if temp_home.exists():
            shutil.rmtree(temp_home)
        os.environ["OPENCLAW_HOME"] = str(temp_home)
        os.environ["WDK_BTC_LOCAL_TOKEN"] = server.auth_token

        setup_created = _run(
            "setup",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "bitcoin",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-btc-password\n",
        )
        assert setup_created["action"] == "created"
        assert setup_created["wallet"]["wallet_id"] == server.wallet_id
        assert setup_created["openclaw_config_hint"]["backend"] == "wdk_btc_local"

        binding = _run(
            "get",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "bitcoin",
        )
        assert binding["wallet"]["wallet_id"] == server.wallet_id

        locked = _run(
            "lock",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "bitcoin",
            "--service-url",
            server.base_url,
        )
        assert locked["wallet"]["unlocked"] is False

        unlocked = _run(
            "unlock",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "bitcoin",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-btc-password\n",
        )
        assert unlocked["wallet"]["unlocked"] is True

        revealed = _run(
            "reveal-seed",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "bitcoin",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-btc-password\n",
        )
        assert revealed["wallet"]["seed_phrase"] == (
            "abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon abandon abandon about"
        )

        setup_unlocked = _run(
            "setup",
            "--user-id",
            "script-btc@example.com",
            "--network",
            "bitcoin",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-btc-password\n",
        )
        assert setup_unlocked["action"] == "unlocked"
        assert setup_unlocked["wallet"]["wallet_id"] == server.wallet_id
        os.environ.pop("WDK_BTC_LOCAL_TOKEN", None)

    print("smoke_manage_openclaw_btc_wallet: ok")


if __name__ == "__main__":
    main()
