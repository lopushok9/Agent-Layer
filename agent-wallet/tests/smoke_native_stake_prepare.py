"""Regression smoke test for native stake prepare path."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.wallet_layer.solana import SolanaLocalKeypairSigner, SolanaWalletBackend


async def main() -> None:
    signer = SolanaLocalKeypairSigner.from_secret_material(json.dumps([1] * 32))
    backend = SolanaWalletBackend(
        rpc_url="https://api.devnet.solana.com",
        network="devnet",
        signer=signer,
        address=signer.address,
        sign_only=False,
    )

    async def fake_preview_native_stake(vote_account: str, amount_native: float) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "preview",
            "asset_type": "native-stake",
            "owner": signer.address,
            "stake_account_address": None,
            "vote_account": vote_account,
            "validator": {"votePubkey": vote_account},
            "amount_native": amount_native,
            "stake_lamports": 10_000_000,
            "rent_exempt_lamports": 2_282_880,
            "rent_exempt_native": 0.00228288,
            "total_lamports": 12_282_880,
            "estimated_fee_lamports": 10_000,
            "estimated_fee_native": 0.00001,
            "balance_native_before": 5.0,
            "estimated_balance_native_after": 4.98770712,
            "latest_blockhash": "11111111111111111111111111111111",
            "last_valid_block_height": 123,
            "sign_only": False,
            "can_send": True,
            "source": "fake",
        }

    backend.preview_native_stake = fake_preview_native_stake  # type: ignore[method-assign]
    result = await backend.prepare_native_stake(
        vote_account="vgcDar2pryHvMgPkKaZfh8pQy4BJxv7SpwUG7zinWjG",
        amount_native=0.01,
    )
    assert result["mode"] == "prepare"
    assert result["transaction_format"] == "legacy"
    assert result["signed"] is True
    assert "transaction_base64" in result
    print("smoke_native_stake_prepare: ok")


if __name__ == "__main__":
    asyncio.run(main())
