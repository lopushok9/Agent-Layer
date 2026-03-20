"""Smoke test for Jupiter Earn response normalization in the Solana backend."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import jupiter  # noqa: E402
from agent_wallet.wallet_layer.solana import SolanaWalletBackend  # noqa: E402


async def main() -> None:
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        address="So11111111111111111111111111111111111111112",
        sign_only=True,
    )

    original_fetch_earn_tokens = jupiter.fetch_earn_tokens
    original_fetch_earn_positions = jupiter.fetch_earn_positions
    original_fetch_earn_earnings = jupiter.fetch_earn_earnings
    try:
        async def fake_fetch_earn_tokens() -> dict:
            return {
                "tokens": [
                    {
                        "asset": "So11111111111111111111111111111111111111112",
                        "symbol": "SOL",
                    }
                ]
            }

        async def fake_fetch_earn_positions(*, users: list[str]) -> dict:
            return {
                "positions": [
                    {
                        "user": users[0],
                        "asset": "So11111111111111111111111111111111111111112",
                        "address": "11111111111111111111111111111111",
                    }
                ]
            }

        async def fake_fetch_earn_earnings(*, user: str, positions: list[str]) -> dict:
            return {
                "earnings": [
                    {
                        "user": user,
                        "position": positions[0],
                        "asset": "So11111111111111111111111111111111111111112",
                        "amountUsd": 1.23,
                    }
                ]
            }

        jupiter.fetch_earn_tokens = fake_fetch_earn_tokens
        jupiter.fetch_earn_positions = fake_fetch_earn_positions
        jupiter.fetch_earn_earnings = fake_fetch_earn_earnings

        tokens = await backend.get_jupiter_earn_tokens()
        assert tokens["token_count"] == 1
        assert tokens["tokens"][0]["symbol"] == "SOL"

        positions = await backend.get_jupiter_earn_positions(
            users=["So11111111111111111111111111111111111111112"]
        )
        assert positions["position_count"] == 1
        assert positions["positions"][0]["asset"] == "So11111111111111111111111111111111111111112"

        earnings = await backend.get_jupiter_earn_earnings(
            user="So11111111111111111111111111111111111111112",
            positions=["11111111111111111111111111111111"],
        )
        assert len(earnings["earnings"]) == 1
        assert earnings["earnings"][0]["amountUsd"] == 1.23
    finally:
        jupiter.fetch_earn_tokens = original_fetch_earn_tokens
        jupiter.fetch_earn_positions = original_fetch_earn_positions
        jupiter.fetch_earn_earnings = original_fetch_earn_earnings

    print("smoke_jupiter_earn_responses: ok")


if __name__ == "__main__":
    asyncio.run(main())
