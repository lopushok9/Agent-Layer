"""Smoke test: the fake wdk-evm-wallet test server can listen on a unix socket.

Later tests (Task 4's client test, and any bootstrap smoke that wants a
socket-mode daemon without a real Node build) depend on this working.
"""

from __future__ import annotations

import http.client
import json
import shutil
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._socket_path)


def main() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="wdk-evm-fake-socket-"))
    socket_path = str(temp_dir / "daemon.sock")
    try:
        with FakeWdkEvmWalletServer(socket_path=socket_path, network="base"):
            conn = _UnixHTTPConnection(socket_path)
            conn.request("GET", "/health")
            response = conn.getresponse()
            assert response.status == 200
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["ok"] is True
            conn.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("smoke_fake_wdk_evm_server_socket_mode: ok")


if __name__ == "__main__":
    main()
