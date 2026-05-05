"""Smoke test for the one-command OpenClaw EVM bootstrap script."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_openclaw_evm.py"


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-bootstrap-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-evm-bootstrap-smoke",
        master_key="test-master-key-for-evm-bootstrap-smoke",
        approval_secret="test-approval-secret-for-evm-bootstrap-smoke",
    )

    config_path = temp_home / "openclaw.json"
    with FakeWdkEvmWalletServer(network="base") as server:
        base_url = server.base_url
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["WDK_EVM_LOCAL_TOKEN"] = server.auth_token
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--config-path",
                str(config_path),
                "--user-id",
                "bootstrap-evm@example.com",
                "--network",
                "base",
                "--service-url",
                base_url,
                "--password-stdin",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            input="bootstrap-evm-password\n",
        )
    payload = json.loads(completed.stdout)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert payload["ok"] is True
    assert payload["evm_setup"]["wallet"]["wallet_id"] == server.wallet_id
    assert payload["evm_setup"]["paired_binding"]["network"] == "ethereum"
    plugin_config = config["plugins"]["entries"]["agent-wallet"]["config"]
    assert plugin_config["backend"] == "wdk_evm_local"
    assert plugin_config["network"] == "base"
    assert plugin_config["wdkEvmServiceUrl"] == base_url
    assert plugin_config["wdkEvmAccountIndex"] == 0
    assert "transfer_sol" in config["tools"]["alsoAllow"]

    print("smoke_bootstrap_openclaw_evm: ok")


if __name__ == "__main__":
    main()
