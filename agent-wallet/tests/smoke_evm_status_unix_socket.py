"""Smoke test: the EVM status/health probes work over a unix socket.

Two sibling probes used their own raw urlopen call, which raises
"URLError: unknown url type: unix" for the plan's new default service URL:

- manage_openclaw_evm_wallet.py's _service_health, reached by the Hermes
  `evm status` tool — it reported healthy=false for a perfectly healthy
  socket daemon, while the same payload's network_info (fetched via the
  unix-aware WdkEvmLocalClient) showed live data.
- bootstrap_openclaw_evm.py's _service_is_healthy, which made
  --no-auto-start-service reject a running daemon.

Both now delegate to the unix-aware evm_user_wallets._service_health. The
existing regression tests can't catch this because their fake servers are
TCP-only, so this test drives both through a socket-mode fake server.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANAGE_SCRIPT = ROOT / "scripts" / "manage_openclaw_evm_wallet.py"
BOOTSTRAP_SCRIPT = ROOT / "scripts" / "bootstrap_openclaw_evm.py"

AUTH_TOKEN = "test-local-evm-token"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="wdk-evm-status-unix-"))
    socket_path = str(temp_dir / "daemon.sock")
    service_url = f"unix://{socket_path}"

    original_token = os.environ.get("WDK_EVM_LOCAL_TOKEN")
    os.environ["WDK_EVM_LOCAL_TOKEN"] = AUTH_TOKEN
    try:
        manage = _load_module(MANAGE_SCRIPT, "manage_openclaw_evm_wallet_unix_status_test")
        bootstrap = _load_module(BOOTSTRAP_SCRIPT, "bootstrap_openclaw_evm_unix_status_test")

        with FakeWdkEvmWalletServer(
            socket_path=socket_path,
            network="base",
            auth_token=AUTH_TOKEN,
        ):
            # The agent-facing `status` payload must report the socket daemon
            # as healthy, and must not contradict its own network_info.
            payload = manage._status_payload(None, "base", service_url)
            service = payload["service"]
            assert service["healthy"] is True, service
            assert service["service_url"] == service_url, service
            assert service["health"]["service"] == "wdk-evm-wallet", service
            assert "error" not in service, service
            assert payload.get("network_info_error") is None, payload
            assert payload["network_info"]["activeNetwork"] == "base", payload

            # bootstrap's --no-auto-start-service gate must agree.
            assert bootstrap._service_is_healthy(service_url) is True

        # Once the daemon is gone both probes must report down (not raise).
        payload = manage._status_payload(None, "base", service_url)
        assert payload["service"]["healthy"] is False, payload
        assert payload["service"]["error"], payload
        assert bootstrap._service_is_healthy(service_url) is False
    finally:
        if original_token is None:
            os.environ.pop("WDK_EVM_LOCAL_TOKEN", None)
        else:
            os.environ["WDK_EVM_LOCAL_TOKEN"] = original_token
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("smoke_evm_status_unix_socket: ok")


if __name__ == "__main__":
    main()
