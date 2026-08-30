"""Smoke test: two different OPENCLAW_HOMEs never share an EVM daemon socket.

Before the unix-socket transport, two wallet homes could collide on the
same shared TCP port and evm_user_wallets.py needed ~300 lines of lsof/PID/
cwd cross-checking just to refuse touching a foreign daemon safely. With a
per-home socket path, the collision this guarded against can't happen at
all — this test is the replacement for
smoke_openclaw_evm_runtime_restart_wrong_home.py, which asserted the old
refusal behavior for a scenario that is now structurally impossible.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.config import resolve_wdk_evm_service_url, settings  # noqa: E402


def main() -> None:
    original_home = os.environ.get("OPENCLAW_HOME")
    original_setting = settings.wdk_evm_service_url
    home_a = Path(tempfile.mkdtemp(prefix="wdk-evm-home-a-"))
    home_b = Path(tempfile.mkdtemp(prefix="wdk-evm-home-b-"))
    try:
        settings.wdk_evm_service_url = ""

        os.environ["OPENCLAW_HOME"] = str(home_a)
        url_a = resolve_wdk_evm_service_url()

        os.environ["OPENCLAW_HOME"] = str(home_b)
        url_b = resolve_wdk_evm_service_url()

        assert url_a != url_b, "two different homes resolved to the same socket"
        assert url_a == f"unix://{home_a / 'wdk-evm-wallet' / 'daemon.sock'}"
        assert url_b == f"unix://{home_b / 'wdk-evm-wallet' / 'daemon.sock'}"
    finally:
        settings.wdk_evm_service_url = original_setting
        if original_home is None:
            os.environ.pop("OPENCLAW_HOME", None)
        else:
            os.environ["OPENCLAW_HOME"] = original_home
        shutil.rmtree(home_a, ignore_errors=True)
        shutil.rmtree(home_b, ignore_errors=True)

    print("smoke_evm_wallet_home_isolation: ok")


if __name__ == "__main__":
    main()
