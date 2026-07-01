"""Smoke test for Solana wallet overview without external RPC."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import jupiter, solana_rpc
from agent_wallet.wallet_layer.solana import (
    NATIVE_SOL_MINT,
    TOKEN_2022_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    SolanaWalletBackend,
)


USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
OWNER = "11111111111111111111111111111111"


async def main() -> None:
    original_fetch_balance = solana_rpc.fetch_balance
    original_fetch_token_accounts = solana_rpc.fetch_token_accounts_by_owner
    original_fetch_prices = jupiter.fetch_prices
    original_fetch_token_metadata = jupiter.fetch_token_metadata

    async def fake_fetch_balance(address, rpc_url, commitment="confirmed"):
        return {
            "address": address,
            "chain": "solana",
            "balance_native": 2.0,
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
                "pubkey": "FakeUsdcAta111111111111111111111111111111111",
                "account": {
                    "owner": TOKEN_PROGRAM_ID,
                    "data": {
                        "parsed": {
                            "info": {
                                "mint": USDC_MINT,
                                "owner": owner,
                                "tokenAmount": {
                                    "amount": "1500000",
                                    "uiAmount": 1.5,
                                    "decimals": 6,
                                },
                                "state": "initialized",
                            }
                        }
                    },
                },
            }
        ]

    async def fake_fetch_prices(*, mints, show_extra_info=False):
        assert NATIVE_SOL_MINT in mints
        assert USDC_MINT in mints
        return {
            NATIVE_SOL_MINT: {"usdPrice": 100},
            USDC_MINT: {"usdPrice": 1},
        }

    async def fake_fetch_token_metadata(*, mints):
        assert USDC_MINT in mints
        return {USDC_MINT: {"symbol": "USDC", "name": "USD Coin"}}

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
        overview = await backend.get_balance()
    finally:
        solana_rpc.fetch_balance = original_fetch_balance
        solana_rpc.fetch_token_accounts_by_owner = original_fetch_token_accounts
        jupiter.fetch_prices = original_fetch_prices
        jupiter.fetch_token_metadata = original_fetch_token_metadata

    assert overview["chain"] == "solana"
    assert overview["address"] == OWNER
    assert overview["balance_native"] == 2.0
    assert overview["balance_usd"] == "201.50"
    assert overview["native_value_usd"] == "200.00"
    assert overview["total_value_usd"] == "201.50"
    assert overview["token_count"] == 1
    assert overview["asset_count"] == 2
    assert overview["tokens"][0]["mint"] == USDC_MINT
    assert overview["tokens"][0]["value_usd"] == "1.50"
    assert overview["tokens"][0]["symbol"] == "USDC"
    assert overview["tokens"][0]["name"] == "USD Coin"
    assert overview["assets"][0]["value_usd"] == "200.00"
    assert overview["assets"][1]["value_usd"] == "1.50"
    assert overview["assets"][1]["symbol"] == "USDC"
    assert overview["token_discovery_source"] == "solana-rpc"
    assert overview["pricing_source"] == "jupiter-price"
    assert overview["token_metadata_source"] == "jupiter-token-search"

    print("solana wallet portfolio smoke ok")


if __name__ == "__main__":
    asyncio.run(main())
