"""Smoke tests for WDK EVM local client security guardrails."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_evm_test_server import FakeWdkEvmWalletServer  # noqa: E402
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient, _timeout_for_path  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-local-security")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ.pop("WDK_EVM_LOCAL_TOKEN", None)

    try:
        WdkEvmLocalClient("https://example.com")
        raise AssertionError("Remote WDK EVM service URL should be rejected.")
    except WalletBackendError as exc:
        assert "localhost" in str(exc).lower()

    try:
        WdkEvmLocalClient("http://127.0.0.1:8081")
        raise AssertionError("Missing local auth token should be rejected.")
    except WalletBackendError as exc:
        assert "token" in str(exc).lower()

    with FakeWdkEvmWalletServer(network="sepolia", auth_token="correct-token") as server:
        os.environ["WDK_EVM_LOCAL_TOKEN"] = "wrong-token"
        try:
            WdkEvmLocalClient(server.base_url).post_sync(
                "/v1/evm/wallets/get",
                {"walletId": server.wallet_id},
            )
            raise AssertionError("Wrong local auth token should be rejected.")
        except WalletBackendError as exc:
            assert "unauthorized" in str(exc).lower()

        os.environ["WDK_EVM_LOCAL_TOKEN"] = "correct-token"
        payload = WdkEvmLocalClient(server.base_url).post_sync(
            "/v1/evm/wallets/get",
            {"walletId": server.wallet_id},
        )
        assert payload["walletId"] == server.wallet_id

    with FakeWdkEvmWalletServer(
        network="base",
        auth_token="correct-token",
        response_delays={"POST /v1/evm/swap/send": 11.0},
    ) as server:
        os.environ["WDK_EVM_LOCAL_TOKEN"] = "correct-token"
        client = WdkEvmLocalClient(server.base_url)
        unlock = client.post_sync("/v1/evm/wallets/unlock", {"walletId": server.wallet_id})
        assert unlock["unlocked"] is True
        sent = client.post_sync(
            "/v1/evm/swap/send",
            {
                "walletId": server.wallet_id,
                "network": "base",
                "tokenIn": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "tokenOut": server.token,
                "tokenInAmount": "465000000000000",
                "expectedQuoteFingerprint": "evm-swap-fingerprint-1",
            },
        )
        assert sent["protocol"] == "velora"

    assert _timeout_for_path("/v1/evm/swap/send") >= 120.0
    assert _timeout_for_path("/v1/evm/transfer/send") >= 120.0
    assert _timeout_for_path("/v1/evm/token-transfer/send") >= 120.0
    assert _timeout_for_path("/v1/evm/swap/quote") == 10.0

    print("smoke_wdk_evm_local_security: ok")


if __name__ == "__main__":
    main()
