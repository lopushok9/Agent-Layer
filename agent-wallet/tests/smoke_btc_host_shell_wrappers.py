"""Smoke test for the host-side BTC shell wrappers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from _wdk_btc_test_server import FakeWdkBtcWalletServer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup_btc_wallet.sh"
REVEAL_SCRIPT = ROOT / "scripts" / "reveal_btc_seed.sh"


def main() -> None:
    temp_home = Path("/tmp/openclaw-btc-host-shell-wrappers")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-btc-host-shell",
        master_key="test-master-key-for-btc-host-shell",
        approval_secret="test-approval-secret-for-btc-host-shell",
    )

    config_path = temp_home / "openclaw.json"
    with FakeWdkBtcWalletServer(network="bitcoin") as server:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["OPENCLAW_HOME"] = str(temp_home)
        env["OPENCLAW_AGENT_WALLET_PYTHON"] = sys.executable
        env["WDK_BTC_LOCAL_TOKEN"] = server.auth_token
        env["OPENCLAW_BTC_CONFIG_PATH"] = str(config_path)
        env["OPENCLAW_BTC_USER_ID"] = "host-shell@example.com"
        env["OPENCLAW_BTC_NETWORK"] = "mainnet"
        env["OPENCLAW_BTC_SERVICE_URL"] = server.base_url

        setup = subprocess.run(
            [
                "sh",
                str(SETUP_SCRIPT),
                "--password-stdin",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            input="host-shell-password\n",
        )
        setup_payload = json.loads(setup.stdout)
        assert setup_payload["ok"] is True
        assert setup_payload["btc_setup"]["wallet"]["wallet_id"] == server.wallet_id

        reveal = subprocess.run(
            [
                "sh",
                str(REVEAL_SCRIPT),
                "--password-stdin",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            input="host-shell-password\n",
        )
        reveal_payload = json.loads(reveal.stdout)
        assert reveal_payload["wallet"]["seed_phrase"] == (
            "abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon abandon abandon about"
        )

    print("smoke_btc_host_shell_wrappers: ok")


if __name__ == "__main__":
    main()
