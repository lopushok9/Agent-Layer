"""Standalone runner for the fake WDK EVM service used by bootstrap smokes."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402


def main() -> None:
    network = os.getenv("WDK_EVM_NETWORK", "base").strip() or "base"
    host = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("PORT", "8081").strip() or "8081")
    auth_token = os.getenv("WDK_EVM_LOCAL_TOKEN", "test-local-evm-token").strip()
    with FakeWdkEvmWalletServer(
        network=network,
        host=host,
        port=port,
        auth_token=auth_token,
    ):
        while True:
            time.sleep(1)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    raise SystemExit(main())
