"""Smoke test for Kamino response normalization in the Solana backend."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import kamino  # noqa: E402
from agent_wallet.wallet_layer.solana import SolanaWalletBackend  # noqa: E402


async def main() -> None:
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        address="So11111111111111111111111111111111111111112",
        sign_only=True,
    )

    original_fetch_markets = kamino.fetch_lend_markets
    original_fetch_reserves = kamino.fetch_lend_market_reserves
    original_fetch_obligations = kamino.fetch_lend_user_obligations
    original_fetch_rewards = kamino.fetch_lend_user_rewards
    try:
        async def fake_fetch_markets() -> dict:
            return {
                "markets": [
                    {
                        "lendingMarket": "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF",
                        "name": "Main Market",
                    }
                ]
            }

        async def fake_fetch_reserves(*, market: str, network: str) -> dict:
            return {
                "reserves": [
                    {
                        "reserve": "D6q6wuQSrifJKZYpR1M8R4YawnLDtDsMmWM1NbBmgJ59",
                        "liquidityToken": "USDC",
                    }
                ]
            }

        async def fake_fetch_obligations(*, market: str, user: str, network: str) -> dict:
            return {
                "obligations": [
                    {
                        "obligationAddress": "HcrU9nyaBFmhNPrxnwXRjreVxdQTZdq2dpvktjsWiS4J",
                        "state": {"owner": user},
                    }
                ]
            }

        async def fake_fetch_rewards(*, user: str) -> dict:
            return {
                "rewards": [{"symbol": "KMNO", "amount": "1.23"}],
                "avgBaseApy": "0.04",
            }

        kamino.fetch_lend_markets = fake_fetch_markets
        kamino.fetch_lend_market_reserves = fake_fetch_reserves
        kamino.fetch_lend_user_obligations = fake_fetch_obligations
        kamino.fetch_lend_user_rewards = fake_fetch_rewards

        markets = await backend.get_kamino_lend_markets()
        assert markets["market_count"] == 1
        assert markets["markets"][0]["name"] == "Main Market"

        reserves = await backend.get_kamino_lend_market_reserves(
            market="7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF"
        )
        assert reserves["reserve_count"] == 1
        assert reserves["reserves"][0]["liquidityToken"] == "USDC"

        obligations = await backend.get_kamino_lend_user_obligations(
            market="7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF",
            user="So11111111111111111111111111111111111111112",
        )
        assert obligations["obligation_count"] == 1
        assert obligations["obligations"][0]["state"]["owner"] == "So11111111111111111111111111111111111111112"

        rewards = await backend.get_kamino_lend_user_rewards(
            user="So11111111111111111111111111111111111111112"
        )
        assert rewards["reward_count"] == 1
        assert rewards["avg_base_apy"] == "0.04"
    finally:
        kamino.fetch_lend_markets = original_fetch_markets
        kamino.fetch_lend_market_reserves = original_fetch_reserves
        kamino.fetch_lend_user_obligations = original_fetch_obligations
        kamino.fetch_lend_user_rewards = original_fetch_rewards

    print("smoke_kamino_responses: ok")


if __name__ == "__main__":
    asyncio.run(main())
