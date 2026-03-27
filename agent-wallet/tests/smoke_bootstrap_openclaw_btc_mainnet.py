"""Smoke test for mainnet alias handling in the OpenClaw BTC bootstrap script."""

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
SCRIPT = ROOT / "scripts" / "bootstrap_openclaw_btc.py"


def main() -> None:
    temp_home = Path("/tmp/openclaw-btc-bootstrap-mainnet-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-btc-bootstrap-mainnet-smoke",
        master_key="test-master-key-for-btc-bootstrap-mainnet-smoke",
        approval_secret="test-approval-secret-for-btc-bootstrap-mainnet-smoke",
    )

    config_path = temp_home / "openclaw.json"
    with FakeWdkBtcWalletServer(network="bitcoin") as server:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["WDK_BTC_LOCAL_TOKEN"] = server.auth_token
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--config-path",
                str(config_path),
                "--user-id",
                "bootstrap-btc-mainnet@example.com",
                "--network",
                "mainnet",
                "--service-url",
                server.base_url,
                "--password-stdin",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            input="bootstrap-btc-mainnet-password\n",
        )
    payload = json.loads(completed.stdout)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    plugin_config = config["plugins"]["entries"]["agent-wallet"]["config"]

    assert payload["ok"] is True
    assert payload["btc_setup"]["wallet"]["network"] == "bitcoin"
    assert plugin_config["backend"] == "wdk_btc_local"
    assert plugin_config["network"] == "bitcoin"

    print("smoke_bootstrap_openclaw_btc_mainnet: ok")


if __name__ == "__main__":
    main()
