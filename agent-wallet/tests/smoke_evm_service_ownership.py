"""EVM daemon stop signals only a verified, still-owned local pid."""

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
    payload = {"service": "wdk-evm-wallet", "instanceId": "instance-a", "pid": PID}
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

    originals = {"kill": evm.os.kill, "health": evm._service_health}
    signalled: list[tuple[int, int]] = []

    try:
        # A live pid the caller owns: SIGTERM, then the wait loop sees it
        # gone via a dropped /health and returns cleanly.
        evm.os.kill = lambda pid, sig: signalled.append((pid, sig))
        evm._service_health = lambda _url: None
        evm._stop_local_service(SERVICE_URL, _health())
        assert (PID, signal.SIGTERM) in signalled, signalled

        # No pid in /health at all: refuse before ever signalling.
        signalled.clear()
        _expect_refusal(
            "missing pid",
            lambda: evm._stop_local_service(SERVICE_URL, _health(pid=0)),
        )
        assert signalled == [], signalled

        # os.kill(pid, 0) says the process is already gone: treat as success,
        # not a refusal — nothing left to signal.
        signalled.clear()

        def _kill_already_gone(pid, sig):
            if sig == 0:
                raise ProcessLookupError()
            signalled.append((pid, sig))

        evm.os.kill = _kill_already_gone
        evm._stop_local_service(SERVICE_URL, _health())
        assert signalled == [], signalled

        # os.kill(pid, 0) says the pid belongs to another user: refuse.
        signalled.clear()

        def _kill_foreign_user(pid, sig):
            if sig == 0:
                raise PermissionError("owned by another user")
            signalled.append((pid, sig))

        evm.os.kill = _kill_foreign_user
        _expect_refusal(
            "foreign-user pid",
            lambda: evm._stop_local_service(SERVICE_URL, _health()),
        )
        assert signalled == [], signalled

        # The escape hatch refuses before any pid check at all.
        signalled.clear()
        evm.os.kill = lambda pid, sig: signalled.append((pid, sig))
        os.environ["OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER"] = "1"
        _expect_refusal(
            "kill switch",
            lambda: evm._stop_local_service(SERVICE_URL, _health()),
        )
        assert signalled == [], signalled
    finally:
        evm.os.kill = originals["kill"]
        evm._service_health = originals["health"]
        os.environ.pop("OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER", None)
        shutil.rmtree(home, ignore_errors=True)

    print("smoke_evm_service_ownership: ok")


if __name__ == "__main__":
    main()
