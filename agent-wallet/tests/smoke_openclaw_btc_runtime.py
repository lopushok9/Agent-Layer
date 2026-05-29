"""Smoke test for host-side OpenClaw BTC wallet onboarding flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _wdk_btc_test_server import FakeWdkBtcWalletServer  # noqa: E402


def main() -> None:
    with FakeWdkBtcWalletServer(network="bitcoin") as server:
        os.environ["AGENT_WALLET_BACKEND"] = "wdk_btc_local"
        os.environ["WDK_BTC_SERVICE_URL"] = server.base_url
        os.environ["WDK_BTC_LOCAL_TOKEN"] = server.auth_token
        os.environ.pop("WDK_BTC_WALLET_ID", None)
        os.environ["WDK_BTC_ACCOUNT_INDEX"] = "0"
        os.environ["SOLANA_NETWORK"] = "mainnet"

        from agent_wallet.btc_user_wallets import create_user_btc_wallet  # noqa: E402
        from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet  # noqa: E402

        created = create_user_btc_wallet(
            "runtime-btc@example.com",
            password="runtime-btc-password",
            network="bitcoin",
            service_url=server.base_url,
        )
        assert created["wallet_id"] == server.wallet_id

        context = onboard_openclaw_user_wallet("runtime-btc@example.com", network="bitcoin")
        session = context.session_metadata()
        bundle = context.serializable_bundle()

        assert context.created_now is False
        assert session.chain == "bitcoin"
        assert session.backend == "wdk_btc_local"
        assert session.network == "bitcoin"
        assert session.storage_format == "local_vault"
        assert session.address.startswith("bc1")
        assert "transfer_btc" in session.tool_names
        assert "transfer_sol" not in session.tool_names
        assert bundle["session"]["address"] == session.address

    print("smoke_openclaw_btc_runtime: ok")


if __name__ == "__main__":
    main()
