"""Smoke test: EVM service URL resolution defaults to a per-home unix socket."""

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
    temp_home = Path(tempfile.mkdtemp(prefix="wdk-evm-default-url-"))
    try:
        os.environ["OPENCLAW_HOME"] = str(temp_home)
        settings.wdk_evm_service_url = ""
        resolved = resolve_wdk_evm_service_url()
        assert resolved == f"unix://{temp_home / 'wdk-evm-wallet' / 'daemon.sock'}", resolved

        # An explicit setting always wins, whatever transport it names.
        settings.wdk_evm_service_url = "http://127.0.0.1:8081"
        assert resolve_wdk_evm_service_url() == "http://127.0.0.1:8081"

        settings.wdk_evm_service_url = "unix:///custom/path/daemon.sock"
        assert resolve_wdk_evm_service_url() == "unix:///custom/path/daemon.sock"
    finally:
        settings.wdk_evm_service_url = original_setting
        if original_home is None:
            os.environ.pop("OPENCLAW_HOME", None)
        else:
            os.environ["OPENCLAW_HOME"] = original_home
        shutil.rmtree(temp_home, ignore_errors=True)

    print("smoke_wdk_evm_default_service_url: ok")


if __name__ == "__main__":
    main()
