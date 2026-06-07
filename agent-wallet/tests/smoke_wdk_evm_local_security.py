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
from agent_wallet.wallet_layer.wdk_evm import WdkEvmLocalWalletBackend  # noqa: E402


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

    with FakeWdkEvmWalletServer(network="ethereum", auth_token="correct-token") as server:
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

    with FakeWdkEvmWalletServer(
        network="base",
        auth_token="correct-token",
        response_delays={
            "POST /v1/evm/swap/quote": 11.0,
            "POST /v1/evm/lifi/quote": 11.0,
        },
    ) as server:
        os.environ["WDK_EVM_LOCAL_TOKEN"] = "correct-token"
        client = WdkEvmLocalClient(server.base_url)
        unlock = client.post_sync("/v1/evm/wallets/unlock", {"walletId": server.wallet_id})
        assert unlock["unlocked"] is True
        swap_quote = client.post_sync(
            "/v1/evm/swap/quote",
            {
                "walletId": server.wallet_id,
                "address": server.address,
                "network": "base",
                "tokenIn": server.token,
                "tokenOut": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "tokenInAmount": "100000",
            },
        )
        assert swap_quote["protocol"] == "velora"
        lifi_quote = client.post_sync(
            "/v1/evm/lifi/quote",
            {
                "walletId": server.wallet_id,
                "address": server.address,
                "network": "base",
                "tokenIn": server.token,
                "destinationChain": "1",
                "outputToken": "0x0000000000000000000000000000000000000000",
                "destinationAddress": "0x3333333333333333333333333333333333333333",
                "tokenInAmount": "100000",
            },
        )
        assert lifi_quote["tool"] == "across"

    with FakeWdkEvmWalletServer(network="base", auth_token="correct-token") as server:
        os.environ["WDK_EVM_LOCAL_TOKEN"] = "correct-token"
        backend = WdkEvmLocalWalletBackend(
            service_url=server.base_url,
            wallet_id=server.wallet_id,
            network="base",
        )
        signature = backend.sign_x402_evm_exact_typed_data(
            domain={
                "name": "USD Coin",
                "version": "2",
                "chainId": 8453,
                "verifyingContract": server.token,
            },
            types={
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"},
                ]
            },
            primary_type="TransferWithAuthorization",
            message={
                "from": server.address,
                "to": "0x3333333333333333333333333333333333333333",
                "value": "1000000",
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": bytes.fromhex("22" * 32),
            },
        )
        assert isinstance(signature, bytes)
        assert len(signature) == 65
        assert server.sent_payloads[-1]["path"] == "/v1/evm/x402/exact/sign"
        assert server.sent_payloads[-1]["body"]["message"]["nonce"] == "0x" + ("22" * 32)

    assert _timeout_for_path("/v1/evm/swap/send") >= 120.0
    assert _timeout_for_path("/v1/evm/transfer/send") >= 120.0
    assert _timeout_for_path("/v1/evm/token-transfer/send") >= 120.0
    assert _timeout_for_path("/v1/evm/swap/quote") >= 120.0
    # Uniswap is a same-class write path (approve + swap = two on-chain
    # confirmations) and must share the long-running timeout, not the 10s default.
    assert _timeout_for_path("/v1/evm/uniswap/swap/send") >= 120.0
    assert _timeout_for_path("/v1/evm/uniswap/swap/quote") >= 120.0
    assert _timeout_for_path("/v1/evm/lifi/quote") >= 120.0

    print("smoke_wdk_evm_local_security: ok")


if __name__ == "__main__":
    main()
