"""Smoke test for the host-side EVM wallet management script."""

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
SCRIPT = ROOT / "scripts" / "manage_openclaw_evm_wallet.py"


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
    with FakeWdkEvmWalletServer(network="base") as server:
        temp_home = Path("/tmp/openclaw-evm-script-smoke")
        if temp_home.exists():
            shutil.rmtree(temp_home)
        install_test_sealed_secrets(
            temp_home,
            boot_key="script-evm-boot-key",
            master_key="script-evm-master-key",
        )
        os.environ["WDK_EVM_LOCAL_TOKEN"] = server.auth_token
        os.environ["WDK_EVM_SERVICE_URL"] = server.base_url

        status = _run("status", "--network", "base")
        assert status["ok"] is True
        assert status["service"]["healthy"] is True
        assert status["network"] == "base"

        setup_created = _run(
            "setup",
            "--user-id",
            "script-evm@example.com",
            "--network",
            "base",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-evm-password\n",
        )
        assert setup_created["action"] == "created"
        assert setup_created["wallet"]["wallet_id"] == server.wallet_id
        assert setup_created["openclaw_config_hint"]["backend"] == "wdk_evm_local"
        assert setup_created["paired_binding"]["network"] == "ethereum"
        assert unseal_keys("script-evm-boot-key")["wdk_evm_wallet_password"] == "script-evm-password"

        binding = _run(
            "get",
            "--user-id",
            "script-evm@example.com",
            "--network",
            "base",
        )
        assert binding["wallet"]["wallet_id"] == server.wallet_id

        listed = _run(
            "list",
            "--user-id",
            "script-evm@example.com",
        )
        assert len(listed["wallets"]) == 2
        assert {item["network"] for item in listed["wallets"]} == {"base", "ethereum"}

        locked = _run(
            "lock",
            "--user-id",
            "script-evm@example.com",
            "--network",
            "base",
            "--service-url",
            server.base_url,
        )
        assert locked["wallet"]["unlocked"] is False

        unlocked = _run(
            "unlock",
            "--user-id",
            "script-evm@example.com",
            "--network",
            "base",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-evm-password\n",
        )
        assert unlocked["wallet"]["unlocked"] is True

        setup_unlocked = _run(
            "setup",
            "--user-id",
            "script-evm@example.com",
            "--network",
            "base",
            "--service-url",
            server.base_url,
            "--password-stdin",
            stdin_text="script-evm-password\n",
        )
        assert setup_unlocked["action"] == "unlocked"
        assert setup_unlocked["wallet"]["wallet_id"] == server.wallet_id
        os.environ.pop("WDK_EVM_LOCAL_TOKEN", None)

    print("smoke_manage_openclaw_evm_wallet: ok")


if __name__ == "__main__":
    main()
