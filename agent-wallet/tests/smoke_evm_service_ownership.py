"""EVM daemon stop signals only a verified same-home local listener."""

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

SERVICE_URL = "http://127.0.0.1:18081"
PID = 4242


def _health(**overrides):
    payload = {
        "service": "wdk-evm-wallet",
        "dataDir": str(evm._expected_local_service_data_dir()),
        "instanceId": "instance-a",
        "pid": PID,
    }
    payload.update(overrides)
    return payload


def _owner(**overrides):
    payload = {
        "pid": PID,
        "port": 18081,
        "data_dir": str(evm._expected_local_service_data_dir()),
        "instance_id": "instance-a",
    }
    payload.update(overrides)
    return payload


def _expect_refusal(label: str, callback) -> None:
    try:
        callback()
    except WalletBackendError:
        return
    raise AssertionError(f"{label} must be refused")


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="openclaw-evm-owner-"))
    os.environ["OPENCLAW_HOME"] = str(home)

    originals = {
        "listeners": evm._listening_pids,
        "cwd": evm._process_cwd,
        "owner": evm._read_service_owner,
        "exists": evm._process_exists,
        "kill": evm.os.kill,
        "health": evm._service_health,
    }
    signalled: list[tuple[int, int]] = []

    try:
        evm._listening_pids = lambda _port: [PID]
        evm._process_cwd = lambda _pid: Path("/tmp/runtime/wdk-evm-wallet")
        evm._read_service_owner = lambda: _owner()
        evm._process_exists = lambda _pid: False
        evm._service_health = lambda _url: None
        evm.os.kill = lambda pid, sig: signalled.append((pid, sig))

        # A stale instance is stoppable only because every same-home OS and
        # ownership check confirms the exact listener.
        evm._stop_local_service(
            SERVICE_URL,
            _health(instanceId="instance-a"),
        )
        assert (PID, signal.SIGTERM) in signalled, signalled

        signalled.clear()
        evm._listening_pids = lambda _port: [9999]
        _expect_refusal(
            "health pid absent from listeners",
            lambda: evm._stop_local_service(SERVICE_URL, _health()),
        )
        assert signalled == [], signalled

        signalled.clear()
        evm._listening_pids = lambda _port: []
        _expect_refusal(
            "missing listener inspection",
            lambda: evm._stop_local_service(SERVICE_URL, _health()),
        )
        assert signalled == [], signalled

        signalled.clear()
        evm._listening_pids = lambda _port: [PID]
        evm._process_cwd = lambda _pid: Path("/tmp/unrelated-service")
        _expect_refusal(
            "foreign process cwd",
            lambda: evm._stop_local_service(SERVICE_URL, _health()),
        )
        assert signalled == [], signalled

        signalled.clear()
        evm._process_cwd = lambda _pid: Path("/tmp/runtime/wdk-evm-wallet")
        evm._read_service_owner = lambda: _owner(pid=9999)
        _expect_refusal(
            "ownership record mismatch",
            lambda: evm._stop_local_service(SERVICE_URL, _health()),
        )
        assert signalled == [], signalled

        signalled.clear()
        evm._read_service_owner = lambda: _owner()
        foreign_dir = home / "other-wallet-home"
        _expect_refusal(
            "different wallet home",
            lambda: evm._stop_local_service(
                SERVICE_URL,
                _health(dataDir=str(foreign_dir)),
            ),
        )
        assert signalled == [], signalled

        signalled.clear()
        os.environ["OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER"] = "1"
        _expect_refusal(
            "kill switch",
            lambda: evm._stop_local_service(SERVICE_URL, _health()),
        )
        assert signalled == [], signalled
    finally:
        evm._listening_pids = originals["listeners"]
        evm._process_cwd = originals["cwd"]
        evm._read_service_owner = originals["owner"]
        evm._process_exists = originals["exists"]
        evm.os.kill = originals["kill"]
        evm._service_health = originals["health"]
        os.environ.pop("OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER", None)
        shutil.rmtree(home, ignore_errors=True)

    print("smoke_evm_service_ownership: ok")


if __name__ == "__main__":
    main()
