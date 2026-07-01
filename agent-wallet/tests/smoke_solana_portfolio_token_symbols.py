"""Smoke test: get_portfolio enriches SPL token entries with symbol/name from
Jupiter's token search API, and tolerates that lookup failing."""

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

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
UNKNOWN_MINT = "UnknownMint1111111111111111111111111111111"
OWNER = "11111111111111111111111111111111"


def _fake_token_accounts(owner):
    def make(mint, amount, decimals, pubkey):
        return {
            "pubkey": pubkey,
            "account": {
                "owner": TOKEN_PROGRAM_ID,
                "data": {
                    "parsed": {
                        "info": {
                            "mint": mint,
                            "owner": owner,
                            "tokenAmount": {
                                "amount": str(amount),
                                "uiAmount": amount / (10**decimals),
                                "decimals": decimals,
                            },
                            "state": "initialized",
                        }
                    }
                },
            },
        }

    return [
        make(USDC_MINT, 1_500_000, 6, "FakeUsdcAta"),
        make(UNKNOWN_MINT, 42_000_000_000, 9, "FakeUnknownAta"),
    ]


async def main() -> None:
    original_fetch_balance = solana_rpc.fetch_balance
    original_fetch_token_accounts = solana_rpc.fetch_token_accounts_by_owner
    original_fetch_prices = jupiter.fetch_prices
    original_fetch_token_metadata = jupiter.fetch_token_metadata

    async def fake_fetch_balance(address, rpc_url, commitment="confirmed"):
        return {
            "address": address,
            "chain": "solana",
            "balance_native": 1.0,
            "balance_usd": None,
            "source": "fake-rpc",
        }

    async def fake_fetch_token_accounts_by_owner(owner, rpc_url, token_program_id=TOKEN_PROGRAM_ID):
        if token_program_id == TOKEN_2022_PROGRAM_ID:
            return []
        return _fake_token_accounts(owner)

    async def fake_fetch_prices(*, mints, show_extra_info=False):
        return {mint: {"usdPrice": 1} for mint in mints}

    async def fake_fetch_token_metadata(*, mints):
        # Jupiter doesn't index every mint (e.g. brand new/illiquid tokens).
        # Only USDC resolves; UNKNOWN_MINT is simply absent from the result.
        return {mint: {"symbol": "USDC", "name": "USD Coin"} for mint in mints if mint == USDC_MINT}

    solana_rpc.fetch_balance = fake_fetch_balance
    solana_rpc.fetch_token_accounts_by_owner = fake_fetch_token_accounts_by_owner

    async def failing_fetch_token_metadata(*, mints):
        raise ProviderError("jupiter", "token search unavailable")

    try:
        jupiter.fetch_prices = fake_fetch_prices
        jupiter.fetch_token_metadata = fake_fetch_token_metadata
        backend = SolanaWalletBackend(
            rpc_url="http://127.0.0.1:8899", network="mainnet", address=OWNER, sign_only=True
        )
        overview = await backend.get_portfolio()

        # A total metadata-provider outage must not break pricing or crash the call.
        jupiter.fetch_token_metadata = failing_fetch_token_metadata
        backend2 = SolanaWalletBackend(
            rpc_url="http://127.0.0.1:8899", network="mainnet", address=OWNER, sign_only=True
        )
        overview2 = await backend2.get_portfolio()
    finally:
        solana_rpc.fetch_balance = original_fetch_balance
        solana_rpc.fetch_token_accounts_by_owner = original_fetch_token_accounts
        jupiter.fetch_prices = original_fetch_prices
        jupiter.fetch_token_metadata = original_fetch_token_metadata

    by_mint = {a["mint"]: a for a in overview["assets"]}
    assert by_mint[NATIVE_SOL_MINT]["symbol"] == "SOL"
    assert by_mint[USDC_MINT]["symbol"] == "USDC"
    assert by_mint[USDC_MINT]["name"] == "USD Coin"
    # Mints Jupiter can't resolve fall back to symbol=None (callers already
    # fall back to the mint address for display), not a crash.
    assert by_mint[UNKNOWN_MINT]["symbol"] is None
    assert by_mint[UNKNOWN_MINT]["value_usd"] is not None  # pricing still worked
    assert overview["token_metadata_source"] == "jupiter-token-search"
    assert overview["token_metadata_errors"] == []

    by_mint2 = {a["mint"]: a for a in overview2["assets"]}
    assert by_mint2[USDC_MINT]["symbol"] is None
    assert by_mint2[USDC_MINT]["value_usd"] is not None
    assert overview2["token_metadata_source"] is None
    assert len(overview2["token_metadata_errors"]) == 1

    print("smoke_solana_portfolio_token_symbols: ok")


if __name__ == "__main__":
    asyncio.run(main())
