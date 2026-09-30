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

        socket_url = resolved

        # An explicit setting wins, whatever transport it names...
        settings.wdk_evm_service_url = "http://127.0.0.1:9090"
        assert resolve_wdk_evm_service_url() == "http://127.0.0.1:9090"

        settings.wdk_evm_service_url = "unix:///custom/path/daemon.sock"
        assert resolve_wdk_evm_service_url() == "unix:///custom/path/daemon.sock"

        # ...except the legacy TCP default old installers persisted, which
        # means "unset" and resolves to the per-home socket.
        for legacy in ("http://127.0.0.1:8081", "http://localhost:8081/"):
            settings.wdk_evm_service_url = legacy
            assert resolve_wdk_evm_service_url() == socket_url, legacy

        # An explicit TCP transport opt-out keeps it.
        os.environ["WDK_EVM_TRANSPORT"] = "tcp"
        settings.wdk_evm_service_url = "http://127.0.0.1:8081"
        assert resolve_wdk_evm_service_url() == "http://127.0.0.1:8081"
        os.environ.pop("WDK_EVM_TRANSPORT", None)

        # The CLI drops the legacy default from plugin config before any EVM
        # path reads it, and never exports it as WDK_EVM_SERVICE_URL.
        from agent_wallet import openclaw_cli

        os.environ.pop("WDK_EVM_SERVICE_URL", None)
        config = {"backend": "wdk_evm_local", "wdkEvmServiceUrl": "http://127.0.0.1:8081"}
        openclaw_cli._apply_config_overrides(config)
        assert "wdkEvmServiceUrl" not in config, config
        assert "WDK_EVM_SERVICE_URL" not in os.environ

        config = {"backend": "wdk_evm_local", "wdkEvmServiceUrl": "http://127.0.0.1:9090"}
        openclaw_cli._apply_config_overrides(config)
        assert config["wdkEvmServiceUrl"] == "http://127.0.0.1:9090"
    finally:
        settings.wdk_evm_service_url = original_setting
        os.environ.pop("WDK_EVM_TRANSPORT", None)
        if original_home is None:
            os.environ.pop("OPENCLAW_HOME", None)
        else:
            os.environ["OPENCLAW_HOME"] = original_home
        shutil.rmtree(temp_home, ignore_errors=True)

    print("smoke_wdk_evm_default_service_url: ok")


if __name__ == "__main__":
    main()
