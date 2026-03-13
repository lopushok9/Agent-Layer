"""Live Jupiter price API smoke test."""

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
    data = await backend.get_token_prices([NATIVE_SOL_MINT, USDC_MINT])
    assert data["count"] == 2
    assert len(data["prices"]) == 2
    assert all(item["raw"] is not None for item in data["prices"])

    print(
        json.dumps(
            {
                "count": data["count"],
                "prices": [
                    {
                        "mint": item["mint"],
                        "raw": item["raw"],
                    }
                    for item in data["prices"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
