"""Smoke test for the host-side EVM shell wrapper."""

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
from agent_wallet.sealed_keys import unseal_keys  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup_evm_wallet.sh"


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-host-shell-wrappers")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-evm-host-shell",
        master_key="test-master-key-for-evm-host-shell",
        approval_secret="test-approval-secret-for-evm-host-shell",
    )

    config_path = temp_home / "openclaw.json"
    with FakeWdkEvmWalletServer(network="base") as server:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["OPENCLAW_HOME"] = str(temp_home)
        env["OPENCLAW_AGENT_WALLET_PYTHON"] = sys.executable
        env["WDK_EVM_LOCAL_TOKEN"] = server.auth_token
        env["OPENCLAW_EVM_CONFIG_PATH"] = str(config_path)
        env["OPENCLAW_EVM_USER_ID"] = "host-shell-evm@example.com"
        env["OPENCLAW_EVM_NETWORK"] = "base"
        env["OPENCLAW_EVM_SERVICE_URL"] = server.base_url

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
            input="host-shell-evm-password\n",
        )
        setup_payload = json.loads(setup.stdout)
        assert setup_payload["ok"] is True
        assert setup_payload["evm_setup"]["wallet"]["wallet_id"] == server.wallet_id
        assert setup_payload["evm_setup"]["paired_binding"]["network"] == "ethereum"
        assert unseal_keys("test-boot-key-for-evm-host-shell")["wdk_evm_wallet_password"] == "host-shell-evm-password"

    print("smoke_evm_host_shell_wrappers: ok")


if __name__ == "__main__":
    main()
