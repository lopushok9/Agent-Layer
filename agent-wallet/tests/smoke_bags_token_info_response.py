"""Smoke test for Bags token-info response normalization in the Solana backend."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.wallet_layer.solana import SolanaWalletBackend  # noqa: E402


def main() -> None:
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        address="So11111111111111111111111111111111111111112",
        sign_only=True,
    )

    launch_shape_payload = {
        "tokenMint": "mint-launch-123",
        "tokenMetadata": "ipfs://metadata-from-token-metadata",
        "tokenLaunch": {
            "uri": "ipfs://metadata-from-token-launch",
        },
    }
    token_mint, metadata_ref = backend._bags_extract_token_info_fields(launch_shape_payload)
    assert token_mint == "mint-launch-123"
    assert metadata_ref == "ipfs://metadata-from-token-launch"

    metadata_only_payload = {
        "tokenMint": "mint-metadata-456",
        "tokenMetadata": "ipfs://metadata-only",
    }
    token_mint, metadata_ref = backend._bags_extract_token_info_fields(metadata_only_payload)
    assert token_mint == "mint-metadata-456"
    assert metadata_ref == "ipfs://metadata-only"

    print("smoke_bags_token_info_response: ok")


if __name__ == "__main__":
    main()
