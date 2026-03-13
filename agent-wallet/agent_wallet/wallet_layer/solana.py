"""Solana wallet backend focused on simple local or read-only operation."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from agent_wallet.models import AgentWalletCapabilities, SolanaWalletState
from agent_wallet.providers import jupiter, solana_rpc
from agent_wallet.solana_tx import (
    build_legacy_sol_transfer_message,
    encode_transaction_base64,
    serialize_legacy_transaction,
)
from agent_wallet.validation import validate_solana_address, validate_solana_mint
from agent_wallet.wallet_layer.base import (
    AgentWalletBackend,
    WalletBackendError,
    WalletCapabilities,
)
from agent_wallet.wallet_layer.base58 import b58decode, b58encode

SOLANA_BASE_FEE_LAMPORTS = 5_000
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"


def _load_signing_key():
    try:
        from nacl.signing import SigningKey
    except ImportError as exc:
        raise WalletBackendError(
            "PyNaCl is required for local Solana signing. Install agent-wallet dependencies first."
        ) from exc
    return SigningKey


def _decode_secret_material(secret_material: str) -> bytes:
    cleaned = secret_material.strip()
    if not cleaned:
        raise WalletBackendError("Solana secret material is empty.")

    if cleaned.startswith("["):
        try:
            values = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise WalletBackendError("Solana keypair JSON could not be parsed.") from exc
        if not isinstance(values, list) or not values:
            raise WalletBackendError("Solana keypair JSON must be a non-empty integer array.")
        try:
            raw = bytes(int(item) for item in values)
        except ValueError as exc:
            raise WalletBackendError("Solana keypair JSON must contain byte values.") from exc
        return raw

    try:
        return b58decode(cleaned)
    except ValueError as exc:
        raise WalletBackendError("Solana secret must be base58 or JSON keypair bytes.") from exc


class SolanaLocalKeypairSigner:
    """Local signer compatible with agent-style wallet backends."""

    def __init__(self, seed: bytes):
        SigningKey = _load_signing_key()
        self._signing_key = SigningKey(seed)
        self._public_key = b58encode(bytes(self._signing_key.verify_key))

    @classmethod
    def from_secret_material(cls, secret_material: str) -> "SolanaLocalKeypairSigner":
        raw = _decode_secret_material(secret_material)
        if len(raw) == 64:
            seed = raw[:32]
        elif len(raw) == 32:
            seed = raw
        else:
            raise WalletBackendError(
                "Unsupported Solana secret length. Expected 32-byte seed or 64-byte keypair."
            )
        return cls(seed)

    @property
    def address(self) -> str:
        return self._public_key

    def export_keypair_bytes(self) -> bytes:
        """Return 64-byte Solana keypair bytes in Solana CLI file format."""
        return self._signing_key.encode() + bytes(self._signing_key.verify_key)

    def sign_message(self, message: bytes) -> bytes:
        signed = self._signing_key.sign(message)
        return bytes(signed.signature)

    def sign_bytes(self, payload: bytes) -> bytes:
        signed = self._signing_key.sign(payload)
        return bytes(signed.signature)


class SolanaWalletBackend(AgentWalletBackend):
    """Minimal Solana wallet backend for plugin-style integration."""

    name = "solana_local"

    def __init__(
        self,
        rpc_url: str,
        commitment: str = "confirmed",
        network: str = "mainnet",
        signer: SolanaLocalKeypairSigner | None = None,
        address: str | None = None,
        sign_only: bool = True,
    ):
        derived_address = signer.address if signer else None
        final_address = address or derived_address
        if final_address:
            final_address = validate_solana_address(final_address)
        if derived_address and final_address and derived_address != final_address:
            raise WalletBackendError(
                "Configured Solana public key does not match the private key provided for signing."
            )

        self.rpc_url = rpc_url
        self.commitment = commitment
        self.network = network
        self.signer = signer
        self.address = final_address
        self.sign_only = sign_only

    async def get_address(self) -> str | None:
        return self.address

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain="solana",
            custody_model="local" if self.signer else "read_only",
            sign_only=self.sign_only,
            has_signer=self.signer is not None,
            can_sign_message=self.signer is not None,
            can_sign_transaction=self.signer is not None,
            can_send_transaction=self.signer is not None and not self.sign_only,
            external_dependencies=["solana-rpc", "pynacl" if self.signer else "solana-rpc"],
        )

    async def get_balance(self, address: str | None = None) -> dict[str, Any]:
        wallet_address = address or self.address
        if not wallet_address:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        return await solana_rpc.fetch_balance(
            validate_solana_address(wallet_address),
            rpc_url=self.rpc_url,
            commitment=self.commitment,
        )

    async def get_portfolio(self, address: str | None = None) -> dict[str, Any]:
        wallet_address = address or self.address
        if not wallet_address:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        wallet_address = validate_solana_address(wallet_address)
        native_balance, tokens = await asyncio.gather(
            self.get_balance(wallet_address),
            self._fetch_token_entries(wallet_address, include_zero_balances=False),
        )
        tokens.sort(
            key=lambda item: float(item.get("amount_ui") or 0),
            reverse=True,
        )
        return {
            "chain": "solana",
            "network": self.network,
            "address": wallet_address,
            "native_balance": native_balance,
            "tokens": tokens,
            "token_count": len(tokens),
            "source": "solana-rpc",
        }

    async def get_token_prices(self, mints: list[str]) -> dict[str, Any]:
        if not mints:
            raise WalletBackendError("At least one mint is required.")
        normalized: list[str] = []
        for mint in mints:
            if not isinstance(mint, str) or not mint.strip():
                raise WalletBackendError("Each mint must be a non-empty string.")
            normalized.append(validate_solana_mint(mint.strip()))

        unique_mints = list(dict.fromkeys(normalized))
        if len(unique_mints) > 20:
            raise WalletBackendError("At most 20 mints can be requested at once.")

        price_data = await jupiter.fetch_prices(mints=unique_mints)
        items: list[dict[str, Any]] = []
        for mint in unique_mints:
            entry = price_data.get(mint)
            items.append(
                {
                    "mint": mint,
                    "price": entry.get("usdPrice") if isinstance(entry, dict) else None,
                    "raw": entry,
                }
            )

        return {
            "chain": "solana",
            "network": "mainnet",
            "requested_mints": unique_mints,
            "count": len(items),
            "prices": items,
            "source": "jupiter",
        }

    async def get_state(self) -> SolanaWalletState:
        balance_native = None
        if self.address:
            balance = await self.get_balance(self.address)
            balance_native = balance["balance_native"]

        return SolanaWalletState(
            chain="solana",
            backend=self.name,
            address=self.address,
            balance_native=balance_native,
            sign_only=self.sign_only,
            has_signer=self.signer is not None,
        )

    async def describe(self) -> AgentWalletCapabilities:
        return AgentWalletCapabilities(**self.get_capabilities().to_dict())

    async def sign_message(self, message: bytes | str) -> str:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        payload = message.encode("utf-8") if isinstance(message, str) else message
        return b58encode(self.signer.sign_message(payload))

    async def preview_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict[str, Any]:
        sender = await self.get_address()
        if not sender:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if amount_native <= 0:
            raise WalletBackendError("amount must be greater than zero.")

        recipient = validate_solana_address(recipient)
        balance = await self.get_balance(sender)
        latest_blockhash = await solana_rpc.fetch_latest_blockhash(
            rpc_url=self.rpc_url,
            commitment=self.commitment,
        )

        amount_lamports = int(round(amount_native * solana_rpc.LAMPORTS_PER_SOL))
        estimated_fee_lamports = SOLANA_BASE_FEE_LAMPORTS
        total_lamports = amount_lamports + estimated_fee_lamports
        available_lamports = int(round(balance["balance_native"] * solana_rpc.LAMPORTS_PER_SOL))
        if total_lamports > available_lamports:
            raise WalletBackendError(
                "Insufficient SOL balance for this transfer preview, including estimated fees."
            )

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "from_address": sender,
            "to_address": recipient,
            "amount_native": amount_native,
            "amount_lamports": amount_lamports,
            "estimated_fee_native": estimated_fee_lamports / solana_rpc.LAMPORTS_PER_SOL,
            "estimated_fee_lamports": estimated_fee_lamports,
            "balance_native_before": balance["balance_native"],
            "estimated_balance_native_after": (
                (available_lamports - total_lamports) / solana_rpc.LAMPORTS_PER_SOL
            ),
            "latest_blockhash": latest_blockhash["blockhash"],
            "last_valid_block_height": latest_blockhash["last_valid_block_height"],
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "solana-rpc",
        }

    async def send_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict[str, Any]:
        prepared = await self.prepare_native_transfer(
            recipient=recipient,
            amount_native=amount_native,
        )
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )

        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_url,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_url,
            )
            confirmed = status is not None

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "from_address": prepared["from_address"],
            "to_address": prepared["to_address"],
            "amount_native": prepared["amount_native"],
            "amount_lamports": prepared["amount_lamports"],
            "estimated_fee_native": prepared["estimated_fee_native"],
            "signature": signature,
            "broadcasted": bool(signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def prepare_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")

        preview = await self.preview_native_transfer(
            recipient=recipient,
            amount_native=amount_native,
        )
        lamports = int(preview["amount_lamports"])
        blockhash = str(preview["latest_blockhash"])
        sender = str(preview["from_address"])
        recipient = str(preview["to_address"])

        message = build_legacy_sol_transfer_message(
            sender=sender,
            recipient=recipient,
            recent_blockhash=blockhash,
            lamports=lamports,
        )
        signature_bytes = self.signer.sign_bytes(message)
        transaction_bytes = serialize_legacy_transaction(signature_bytes, message)
        transaction_base64 = encode_transaction_base64(transaction_bytes)

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "from_address": sender,
            "to_address": recipient,
            "amount_native": amount_native,
            "amount_lamports": lamports,
            "estimated_fee_native": preview["estimated_fee_native"],
            "transaction_base64": transaction_base64,
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": blockhash,
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def request_testnet_airdrop(self, amount_native: float) -> dict[str, Any]:
        if self.network not in {"devnet", "testnet"}:
            raise WalletBackendError("Airdrop is only available on Solana devnet or testnet.")
        if amount_native <= 0:
            raise WalletBackendError("amount must be greater than zero.")

        address = await self.get_address()
        if not address:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )

        lamports = int(round(amount_native * solana_rpc.LAMPORTS_PER_SOL))
        submitted = await solana_rpc.request_airdrop(
            address=address,
            lamports=lamports,
            rpc_url=self.rpc_url,
            commitment=self.commitment,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_url,
            )
            confirmed = status is not None

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "airdrop",
            "address": address,
            "amount_native": amount_native,
            "amount_lamports": lamports,
            "signature": signature,
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "source": "solana-rpc",
        }

    async def _resolve_mint_decimals(self, mint: str) -> int:
        if mint == NATIVE_SOL_MINT:
            return 9
        token_info = await solana_rpc.fetch_token_supply_info(mint, rpc_url=self.rpc_url)
        return int(token_info.get("decimals") or 0)

    async def _resolve_token_program_id(self, mint: str) -> str:
        if mint == NATIVE_SOL_MINT:
            return TOKEN_PROGRAM_ID
        account_info = await solana_rpc.fetch_account_info(mint, rpc_url=self.rpc_url)
        if account_info is None:
            raise WalletBackendError("Mint account was not found on Solana RPC.")
        owner = account_info.get("owner")
        if owner not in {TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID}:
            raise WalletBackendError(
                "Unsupported token program for this mint. Only SPL Token and Token-2022 are supported."
            )
        return str(owner)

    async def _fetch_token_entries(
        self,
        owner: str,
        include_zero_balances: bool,
    ) -> list[dict[str, Any]]:
        token_accounts_legacy, token_accounts_2022 = await asyncio.gather(
            solana_rpc.fetch_token_accounts_by_owner(
                owner,
                rpc_url=self.rpc_url,
                token_program_id=TOKEN_PROGRAM_ID,
            ),
            solana_rpc.fetch_token_accounts_by_owner(
                owner,
                rpc_url=self.rpc_url,
                token_program_id=TOKEN_2022_PROGRAM_ID,
            ),
        )
        token_accounts = token_accounts_legacy + token_accounts_2022

        tokens: list[dict[str, Any]] = []
        for item in token_accounts:
            pubkey = item.get("pubkey")
            parsed = (
                item.get("account", {})
                .get("data", {})
                .get("parsed", {})
                .get("info", {})
            )
            token_amount = parsed.get("tokenAmount", {})
            ui_amount = token_amount.get("uiAmount")
            raw_amount = str(token_amount.get("amount") or "0")
            if not include_zero_balances and ui_amount in (None, 0, 0.0) and raw_amount == "0":
                continue
            tokens.append(
                {
                    "mint": parsed.get("mint"),
                    "token_account": pubkey,
                    "token_program_id": item.get("account", {}).get("owner"),
                    "owner": parsed.get("owner"),
                    "close_authority": parsed.get("closeAuthority"),
                    "amount_raw": raw_amount,
                    "amount_ui": ui_amount,
                    "decimals": token_amount.get("decimals"),
                    "is_native": bool(parsed.get("isNative", False)),
                    "state": parsed.get("state"),
                }
            )
        return tokens

    async def _list_empty_closeable_token_accounts(self, owner: str) -> list[dict[str, Any]]:
        portfolio_tokens = await self._fetch_token_entries(owner, include_zero_balances=True)
        candidates: list[dict[str, Any]] = []
        for token in portfolio_tokens:
            raw_amount = str(token.get("amount_raw") or "0")
            close_authority = token.get("close_authority")
            if raw_amount != "0":
                continue
            if close_authority and close_authority != owner:
                continue
            candidates.append(token)
        return candidates

    async def preview_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict[str, Any]:
        sender = await self.get_address()
        if not sender:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if amount_ui <= 0:
            raise WalletBackendError("amount must be greater than zero.")

        recipient = validate_solana_address(recipient)
        mint = validate_solana_mint(mint)

        try:
            from solders.pubkey import Pubkey
            from spl.token.instructions import get_associated_token_address
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for SPL token transfers."
            ) from exc

        sender_pubkey = Pubkey.from_string(sender)
        recipient_pubkey = Pubkey.from_string(recipient)
        mint_pubkey = Pubkey.from_string(mint)
        token_program_id = await self._resolve_token_program_id(mint)
        token_program_pubkey = Pubkey.from_string(token_program_id)
        sender_ata = str(
            get_associated_token_address(
                sender_pubkey,
                mint_pubkey,
                token_program_id=token_program_pubkey,
            )
        )
        recipient_ata = str(
            get_associated_token_address(
                recipient_pubkey,
                mint_pubkey,
                token_program_id=token_program_pubkey,
            )
        )

        sender_ata_exists = await solana_rpc.account_exists(sender_ata, rpc_url=self.rpc_url)
        if not sender_ata_exists:
            raise WalletBackendError("Sender token account does not exist for this mint.")

        token_info = await solana_rpc.fetch_token_supply_info(mint, rpc_url=self.rpc_url)
        resolved_decimals = int(
            decimals if decimals is not None else (token_info.get("decimals") or 0)
        )
        raw_amount = int(round(amount_ui * (10**resolved_decimals)))
        if raw_amount <= 0:
            raise WalletBackendError("amount is too small for the token decimals.")

        sender_balance = await solana_rpc.fetch_token_account_balance(
            sender_ata,
            rpc_url=self.rpc_url,
        )
        sender_raw_balance = int(sender_balance.get("amount") or 0)
        if raw_amount > sender_raw_balance:
            raise WalletBackendError("Insufficient token balance for this transfer preview.")

        recipient_ata_exists = await solana_rpc.account_exists(recipient_ata, rpc_url=self.rpc_url)
        latest_blockhash = await solana_rpc.fetch_latest_blockhash(
            rpc_url=self.rpc_url,
            commitment=self.commitment,
        )

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "spl",
            "from_address": sender,
            "to_address": recipient,
            "mint": mint,
            "token_program_id": token_program_id,
            "sender_token_account": sender_ata,
            "recipient_token_account": recipient_ata,
            "recipient_token_account_exists": recipient_ata_exists,
            "amount_ui": amount_ui,
            "amount_raw": raw_amount,
            "decimals": resolved_decimals,
            "sender_balance_ui_before": sender_balance.get("ui_amount"),
            "sender_balance_raw_before": sender_raw_balance,
            "estimated_sender_balance_raw_after": sender_raw_balance - raw_amount,
            "latest_blockhash": latest_blockhash["blockhash"],
            "last_valid_block_height": latest_blockhash["last_valid_block_height"],
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "solana-rpc",
        }

    async def send_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_spl_transfer(
            recipient=recipient,
            mint=mint,
            amount_ui=amount_ui,
            decimals=decimals,
        )
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )

        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_url,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_url,
            )
            confirmed = status is not None

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": "spl",
            "from_address": prepared["from_address"],
            "to_address": prepared["to_address"],
            "mint": prepared["mint"],
            "token_program_id": prepared["token_program_id"],
            "sender_token_account": prepared["sender_token_account"],
            "recipient_token_account": prepared["recipient_token_account"],
            "recipient_token_account_exists_before": prepared[
                "recipient_token_account_exists_before"
            ],
            "recipient_token_account_created": prepared["recipient_token_account_created"],
            "amount_ui": prepared["amount_ui"],
            "amount_raw": prepared["amount_raw"],
            "decimals": prepared["decimals"],
            "signature": signature,
            "broadcasted": bool(signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def prepare_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")

        preview = await self.preview_spl_transfer(
            recipient=recipient,
            mint=mint,
            amount_ui=amount_ui,
            decimals=decimals,
        )

        try:
            from solders.hash import Hash
            from solders.instruction import Instruction
            from solders.keypair import Keypair
            from solders.message import Message
            from solders.pubkey import Pubkey
            from solders.transaction import Transaction
            from spl.token.instructions import (
                TransferCheckedParams,
                create_associated_token_account,
                transfer_checked,
            )
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for SPL token transfers."
            ) from exc

        sender = str(preview["from_address"])
        recipient = str(preview["to_address"])
        mint = str(preview["mint"])
        token_program_id = str(preview["token_program_id"])
        sender_ata = str(preview["sender_token_account"])
        recipient_ata = str(preview["recipient_token_account"])
        raw_amount = int(preview["amount_raw"])
        resolved_decimals = int(preview["decimals"])

        sender_pubkey = Pubkey.from_string(sender)
        recipient_pubkey = Pubkey.from_string(recipient)
        mint_pubkey = Pubkey.from_string(mint)
        token_program_pubkey = Pubkey.from_string(token_program_id)
        sender_ata_pubkey = Pubkey.from_string(sender_ata)
        recipient_ata_pubkey = Pubkey.from_string(recipient_ata)
        keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())

        instructions: list[Instruction] = []
        if not bool(preview["recipient_token_account_exists"]):
            instructions.append(
                create_associated_token_account(
                    payer=sender_pubkey,
                    owner=recipient_pubkey,
                    mint=mint_pubkey,
                    token_program_id=token_program_pubkey,
                )
            )

        instructions.append(
            transfer_checked(
                TransferCheckedParams(
                    program_id=token_program_pubkey,
                    source=sender_ata_pubkey,
                    mint=mint_pubkey,
                    dest=recipient_ata_pubkey,
                    owner=sender_pubkey,
                    amount=raw_amount,
                    decimals=resolved_decimals,
                    signers=[],
                )
            )
        )

        blockhash = Hash.from_string(str(preview["latest_blockhash"]))
        message = Message.new_with_blockhash(instructions, sender_pubkey, blockhash)
        transaction = Transaction([keypair], message, blockhash)
        transaction_base64 = encode_transaction_base64(bytes(transaction))

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": "spl",
            "from_address": sender,
            "to_address": recipient,
            "mint": mint,
            "token_program_id": token_program_id,
            "sender_token_account": sender_ata,
            "recipient_token_account": recipient_ata,
            "recipient_token_account_exists_before": bool(
                preview["recipient_token_account_exists"]
            ),
            "recipient_token_account_created": not bool(preview["recipient_token_account_exists"]),
            "amount_ui": amount_ui,
            "amount_raw": raw_amount,
            "decimals": resolved_decimals,
            "transaction_base64": transaction_base64,
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": str(preview["latest_blockhash"]),
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def preview_close_empty_token_accounts(
        self,
        limit: int = 8,
    ) -> dict[str, Any]:
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if limit <= 0:
            raise WalletBackendError("limit must be greater than zero.")

        candidates = await self._list_empty_closeable_token_accounts(owner)
        selected = candidates[:limit]
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "close_empty_token_accounts",
            "address": owner,
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "accounts": selected,
            "limit": limit,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "solana-rpc",
        }

    async def close_empty_token_accounts(
        self,
        limit: int = 8,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )

        preview = await self.preview_close_empty_token_accounts(limit=limit)
        if not preview["accounts"]:
            return {
                "chain": "solana",
                "network": self.network,
                "mode": "execute",
                "asset_type": "close_empty_token_accounts",
                "address": preview["address"],
                "candidate_count": 0,
                "closed_accounts": [],
                "signature": None,
                "broadcasted": False,
                "confirmed": False,
                "source": "solana-rpc",
            }

        try:
            from solders.hash import Hash
            from solders.keypair import Keypair
            from solders.message import Message
            from solders.pubkey import Pubkey
            from solders.transaction import Transaction
            from spl.token.instructions import CloseAccountParams, close_account
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required to close token accounts."
            ) from exc

        owner = str(preview["address"])
        owner_pubkey = Pubkey.from_string(owner)
        keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        instructions = []
        for account in preview["accounts"]:
            instructions.append(
                close_account(
                    CloseAccountParams(
                        program_id=Pubkey.from_string(str(account["token_program_id"])),
                        account=Pubkey.from_string(str(account["token_account"])),
                        dest=owner_pubkey,
                        owner=owner_pubkey,
                        signers=[],
                    )
                )
            )

        latest_blockhash = await solana_rpc.fetch_latest_blockhash(
            rpc_url=self.rpc_url,
            commitment=self.commitment,
        )
        blockhash = Hash.from_string(str(latest_blockhash["blockhash"]))
        message = Message.new_with_blockhash(instructions, owner_pubkey, blockhash)
        transaction = Transaction([keypair], message, blockhash)

        submitted = await solana_rpc.send_transaction(
            transaction_base64=encode_transaction_base64(bytes(transaction)),
            rpc_url=self.rpc_url,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_url,
            )
            confirmed = status is not None

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": "close_empty_token_accounts",
            "address": owner,
            "candidate_count": preview["candidate_count"],
            "closed_accounts": preview["accounts"],
            "signature": signature,
            "broadcasted": bool(signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "source": "solana-rpc",
        }

    async def preview_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        if self.network != "mainnet":
            raise WalletBackendError("Jupiter swaps are only enabled for Solana mainnet.")
        if amount_ui <= 0:
            raise WalletBackendError("amount must be greater than zero.")
        if slippage_bps <= 0:
            raise WalletBackendError("slippage_bps must be greater than zero.")

        input_mint = validate_solana_mint(input_mint)
        output_mint = validate_solana_mint(output_mint)
        if input_mint == output_mint:
            raise WalletBackendError("input_mint and output_mint must be different.")

        input_decimals = await self._resolve_mint_decimals(input_mint)
        output_decimals = await self._resolve_mint_decimals(output_mint)
        raw_amount = int(round(amount_ui * (10**input_decimals)))
        if raw_amount <= 0:
            raise WalletBackendError("amount is too small for the input token decimals.")

        quote = await jupiter.fetch_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=raw_amount,
            slippage_bps=slippage_bps,
        )
        out_amount_raw = int(quote.get("outAmount") or 0)
        other_threshold_raw = int(quote.get("otherAmountThreshold") or 0)
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "swap",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount_ui": amount_ui,
            "input_amount_raw": raw_amount,
            "input_decimals": input_decimals,
            "estimated_output_amount_ui": out_amount_raw / (10**output_decimals),
            "estimated_output_amount_raw": out_amount_raw,
            "minimum_output_amount_ui": other_threshold_raw / (10**output_decimals),
            "minimum_output_amount_raw": other_threshold_raw,
            "output_decimals": output_decimals,
            "slippage_bps": int(quote.get("slippageBps") or slippage_bps),
            "price_impact_pct": quote.get("priceImpactPct"),
            "route_plan": quote.get("routePlan", []),
            "context_slot": quote.get("contextSlot"),
            "time_taken_seconds": quote.get("timeTaken"),
            "quote_response": quote,
            "can_send": self.get_capabilities().can_send_transaction,
            "sign_only": self.sign_only,
            "source": "jupiter",
        }

    async def execute_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        prepared = await self.prepare_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )

        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_url,
        )
        onchain_signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(onchain_signature, str) and onchain_signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=onchain_signature,
                rpc_url=self.rpc_url,
            )
            confirmed = status is not None

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": "swap",
            "input_mint": prepared["input_mint"],
            "output_mint": prepared["output_mint"],
            "input_amount_ui": prepared["input_amount_ui"],
            "estimated_output_amount_ui": prepared["estimated_output_amount_ui"],
            "minimum_output_amount_ui": prepared["minimum_output_amount_ui"],
            "slippage_bps": prepared["slippage_bps"],
            "price_impact_pct": prepared["price_impact_pct"],
            "signature": onchain_signature,
            "broadcasted": bool(onchain_signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "last_valid_block_height": prepared["last_valid_block_height"],
            "prioritization_fee_lamports": prepared["prioritization_fee_lamports"],
            "compute_unit_limit": prepared["compute_unit_limit"],
            "source": "jupiter",
        }

    async def prepare_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")

        sender = await self.get_address()
        if not sender:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )

        preview = await self.preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        swap_build = await jupiter.build_swap_transaction(
            user_public_key=sender,
            quote_response=preview["quote_response"],
        )

        try:
            from solders.keypair import Keypair
            from solders.message import to_bytes_versioned
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Jupiter swap execution."
            ) from exc

        unsigned_transaction = VersionedTransaction.from_bytes(
            base64.b64decode(str(swap_build["swapTransaction"]))
        )
        keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        signature = keypair.sign_message(to_bytes_versioned(unsigned_transaction.message))
        signed_transaction = VersionedTransaction.populate(
            unsigned_transaction.message,
            [signature],
        )

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": "swap",
            "input_mint": preview["input_mint"],
            "output_mint": preview["output_mint"],
            "input_amount_ui": preview["input_amount_ui"],
            "estimated_output_amount_ui": preview["estimated_output_amount_ui"],
            "minimum_output_amount_ui": preview["minimum_output_amount_ui"],
            "slippage_bps": preview["slippage_bps"],
            "price_impact_pct": preview["price_impact_pct"],
            "transaction_base64": encode_transaction_base64(bytes(signed_transaction)),
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "last_valid_block_height": swap_build.get("lastValidBlockHeight"),
            "prioritization_fee_lamports": swap_build.get("prioritizationFeeLamports"),
            "compute_unit_limit": swap_build.get("computeUnitLimit"),
            "source": "jupiter",
        }
