"""Smoke test: _service_health fetches /health over a unix socket."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402
from agent_wallet.evm_user_wallets import _is_local_service_url, _service_health  # noqa: E402


def _check_is_local_service_url() -> None:
    # _auto_start_local_service refuses to start anything whose URL is not
    # local, so the unix:// default from resolve_wdk_evm_service_url has to
    # pass this check or the whole auto-start path is dead under the default.
    assert _is_local_service_url("unix:///tmp/some/daemon.sock") is True
    assert _is_local_service_url("unix://") is False
    assert _is_local_service_url("http://127.0.0.1:8081") is True
    assert _is_local_service_url("http://example.com:8081") is False


def main() -> None:
    _check_is_local_service_url()
    temp_dir = Path(tempfile.mkdtemp(prefix="wdk-evm-health-unix-"))
    socket_path = str(temp_dir / "daemon.sock")
    try:
        with FakeWdkEvmWalletServer(socket_path=socket_path, network="base"):
            health = _service_health(f"unix://{socket_path}")
            assert health is not None, "expected a healthy response over the unix socket"
            assert health.get("network") == "base", health

        # After the server exits, the same call must return None (not raise).
        assert _service_health(f"unix://{socket_path}") is None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("smoke_evm_service_health_unix: ok")


if __name__ == "__main__":
    main()
