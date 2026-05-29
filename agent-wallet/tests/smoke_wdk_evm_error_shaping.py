"""Smoke tests for structured EVM error shaping."""

from __future__ import annotations

import os
import shutil
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def _unused_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-error-shaping")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)

    with FakeWdkEvmWalletServer(
        network="ethereum",
        auth_token="correct-token",
        error_responses={
            "POST /v1/evm/transfer/quote": {
                "status": 409,
                "payload": {
                    "ok": False,
                    "error": "insufficient funds for gas * price + value",
                    "error_code": "insufficient_funds",
                    "error_details": {"source": "wdk-evm-wallet", "path": "/v1/evm/transfer/quote"},
                },
            },
            "POST /v1/evm/token-balance/get": {
                "status": 404,
                "payload": {
                    "ok": False,
                    "error": "Token contract could not be resolved on this network.",
                    "error_code": "token_not_found",
                    "error_details": {"source": "wdk-evm-wallet", "path": "/v1/evm/token-balance/get"},
                },
            },
            "POST /v1/evm/address/resolve": {
                "status": 409,
                "payload": {
                    "ok": False,
                    "error": "Wallet is locked. Unlock it first or provide seedPhrase explicitly.",
                    "error_code": "wallet_locked",
                    "error_details": {"source": "wdk-evm-wallet", "path": "/v1/evm/address/resolve"},
                },
            },
        },
    ) as server:
        os.environ["WDK_EVM_LOCAL_TOKEN"] = "correct-token"
        client = WdkEvmLocalClient(server.base_url)

        try:
            client.post_sync(
                "/v1/evm/transfer/quote",
                {"walletId": server.wallet_id, "network": "ethereum", "to": server.address, "value": "1"},
            )
            raise AssertionError("Expected insufficient_funds to be raised.")
        except WalletBackendError as exc:
            assert exc.code == "insufficient_funds"
            assert exc.details == {"source": "wdk-evm-wallet", "path": "/v1/evm/transfer/quote"}

        try:
            client.post_sync(
                "/v1/evm/token-balance/get",
                {
                    "walletId": server.wallet_id,
                    "network": "ethereum",
                    "tokenAddress": "0x2222222222222222222222222222222222222222",
                },
            )
            raise AssertionError("Expected token_not_found to be raised.")
        except WalletBackendError as exc:
            assert exc.code == "token_not_found"
            assert exc.details == {"source": "wdk-evm-wallet", "path": "/v1/evm/token-balance/get"}

        try:
            client.post_sync(
                "/v1/evm/address/resolve",
                {"walletId": server.wallet_id, "network": "ethereum", "accountIndex": 0},
            )
            raise AssertionError("Expected wallet_locked to be raised.")
        except WalletBackendError as exc:
            assert exc.code == "wallet_locked"
            assert exc.details == {"source": "wdk-evm-wallet", "path": "/v1/evm/address/resolve"}

    os.environ["WDK_EVM_LOCAL_TOKEN"] = "correct-token"
    unavailable_client = WdkEvmLocalClient(f"http://127.0.0.1:{_unused_port()}")
    try:
        unavailable_client.post_sync("/v1/evm/wallets/get", {"walletId": "missing"})
        raise AssertionError("Expected network_unavailable to be raised.")
    except WalletBackendError as exc:
        assert exc.code == "network_unavailable"
        assert exc.details == {"service": "wdk-evm-wallet", "path": "/v1/evm/wallets/get"}

    print("smoke_wdk_evm_error_shaping: ok")


if __name__ == "__main__":
    main()
