"""EVM daemon restart signals only verified owners or one legacy listener."""

from __future__ import annotations

import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402
import agent_wallet.evm_user_wallets as evm  # noqa: E402


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="openclaw-evm-owner-"))
    os.environ["OPENCLAW_HOME"] = str(home)
    expected_data_dir = str(home / "wdk-evm-wallet")
    expected_instance = evm._expected_local_service_instance_id()
    service_url = "http://127.0.0.1:18081"

    original_listeners = evm._listening_pids
    original_kill = evm.os.kill
    original_health = evm._service_health
    killed: list[tuple[int, int]] = []
    try:
        evm._listening_pids = lambda _port: [4242]
        evm.os.kill = lambda pid, sig: killed.append((pid, sig))
        evm._service_health = lambda _url: None

        foreign = {
            "service": "wdk-evm-wallet",
            "dataDir": expected_data_dir,
            "instanceId": "foreign-instance",
            "pid": 4242,
        }
        assert evm._should_restart_local_service(foreign, wallet_root=None) is True
        try:
            evm._stop_local_service(service_url, foreign)
            raise AssertionError("foreign instance must not be stopped")
        except WalletBackendError:
            pass
        assert killed == [], killed

        legacy = {
            "service": "wdk-evm-wallet",
            "dataDir": expected_data_dir,
            "pid": 0,
        }
        evm._stop_local_service(service_url, legacy)
        assert killed == [(4242, signal.SIGTERM)], killed

        owned = {
            "service": "wdk-evm-wallet",
            "dataDir": expected_data_dir,
            "instanceId": expected_instance,
            "pid": 4242,
        }
        assert evm._should_restart_local_service(owned, wallet_root=None) is False
    finally:
        evm._listening_pids = original_listeners
        evm.os.kill = original_kill
        evm._service_health = original_health
        shutil.rmtree(home, ignore_errors=True)

    print("smoke_evm_service_ownership: ok")


if __name__ == "__main__":
    main()
