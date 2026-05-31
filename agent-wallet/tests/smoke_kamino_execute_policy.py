"""Smoke test for Kamino-specific transaction execution policy."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import solana_rpc  # noqa: E402
from agent_wallet.wallet_layer.solana import SolanaWalletBackend  # noqa: E402


async def main() -> None:
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        address="So11111111111111111111111111111111111111112",
        sign_only=False,
    )

    original_send_transaction = solana_rpc.send_transaction
    original_wait_for_confirmation = solana_rpc.wait_for_confirmation

    send_calls: list[dict] = []
    wait_calls: list[dict] = []

    async def fake_send_transaction(
        *,
        transaction_base64: str,
        rpc_url,
        skip_preflight: bool = False,
        max_retries=None,
    ):
        send_calls.append(
            {
                "transaction_base64": transaction_base64,
                "rpc_url": rpc_url,
                "skip_preflight": skip_preflight,
                "max_retries": max_retries,
            }
        )
        return {"signature": "FakeKaminoSig1111111111111111111111111111111111"}

    async def fake_wait_for_confirmation(
        *,
        signature: str,
        rpc_url,
        timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 1.0,
    ):
        wait_calls.append(
            {
                "signature": signature,
                "rpc_url": rpc_url,
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
            }
        )
        return {"confirmationStatus": "confirmed", "slot": 321}

    try:
        solana_rpc.send_transaction = fake_send_transaction
        solana_rpc.wait_for_confirmation = fake_wait_for_confirmation

        kamino_result = await backend._execute_prepared_provider_transaction(
            {
                "transaction_base64": "AQ==",
                "asset_type": "kamino-lend-deposit",
                "owner": backend.address,
                "amount_ui": "1.25",
                "simulation": {"logs": ["ok"]},
                "kamino_safety": {"verified": True},
            },
            source="kamino",
        )
        generic_result = await backend._execute_prepared_provider_transaction(
            {
                "transaction_base64": "AQ==",
                "asset_type": "bags-claim",
                "owner": backend.address,
            },
            source="bags",
        )
    finally:
        solana_rpc.send_transaction = original_send_transaction
        solana_rpc.wait_for_confirmation = original_wait_for_confirmation

    assert kamino_result["confirmed"] is True
    assert kamino_result["simulation"] == {"logs": ["ok"]}
    assert kamino_result["kamino_safety"] == {"verified": True}
    assert generic_result["confirmed"] is True
    assert send_calls[0]["skip_preflight"] is True
    assert send_calls[1]["skip_preflight"] is False
    assert wait_calls[0]["timeout_seconds"] == 60.0
    assert wait_calls[0]["poll_interval_seconds"] == 2.0
    assert wait_calls[1]["timeout_seconds"] == 20.0
    assert wait_calls[1]["poll_interval_seconds"] == 1.0

    print("smoke_kamino_execute_policy: ok")


if __name__ == "__main__":
    asyncio.run(main())
