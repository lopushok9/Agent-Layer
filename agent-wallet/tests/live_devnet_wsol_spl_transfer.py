"""Live devnet smoke for SPL transfer using wrapped SOL."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from spl.token.instructions import (
    SyncNativeParams,
    create_associated_token_account,
    get_associated_token_address,
    sync_native,
)

from agent_wallet.providers import solana_rpc
from agent_wallet.solana_tx import encode_transaction_base64
from agent_wallet.wallet_layer.solana import SolanaLocalKeypairSigner, SolanaWalletBackend


WSOL_MINT = "So11111111111111111111111111111111111111112"
DEVNET_RPC = "https://api.devnet.solana.com"
DEFAULT_TEST_HOME = Path("/tmp/openclaw-devnet-test-2")


def _load_keypair(path: Path) -> Keypair:
    values = json.loads(path.read_text())
    return Keypair.from_bytes(bytes(values))


async def _wrap_sol(
    sender_keypair: Keypair,
    sender_address: str,
    amount_sol: float,
) -> dict[str, object]:
    sender_pubkey = Pubkey.from_string(sender_address)
    mint_pubkey = Pubkey.from_string(WSOL_MINT)
    sender_ata = get_associated_token_address(sender_pubkey, mint_pubkey)

    instructions = []
    if not await solana_rpc.account_exists(str(sender_ata), rpc_url=DEVNET_RPC):
        instructions.append(
            create_associated_token_account(
                payer=sender_pubkey,
                owner=sender_pubkey,
                mint=mint_pubkey,
            )
        )

    lamports = int(round(amount_sol * solana_rpc.LAMPORTS_PER_SOL))
    instructions.append(
        transfer(
            TransferParams(
                from_pubkey=sender_pubkey,
                to_pubkey=sender_ata,
                lamports=lamports,
            )
        )
    )
    instructions.append(
        sync_native(
            SyncNativeParams(
                program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
                account=sender_ata,
            )
        )
    )

    latest_blockhash = await solana_rpc.fetch_latest_blockhash(
        rpc_url=DEVNET_RPC,
        commitment="confirmed",
    )
    blockhash = Hash.from_string(str(latest_blockhash["blockhash"]))
    message = Message.new_with_blockhash(instructions, sender_pubkey, blockhash)
    transaction = Transaction([sender_keypair], message, blockhash)

    submitted = await solana_rpc.send_transaction(
        transaction_base64=encode_transaction_base64(bytes(transaction)),
        rpc_url=DEVNET_RPC,
    )
    signature = submitted.get("signature")
    if not isinstance(signature, str) or not signature:
        raise RuntimeError("WSOL wrap transaction was not accepted by RPC.")

    status = await solana_rpc.wait_for_confirmation(signature=signature, rpc_url=DEVNET_RPC)
    if status is None:
        raise RuntimeError("WSOL wrap transaction was not confirmed in time.")

    return {
        "signature": signature,
        "sender_token_account": str(sender_ata),
        "wrapped_amount_sol": amount_sol,
    }


async def _wait_for_owner_token_balance(
    owner_address: str,
    token_account: str,
    minimum_ui_amount: float,
) -> dict[str, object]:
    for _ in range(20):
        accounts = await solana_rpc.fetch_token_accounts_by_owner(
            owner=owner_address,
            rpc_url=DEVNET_RPC,
        )
        for entry in accounts:
            if str(entry.get("pubkey") or "") != token_account:
                continue
            parsed = (((entry.get("account") or {}).get("data") or {}).get("parsed") or {})
            info = parsed.get("info") or {}
            token_amount = info.get("tokenAmount") or {}
            ui_amount = token_amount.get("uiAmount")
            if ui_amount is not None and float(ui_amount) >= minimum_ui_amount:
                return {
                    "amount": token_amount.get("amount"),
                    "decimals": token_amount.get("decimals"),
                    "ui_amount": ui_amount,
                    "source": "getTokenAccountsByOwner",
                }
        await asyncio.sleep(1)
    raise RuntimeError("Recipient token account balance did not update as expected.")


async def main() -> None:
    test_home = Path(os.environ.get("OPENCLAW_TEST_HOME", str(DEFAULT_TEST_HOME)))
    sender_path = test_home / "wallets" / "solana-devnet-agent.json"
    recipient_path = test_home / "wallets" / "live-recipient.json"

    if not sender_path.exists() or not recipient_path.exists():
        raise RuntimeError(
            "Missing devnet test keypairs. Expected sender and recipient wallets under "
            f"{test_home / 'wallets'}."
        )

    signer = SolanaLocalKeypairSigner.from_secret_material(sender_path.read_text())
    backend = SolanaWalletBackend(
        rpc_url=DEVNET_RPC,
        commitment="confirmed",
        network="devnet",
        signer=signer,
        sign_only=False,
    )

    sender_keypair = _load_keypair(sender_path)
    recipient_keypair = _load_keypair(recipient_path)
    sender_address = signer.address
    recipient_address = str(recipient_keypair.pubkey())
    recipient_ata = str(
        get_associated_token_address(
            recipient_keypair.pubkey(),
            Pubkey.from_string(WSOL_MINT),
        )
    )
    recipient_accounts_before = await solana_rpc.fetch_token_accounts_by_owner(
        recipient_address,
        rpc_url=DEVNET_RPC,
    )
    recipient_ui_before = 0.0
    for entry in recipient_accounts_before:
        if str(entry.get("pubkey") or "") != recipient_ata:
            continue
        parsed = (((entry.get("account") or {}).get("data") or {}).get("parsed") or {})
        info = parsed.get("info") or {}
        token_amount = info.get("tokenAmount") or {}
        recipient_ui_before = float(token_amount.get("uiAmount") or 0)
        break

    wrap_result = await _wrap_sol(
        sender_keypair=sender_keypair,
        sender_address=sender_address,
        amount_sol=0.03,
    )

    preview = await backend.preview_spl_transfer(
        recipient=recipient_address,
        mint=WSOL_MINT,
        amount_ui=0.005,
    )
    assert preview["asset_type"] == "spl"

    sent = await backend.send_spl_transfer(
        recipient=recipient_address,
        mint=WSOL_MINT,
        amount_ui=0.005,
    )
    assert sent["confirmed"] is True

    recipient_balance = await _wait_for_owner_token_balance(
        owner_address=recipient_address,
        token_account=recipient_ata,
        minimum_ui_amount=recipient_ui_before + 0.005,
    )
    ui_amount = recipient_balance.get("ui_amount")

    print(
        json.dumps(
            {
                "wrap_signature": wrap_result["signature"],
                "transfer_signature": sent["signature"],
                "sender_address": sender_address,
                "recipient_address": recipient_address,
                "recipient_token_account": recipient_ata,
                "recipient_ui_amount": ui_amount,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
