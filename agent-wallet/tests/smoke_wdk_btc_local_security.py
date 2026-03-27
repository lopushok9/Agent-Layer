"""Smoke tests for WDK BTC local client security guardrails."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_btc_test_server import FakeWdkBtcWalletServer  # noqa: E402
from agent_wallet.providers.wdk_btc_local import WdkBtcLocalClient  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-btc-local-security")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ.pop("WDK_BTC_LOCAL_TOKEN", None)

    try:
        WdkBtcLocalClient("https://example.com")
        raise AssertionError("Remote WDK BTC service URL should be rejected.")
    except WalletBackendError as exc:
        assert "localhost" in str(exc).lower()

    try:
        WdkBtcLocalClient("http://127.0.0.1:8080")
        raise AssertionError("Missing local auth token should be rejected.")
    except WalletBackendError as exc:
        assert "token" in str(exc).lower()

    with FakeWdkBtcWalletServer(network="testnet", auth_token="correct-token") as server:
        os.environ["WDK_BTC_LOCAL_TOKEN"] = "wrong-token"
        try:
            WdkBtcLocalClient(server.base_url).post_sync(
                "/v1/btc/wallets/get",
                {"walletId": server.wallet_id},
            )
            raise AssertionError("Wrong local auth token should be rejected.")
        except WalletBackendError as exc:
            assert "unauthorized" in str(exc).lower()

        os.environ["WDK_BTC_LOCAL_TOKEN"] = "correct-token"
        payload = WdkBtcLocalClient(server.base_url).post_sync(
            "/v1/btc/wallets/get",
            {"walletId": server.wallet_id},
        )
        assert payload["walletId"] == server.wallet_id

    print("smoke_wdk_btc_local_security: ok")


if __name__ == "__main__":
    main()
