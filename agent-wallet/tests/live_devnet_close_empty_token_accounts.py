"""Live devnet smoke for closing zero-balance token accounts."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solders.pubkey import Pubkey
from spl.token.instructions import get_associated_token_address

from agent_wallet.providers import solana_rpc
from agent_wallet.wallet_layer.solana import NATIVE_SOL_MINT, SolanaLocalKeypairSigner, SolanaWalletBackend


DEVNET_RPC = "https://api.devnet.solana.com"
DEFAULT_TEST_HOME = Path("/tmp/openclaw-devnet-test-2")


def _load_backend(wallet_path: Path) -> SolanaWalletBackend:
    signer = SolanaLocalKeypairSigner.from_secret_material(wallet_path.read_text())
    return SolanaWalletBackend(
        rpc_url=DEVNET_RPC,
        commitment="confirmed",
        network="devnet",
        signer=signer,
        sign_only=False,
    )


async def main() -> None:
    sender_backend = _load_backend(DEFAULT_TEST_HOME / "wallets" / "solana-devnet-agent.json")
    recipient_backend = _load_backend(DEFAULT_TEST_HOME / "wallets" / "live-recipient.json")

    sender_address = await sender_backend.get_address()
    recipient_address = await recipient_backend.get_address()
    if not sender_address or not recipient_address:
        raise RuntimeError("Missing sender or recipient devnet wallet address.")

    recipient_ata = str(
        get_associated_token_address(
            Pubkey.from_string(recipient_address),
            Pubkey.from_string(NATIVE_SOL_MINT),
            token_program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
        )
    )

    initial_exists = await solana_rpc.account_exists(recipient_ata, rpc_url=DEVNET_RPC)
    if not initial_exists:
        seeded = await sender_backend.send_spl_transfer(
            recipient=recipient_address,
            mint=NATIVE_SOL_MINT,
            amount_ui=0.005,
        )
        if not seeded["confirmed"]:
            raise RuntimeError("Failed to seed recipient with WSOL for close-account test.")
        for _ in range(10):
            if await solana_rpc.account_exists(recipient_ata, rpc_url=DEVNET_RPC):
                break
            await asyncio.sleep(1)

    recipient_balance = await solana_rpc.fetch_token_account_balance(recipient_ata, rpc_url=DEVNET_RPC)
    ui_amount = float(recipient_balance.get("ui_amount") or 0)
    if ui_amount > 0:
        drained = await recipient_backend.send_spl_transfer(
            recipient=sender_address,
            mint=NATIVE_SOL_MINT,
            amount_ui=ui_amount,
        )
        if not drained["confirmed"]:
            raise RuntimeError("Failed to drain recipient WSOL balance before close test.")

    preview = None
    for _ in range(10):
        preview = await recipient_backend.preview_close_empty_token_accounts(limit=4)
        candidate_accounts = [item["token_account"] for item in preview["accounts"]]
        if recipient_ata in candidate_accounts:
            break
        await asyncio.sleep(1)
    if preview is None:
        raise RuntimeError("Close preview was not produced.")
    candidate_accounts = [item["token_account"] for item in preview["accounts"]]
    if recipient_ata not in candidate_accounts:
        raise RuntimeError("Recipient WSOL token account was not offered as a close candidate.")

    closed = await recipient_backend.close_empty_token_accounts(limit=4)
    if not closed["confirmed"]:
        raise RuntimeError("Close empty token accounts transaction was not confirmed.")

    still_exists = True
    for _ in range(10):
        still_exists = await solana_rpc.account_exists(recipient_ata, rpc_url=DEVNET_RPC)
        if not still_exists:
            break
        await asyncio.sleep(1)
    if still_exists:
        raise RuntimeError("Recipient token account still exists after close transaction.")

    print(
        json.dumps(
            {
                "recipient_address": recipient_address,
                "closed_signature": closed["signature"],
                "closed_accounts": [item["token_account"] for item in closed["closed_accounts"]],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
