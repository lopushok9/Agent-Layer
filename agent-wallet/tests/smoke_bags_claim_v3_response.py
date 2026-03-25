"""Smoke test for Bags v3 claim transaction response parsing."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import bags  # noqa: E402
from agent_wallet.wallet_layer.solana import (  # noqa: E402
    SolanaLocalKeypairSigner,
    SolanaWalletBackend,
)


async def main() -> None:
    signer = SolanaLocalKeypairSigner.from_secret_material(json.dumps([1] * 32))
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        signer=signer,
        address=signer.address,
        sign_only=True,
    )

    original_build_claim_transactions = bags.build_claim_transactions
    original_prepare_bags_transactions = backend._prepare_bags_transactions
    original_execute_prepared_bags_transactions = backend._execute_prepared_bags_transactions
    try:

        async def fake_build_claim_transactions(payload: dict[str, str]) -> list[dict[str, object]]:
            assert payload == {
                "feeClaimer": signer.address,
                "tokenMint": "So11111111111111111111111111111111111111112",
            }
            return [
                {
                    "tx": "claim-tx-1",
                    "blockhash": {
                        "blockhash": "blockhash-1",
                        "lastValidBlockHeight": 123,
                    },
                },
                {
                    "tx": "claim-tx-2",
                    "blockhash": {
                        "blockhash": "blockhash-2",
                        "lastValidBlockHeight": 456,
                    },
                },
            ]

        async def fake_prepare_bags_transactions(
            *,
            transaction_base64s: list[str],
            token_mint: str,
            action: str,
            owner: str,
            asset_type: str,
            extra: dict[str, object],
        ) -> dict[str, object]:
            assert transaction_base64s == ["claim-tx-1", "claim-tx-2"]
            assert token_mint == "So11111111111111111111111111111111111111112"
            assert action == "Bags fee claim"
            assert owner == signer.address
            assert asset_type == "bags-fee-claim"
            assert isinstance(extra["claim_response"], list)
            assert extra["claim_response"][0]["blockhash"]["blockhash"] == "blockhash-1"
            return {
                "chain": "solana",
                "network": "mainnet",
                "mode": "prepare",
                "asset_type": "bags-fee-claim",
                "owner": owner,
                "token_mint": token_mint,
                "transaction_count": len(transaction_base64s),
                "transactions_base64": transaction_base64s,
                "transaction_encoding": "base64",
                "transaction_format": "versioned",
                "signed": True,
                "broadcasted": False,
                "confirmed": False,
                "sign_only": True,
                "source": "bags",
                **extra,
            }

        async def fake_execute_prepared_bags_transactions(
            prepared: dict[str, object],
        ) -> dict[str, object]:
            assert prepared["transactions_base64"] == ["claim-tx-1", "claim-tx-2"]
            return {
                **prepared,
                "broadcasted": True,
                "confirmed": True,
                "signature": "fake-claim-signature",
                "signatures": ["fake-claim-signature"],
                "confirmation_statuses": ["confirmed", "confirmed"],
            }

        bags.build_claim_transactions = fake_build_claim_transactions
        backend._prepare_bags_transactions = fake_prepare_bags_transactions  # type: ignore[method-assign]
        backend._execute_prepared_bags_transactions = fake_execute_prepared_bags_transactions  # type: ignore[method-assign]

        preview = {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "bags-fee-claim",
            "owner": signer.address,
            "fee_claimer": signer.address,
            "token_mint": "So11111111111111111111111111111111111111112",
            "claimable_position_count": 1,
            "claimable_positions": [{"tokenMint": "So11111111111111111111111111111111111111112"}],
            "sign_only": True,
            "can_send": False,
            "source": "bags",
        }

        result = await backend.execute_bags_fee_claim_from_preview(preview)
        assert result["confirmed"] is True
        assert result["transaction_count"] == 2
        assert result["claimable_position_count"] == 1
        assert result["signatures"] == ["fake-claim-signature"]
    finally:
        bags.build_claim_transactions = original_build_claim_transactions
        backend._prepare_bags_transactions = original_prepare_bags_transactions  # type: ignore[method-assign]
        backend._execute_prepared_bags_transactions = original_execute_prepared_bags_transactions  # type: ignore[method-assign]

    print("smoke_bags_claim_v3_response: ok")


if __name__ == "__main__":
    asyncio.run(main())
