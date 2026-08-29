"""Smoke test: WdkEvmLocalClient talks to a real daemon over a unix socket."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient  # noqa: E402


def main() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="wdk-evm-unix-client-"))
    socket_path = str(temp_dir / "daemon.sock")
    try:
        with FakeWdkEvmWalletServer(
            socket_path=socket_path,
            network="base",
            auth_token="unix-socket-test-token",
        ):
            os.environ["WDK_EVM_LOCAL_TOKEN"] = "unix-socket-test-token"
            client = WdkEvmLocalClient(f"unix://{socket_path}")

            async def _run() -> dict:
                return await client.get("/v1/evm/network")

            # /v1/evm/network requires auth and returns a "data"-wrapped dict
            # like every other route, so this exercises the full GET path
            # (headers + body unwrap) over the unix socket transport.
            result = asyncio.run(_run())
            assert result.get("activeNetwork") == "base", result

            sync_result = client.get_sync("/v1/evm/network")
            assert sync_result == result
    finally:
        os.environ.pop("WDK_EVM_LOCAL_TOKEN", None)
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("smoke_wdk_evm_unix_socket_client: ok")


if __name__ == "__main__":
    main()
