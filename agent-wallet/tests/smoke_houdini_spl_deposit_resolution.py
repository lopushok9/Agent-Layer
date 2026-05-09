"""Smoke test for Houdini SPL deposit readiness polling."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solders.pubkey import Pubkey  # noqa: E402
from spl.token.instructions import get_associated_token_address  # noqa: E402

from agent_wallet.providers import solana_rpc  # noqa: E402
from agent_wallet.wallet_layer.solana import SolanaLocalKeypairSigner, SolanaWalletBackend  # noqa: E402


TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def main() -> None:
    signer = SolanaLocalKeypairSigner(bytes(range(32)))
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        signer=signer,
        address=signer.address,
        sign_only=False,
    )

    sender_pubkey = Pubkey.from_string(signer.address)
    mint_pubkey = Pubkey.from_string(USDC_MINT)
    token_program_pubkey = Pubkey.from_string(TOKEN_PROGRAM_ID)
    sender_ata = str(
        get_associated_token_address(
            sender_pubkey,
            mint_pubkey,
            token_program_id=token_program_pubkey,
        )
    )
    deposit_address = "5G1kFNwzb5nvcTKDgGG6hUkk288eoirghMuoDVWmDoRB"

    original_resolve_token_program_id = backend._resolve_token_program_id
    original_account_exists = solana_rpc.account_exists
    original_fetch_account_info = solana_rpc.fetch_account_info
    original_fetch_token_account_balance = solana_rpc.fetch_token_account_balance
    original_fetch_latest_blockhash = solana_rpc.fetch_latest_blockhash
    original_send_transaction = solana_rpc.send_transaction
    original_wait_for_confirmation = solana_rpc.wait_for_confirmation
    original_sleep = asyncio.sleep

    info_calls = {"count": 0}
    sleep_calls: list[float] = []

    async def fake_resolve_token_program_id(mint: str) -> str:
        assert mint == USDC_MINT
        return TOKEN_PROGRAM_ID

    async def fake_account_exists(address: str, *, rpc_url):
        if address == sender_ata:
            return True
        raise AssertionError(f"Unexpected account_exists lookup: {address}")

    async def fake_fetch_account_info(address: str, *, rpc_url):
        info_calls["count"] += 1
        if address == deposit_address:
            if info_calls["count"] < 3:
                return None
            return {"data": {"parsed": {"info": {"mint": USDC_MINT}}}}
        raise AssertionError(f"Unexpected fetch_account_info lookup: {address}")

    async def fake_fetch_token_account_balance(address: str, *, rpc_url):
        assert address == sender_ata
        return {"amount": "50000000", "ui_amount": 50}

    async def fake_fetch_latest_blockhash(*, rpc_url, commitment):
        return {"blockhash": "11111111111111111111111111111111", "last_valid_block_height": 1}

    async def fake_send_transaction(*, transaction_base64: str, rpc_url):
        assert transaction_base64
        return {"signature": "FakeSig111111111111111111111111111111111111111111"}

    async def fake_wait_for_confirmation(*, signature: str, rpc_url):
        assert signature
        return {"confirmationStatus": "confirmed", "slot": 123}

    async def fake_sleep(delay: float):
        sleep_calls.append(delay)

    try:
        backend._resolve_token_program_id = fake_resolve_token_program_id
        solana_rpc.account_exists = fake_account_exists
        solana_rpc.fetch_account_info = fake_fetch_account_info
        solana_rpc.fetch_token_account_balance = fake_fetch_token_account_balance
        solana_rpc.fetch_latest_blockhash = fake_fetch_latest_blockhash
        solana_rpc.send_transaction = fake_send_transaction
        solana_rpc.wait_for_confirmation = fake_wait_for_confirmation
        asyncio.sleep = fake_sleep

        result = await backend._send_houdini_exact_spl_deposit(
            recipient_token_account=deposit_address,
            mint=USDC_MINT,
            amount_raw=30_000_000,
            decimals=6,
        )
    finally:
        backend._resolve_token_program_id = original_resolve_token_program_id
        solana_rpc.account_exists = original_account_exists
        solana_rpc.fetch_account_info = original_fetch_account_info
        solana_rpc.fetch_token_account_balance = original_fetch_token_account_balance
        solana_rpc.fetch_latest_blockhash = original_fetch_latest_blockhash
        solana_rpc.send_transaction = original_send_transaction
        solana_rpc.wait_for_confirmation = original_wait_for_confirmation
        asyncio.sleep = original_sleep

    assert result["requested_deposit_address"] == deposit_address
    assert result["deposit_address_interpretation"] == "token_account"
    assert result["recipient_token_account"] == deposit_address
    assert result["recipient_token_account_created"] is False
    assert result["confirmed"] is True
    assert info_calls["count"] == 3
    assert sleep_calls == [2.0, 2.0]

    print("smoke_houdini_spl_deposit_resolution: ok")


if __name__ == "__main__":
    asyncio.run(main())
