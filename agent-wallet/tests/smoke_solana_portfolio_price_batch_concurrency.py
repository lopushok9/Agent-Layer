"""Smoke test: get_portfolio fetches Jupiter price batches concurrently and
tolerates a failing batch without losing prices from the other batches."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.exceptions import ProviderError
from agent_wallet.providers import jupiter, solana_rpc
from agent_wallet.wallet_layer.solana import (
    NATIVE_SOL_MINT,
    TOKEN_2022_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    SolanaWalletBackend,
)

OWNER = "11111111111111111111111111111111"
# 25 distinct token mints + native SOL = 26 ids -> two 20-id batches.
TOKEN_MINTS = [f"FakeMint{i:039d}" for i in range(25)]
FAILING_BATCH_MINTS = {NATIVE_SOL_MINT, *TOKEN_MINTS[:19]}


async def main() -> None:
    original_fetch_balance = solana_rpc.fetch_balance
    original_fetch_token_accounts = solana_rpc.fetch_token_accounts_by_owner
    original_fetch_prices = jupiter.fetch_prices
    original_fetch_token_metadata = jupiter.fetch_token_metadata

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def fake_fetch_balance(address, rpc_url, commitment="confirmed"):
        return {
            "address": address,
            "chain": "solana",
            "balance_native": 1.0,
            "balance_usd": None,
            "source": "fake-rpc",
        }

    async def fake_fetch_token_accounts_by_owner(
        owner,
        rpc_url,
        token_program_id=TOKEN_PROGRAM_ID,
    ):
        if token_program_id == TOKEN_2022_PROGRAM_ID:
            return []
        return [
            {
                "pubkey": f"FakeAta{i:040d}",
                "account": {
                    "owner": TOKEN_PROGRAM_ID,
                    "data": {
                        "parsed": {
                            "info": {
                                "mint": mint,
                                "owner": owner,
                                "tokenAmount": {
                                    "amount": "1000000",
                                    "uiAmount": 1.0,
                                    "decimals": 6,
                                },
                                "state": "initialized",
                            }
                        }
                    },
                },
            }
            for i, mint in enumerate(TOKEN_MINTS)
        ]

    async def fake_fetch_prices(*, mints, show_extra_info=False):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        try:
            # Yield control so overlapping batches actually overlap instead of
            # completing before the next gather() task starts.
            await asyncio.sleep(0.05)
            if set(mints) == FAILING_BATCH_MINTS:
                raise ProviderError("jupiter", "simulated batch failure")
            return {mint: {"usdPrice": 2} for mint in mints}
        finally:
            async with lock:
                in_flight -= 1

    async def fake_fetch_token_metadata(*, mints):
        return {}

    solana_rpc.fetch_balance = fake_fetch_balance
    solana_rpc.fetch_token_accounts_by_owner = fake_fetch_token_accounts_by_owner
    jupiter.fetch_prices = fake_fetch_prices
    jupiter.fetch_token_metadata = fake_fetch_token_metadata

    try:
        backend = SolanaWalletBackend(
            rpc_url="http://127.0.0.1:8899",
            network="mainnet",
            address=OWNER,
            sign_only=True,
        )
        overview = await backend.get_portfolio()
    finally:
        solana_rpc.fetch_balance = original_fetch_balance
        solana_rpc.fetch_token_accounts_by_owner = original_fetch_token_accounts
        jupiter.fetch_prices = original_fetch_prices
        jupiter.fetch_token_metadata = original_fetch_token_metadata

    assert max_in_flight >= 2, "price batches did not run concurrently"
    assert len(overview["pricing_errors"]) == 1
    assert "simulated batch failure" in overview["pricing_errors"][0]
    # The failing batch covered native SOL + 19 tokens; the remaining 6 tokens
    # were in the second (successful) batch and must still be priced.
    priced_tokens = [t for t in overview["tokens"] if t["value_usd"] is not None]
    assert len(priced_tokens) == 6
    assert overview["native_value_usd"] is None

    print("smoke_solana_portfolio_price_batch_concurrency: ok")


if __name__ == "__main__":
    asyncio.run(main())
