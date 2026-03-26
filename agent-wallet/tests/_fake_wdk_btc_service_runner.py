"""Standalone runner for the fake WDK BTC service used by bootstrap smokes."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_btc_test_server import FakeWdkBtcWalletServer  # noqa: E402


def main() -> None:
    network = os.getenv("WDK_BTC_NETWORK", "bitcoin").strip() or "bitcoin"
    host = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("PORT", "8080").strip() or "8080")
    with FakeWdkBtcWalletServer(network=network, host=host, port=port) as server:
        while True:
            time.sleep(1)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    raise SystemExit(main())
