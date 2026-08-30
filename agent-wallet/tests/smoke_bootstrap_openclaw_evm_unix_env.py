"""Smoke test: bootstrap_openclaw_evm derives socket env vars for a unix:// URL."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent_wallet.evm_user_wallets as evm  # noqa: E402

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_openclaw_evm.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bootstrap_openclaw_evm_unix_env_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = _load_module()
    wallet_root = Path(tempfile.mkdtemp(prefix="wdk-evm-unix-env-wallet-root-"))
    config_path = Path(tempfile.mkdtemp(prefix="wdk-evm-unix-env-config-")) / "openclaw.json"
    try:
        # _auto_start_local_service refuses to spawn without a launcher script.
        (wallet_root / "run-local.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        # The script imports these helpers from agent_wallet.evm_user_wallets
        # inside the function body, so patch them on their defining module.
        healthy_payload = {"service": "wdk-evm-wallet", "version": "1.2.3", "pid": 4242}
        mock_process = MagicMock()
        mock_process.poll.return_value = None

        with patch.object(evm, "_service_health", side_effect=[None, healthy_payload]), \
             patch.object(module.subprocess, "Popen", return_value=mock_process) as mock_popen, \
             patch.object(evm, "_expected_local_service_instance_id", return_value="test-instance"):
            module._auto_start_local_service(
                service_url="unix:///tmp/example-wdk-evm-wallet/daemon.sock",
                network="base",
                wdk_wallet_root=wallet_root,
                config_path=config_path,
            )

        env_passed = mock_popen.call_args.kwargs["env"]
        assert env_passed["WDK_EVM_TRANSPORT"] == "socket", env_passed.get("WDK_EVM_TRANSPORT")
        assert env_passed["WDK_EVM_SOCKET_PATH"] == "/tmp/example-wdk-evm-wallet/daemon.sock"
        assert "HOST" not in env_passed
        assert "PORT" not in env_passed

        # An http:// target still derives HOST/PORT, unaffected by this change.
        with patch.object(evm, "_service_health", side_effect=[None, healthy_payload]), \
             patch.object(module.subprocess, "Popen", return_value=mock_process) as mock_popen_tcp, \
             patch.object(evm, "_expected_local_service_instance_id", return_value="test-instance"):
            module._auto_start_local_service(
                service_url="http://127.0.0.1:18081",
                network="base",
                wdk_wallet_root=wallet_root,
                config_path=config_path,
            )
        env_passed = mock_popen_tcp.call_args.kwargs["env"]
        assert env_passed["WDK_EVM_TRANSPORT"] == "tcp"
        assert env_passed["HOST"] == "127.0.0.1"
        assert env_passed["PORT"] == "18081"
        assert "WDK_EVM_SOCKET_PATH" not in env_passed
    finally:
        shutil.rmtree(wallet_root, ignore_errors=True)
        shutil.rmtree(config_path.parent, ignore_errors=True)

    print("smoke_bootstrap_openclaw_evm_unix_env: ok")


if __name__ == "__main__":
    main()
