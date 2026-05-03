"""Smoke test Solana swap routing across Jupiter and Bags providers."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.exceptions import ProviderError  # noqa: E402
from agent_wallet.providers import bags, jupiter  # noqa: E402
from agent_wallet.wallet_layer.solana import NATIVE_SOL_MINT, SolanaWalletBackend  # noqa: E402


BAGS_MINT = "444DPguaifQZ5NicFicD9Kni6emKexyqqG4dEkUaBAGS"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
OWNER = "ETaXGWqPtDrrwYZHwZjCwggBDf6VPHLDwcSMzibzy7Fz"


async def main() -> None:
    original_ultra = jupiter.fetch_ultra_order
    original_quote = jupiter.fetch_quote
    original_bags_quote = bags.fetch_trade_quote
    original_env = {"SOLANA_SWAP_PROVIDER": os.environ.get("SOLANA_SWAP_PROVIDER")}
    calls: list[str] = []

    async def fake_ultra(**kwargs):
        calls.append("jupiter-ultra")
        raise ProviderError("jupiter-ultra", "TOKEN_NOT_TRADABLE")

    async def fake_metis(**kwargs):
        calls.append("jupiter-metis")
        raise ProviderError("jupiter", "MARKET_NOT_FOUND")

    async def fake_bags_quote(**kwargs):
        calls.append("bags")
        return {
            "outAmount": "11109000000",
            "otherAmountThreshold": "10997000000",
            "slippageBps": int(kwargs["slippage_bps"]),
            "routePlan": [{"swapInfo": {"label": "bags-dynamic-bonding-curve"}}],
            "platformFee": {"feeBps": 100},
        }

    try:
        os.environ.pop("SOLANA_SWAP_PROVIDER", None)
        jupiter.fetch_ultra_order = fake_ultra
        jupiter.fetch_quote = fake_metis
        bags.fetch_trade_quote = fake_bags_quote

        backend = SolanaWalletBackend(
            rpc_url="https://api.mainnet-beta.solana.com",
            network="mainnet",
            address=OWNER,
            sign_only=True,
            swap_provider="jupiter",
        )

        async def fake_decimals(mint: str) -> int:
            return 9 if mint == NATIVE_SOL_MINT else 6

        backend._resolve_mint_decimals = fake_decimals  # type: ignore[method-assign]

        bags_preview = await backend.preview_swap(
            input_mint=NATIVE_SOL_MINT,
            output_mint=BAGS_MINT,
            amount_ui=0.003,
            slippage_bps=100,
        )
        assert bags_preview["swap_provider"] == "bags"
        assert calls == ["bags"]

        calls.clear()
        fallback_preview = await backend.preview_swap(
            input_mint=NATIVE_SOL_MINT,
            output_mint=USDC_MINT,
            amount_ui=0.003,
            slippage_bps=100,
        )
        assert fallback_preview["swap_provider"] == "bags"
        assert calls == ["jupiter-ultra", "jupiter-metis", "bags"]
    finally:
        jupiter.fetch_ultra_order = original_ultra
        jupiter.fetch_quote = original_quote
        bags.fetch_trade_quote = original_bags_quote
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("smoke_solana_swap_provider_routing: ok")


if __name__ == "__main__":
    asyncio.run(main())
