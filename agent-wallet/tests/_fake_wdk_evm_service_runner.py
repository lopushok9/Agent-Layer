"""Standalone runner for the fake WDK EVM service used by bootstrap smokes."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402


def _resolve_version() -> str:
    # Mirror the real daemon: report the launcher's package.json version, unless a
    # test forces a (stale) value via env to simulate an old long-running process.
    override = os.getenv("WDK_EVM_FAKE_VERSION", "").strip()
    if override:
        return override
    try:
        pkg = json.loads((Path.cwd() / "package.json").read_text(encoding="utf-8"))
        return str(pkg.get("version") or "").strip() or "test-version"
    except (OSError, ValueError):
        return "test-version"


def _resolve_data_dir() -> str | None:
    override = os.getenv("WDK_EVM_FAKE_DATA_DIR", "").strip()
    if override:
        return override
    configured = os.getenv("WDK_EVM_DATA_DIR", "").strip()
    if configured:
        return configured
    openclaw_home = os.getenv("OPENCLAW_HOME", "").strip()
    if not openclaw_home:
        return None
    return str(Path(openclaw_home).expanduser() / "wdk-evm-wallet")


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
        health_data_dir=_resolve_data_dir(),
        version=_resolve_version(),
        instance_id=os.getenv("WDK_EVM_INSTANCE_ID", "").strip() or None,
    ):
        while True:
            time.sleep(1)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    raise SystemExit(main())
