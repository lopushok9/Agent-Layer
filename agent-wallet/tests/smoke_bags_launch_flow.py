"""Smoke coverage for Bags launch config execution."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import bags  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402
from agent_wallet.wallet_layer.base58 import b58encode  # noqa: E402
from agent_wallet.wallet_layer.solana import (  # noqa: E402
    NATIVE_SOL_MINT,
    SolanaLocalKeypairSigner,
    SolanaWalletBackend,
)


async def main() -> None:
    original_env = {
        "PROVIDER_GATEWAY_URL": os.environ.get("PROVIDER_GATEWAY_URL"),
        "PROVIDER_GATEWAY_BEARER_TOKEN": os.environ.get("PROVIDER_GATEWAY_BEARER_TOKEN"),
    }
    original_create_token_info = bags.create_token_info
    original_create_fee_share_config = bags.create_fee_share_config
    original_create_launch_transaction = bags.create_launch_transaction

    signer = SolanaLocalKeypairSigner(bytes(range(32)))
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        signer=signer,
        address=signer.address,
        sign_only=False,
    )

    calls: list[tuple[str, object]] = []

    async def fake_create_token_info(payload: dict[str, object]) -> dict[str, object]:
        calls.append(("token-info", payload))
        return {
            "tokenMint": "mint-123",
            "tokenMetadata": {"uri": "ipfs://metadata.json"},
            "tokenLaunch": {"uri": "ipfs://metadata.json"},
        }

    async def fake_create_fee_share_config(payload: dict[str, object]) -> dict[str, object]:
        calls.append(("fee-share-config", payload))
        assert payload["baseMint"] == "mint-123"
        assert signer.address in payload["claimersArray"]
        return {
            "needsCreation": True,
            "feeShareAuthority": signer.address,
            "meteoraConfigKey": "cfg",
            "transactions": [
                {
                    "blockhash": {"blockhash": "blockhash-a", "lastValidBlockHeight": 123},
                    "transaction": "fee-share-create-tx",
                }
            ],
            "bundles": [
                [
                    {
                        "blockhash": {"blockhash": "blockhash-b", "lastValidBlockHeight": 456},
                        "transaction": "fee-share-bundle-tx",
                    }
                ]
            ],
        }

    async def fake_create_launch_transaction(payload: dict[str, object]) -> str:
        calls.append(("launch-transaction", payload))
        return "launch-tx"

    async def fake_prepare(
        *,
        transaction_base64s: list[str],
        token_mint: str,
        action: str,
        owner: str,
        asset_type: str,
        extra: dict[str, object],
    ) -> dict[str, object]:
        calls.append((f"prepare:{action}", list(transaction_base64s)))
        return {
            "chain": "solana",
            "network": backend.network,
            "mode": "prepare",
            "asset_type": asset_type,
            "owner": owner,
            "token_mint": token_mint,
            "transaction_count": len(transaction_base64s),
            "transactions_base64": [f"signed:{item}" for item in transaction_base64s],
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "verification": None,
            "verifications": [],
            "sign_only": False,
            "source": "bags",
            **extra,
        }

    async def fake_execute(prepared: dict[str, object]) -> dict[str, object]:
        calls.append((f"execute:{prepared['asset_type']}", list(prepared["transactions_base64"])))
        return {
            "chain": "solana",
            "network": backend.network,
            "mode": "execute",
            "asset_type": prepared["asset_type"],
            "owner": prepared["owner"],
            "token_mint": prepared["token_mint"],
            "transaction_count": prepared["transaction_count"],
            "signature": f"sig:{prepared['asset_type']}",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_statuses": ["confirmed"],
            "slots": [123],
            "sign_only": False,
            "source": "bags",
        }

    try:
        os.environ["PROVIDER_GATEWAY_URL"] = "https://gateway.example"
        os.environ["PROVIDER_GATEWAY_BEARER_TOKEN"] = "gateway-token"
        bags.create_token_info = fake_create_token_info
        bags.create_fee_share_config = fake_create_fee_share_config
        bags.create_launch_transaction = fake_create_launch_transaction
        backend._prepare_bags_transactions = fake_prepare  # type: ignore[method-assign]
        backend._execute_prepared_bags_transactions = fake_execute  # type: ignore[method-assign]

        decoded = backend._bags_decode_serialized_transaction_bytes(
            b58encode(b"bags-launch-serialized-bytes")
        )
        assert decoded == b"bags-launch-serialized-bytes"
        assert (
            backend._bags_decode_serialized_transaction_bytes(
                base64.b64encode(b"bags-launch-serialized-bytes").decode()
            )
            == b"bags-launch-serialized-bytes"
        )

        preview = await backend.preview_bags_token_launch(
            name="OpenClaw",
            symbol="CLAW",
            description="Launch test token",
            base_mint=NATIVE_SOL_MINT,
            claimers=[signer.address],
            basis_points=[10000],
            initial_buy_sol=0.01,
        )
        result = await backend.execute_bags_token_launch_from_preview(preview)

        assert result["confirmed"] is True
        assert result["fee_share_execution"]["asset_type"] == "bags-fee-share-config"
        assert result["launch_transaction_response"] == "launch-tx"

        assert calls[0][0] == "token-info"
        assert calls[1][0] == "fee-share-config"
        assert calls[2] == ("prepare:Bags fee share config", ["fee-share-create-tx", "fee-share-bundle-tx"])
        assert calls[3][0] == "execute:bags-fee-share-config"
        assert calls[4][0] == "launch-transaction"
        assert calls[5] == ("prepare:Bags token launch", ["launch-tx"])
        assert calls[6][0] == "execute:bags-token-launch"

        too_many_claimers_preview = await backend.preview_bags_token_launch(
            name="OpenClaw",
            symbol="CLAW",
            description="Launch test token",
            base_mint=NATIVE_SOL_MINT,
            claimers=[signer.address] * 8,
            basis_points=[1250] * 8,
            initial_buy_sol=0.01,
        )
        try:
            await backend.execute_bags_token_launch_from_preview(too_many_claimers_preview)
            raise AssertionError("Expected LUT guard to reject launches with more than 7 claimers")
        except WalletBackendError as exc:
            assert "lookup table" in str(exc).lower()

        try:
            await backend.preview_bags_token_launch(
                name="OpenClaw",
                symbol="CLAW",
                description="Launch test token",
                base_mint=NATIVE_SOL_MINT,
                claimers=["9xQeWvG816bUx9EPfEZq7m1a6jAqJ1i8LojRxurxP9d"],
                basis_points=[10000],
                initial_buy_sol=0.01,
            )
            raise AssertionError("Expected creator-in-claimers validation to fail")
        except WalletBackendError as exc:
            assert "connected wallet" in str(exc).lower()

        print("smoke_bags_launch_flow: ok")
    finally:
        bags.create_token_info = original_create_token_info
        bags.create_fee_share_config = original_create_fee_share_config
        bags.create_launch_transaction = original_create_launch_transaction
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    asyncio.run(main())
