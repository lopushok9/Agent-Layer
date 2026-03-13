"""Live quote smoke for Jupiter-based swap preview."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.wallet_layer.solana import NATIVE_SOL_MINT, SolanaWalletBackend


USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def main() -> None:
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        commitment="confirmed",
        network="mainnet",
        signer=None,
        address=None,
        sign_only=True,
    )
    preview = await backend.preview_swap(
        input_mint=NATIVE_SOL_MINT,
        output_mint=USDC_MINT,
        amount_ui=0.01,
        slippage_bps=50,
    )
    assert preview["asset_type"] == "swap"
    assert preview["estimated_output_amount_ui"] > 0
    assert preview["source"] == "jupiter"

    print(
        json.dumps(
            {
                "input_mint": preview["input_mint"],
                "output_mint": preview["output_mint"],
                "estimated_output_amount_ui": preview["estimated_output_amount_ui"],
                "minimum_output_amount_ui": preview["minimum_output_amount_ui"],
                "slippage_bps": preview["slippage_bps"],
                "price_impact_pct": preview["price_impact_pct"],
                "route_hops": len(preview["route_plan"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
