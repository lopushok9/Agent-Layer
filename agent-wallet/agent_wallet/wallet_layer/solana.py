"""Solana wallet backend focused on simple local or read-only operation."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from agent_wallet.models import AgentWalletCapabilities, SolanaWalletState
from agent_wallet.providers import jupiter, solana_rpc
from agent_wallet.solana_stake import (
    STAKE_STATE_V2_SIZE,
    deactivate_stake as build_deactivate_stake_instruction,
    delegate_stake as build_delegate_stake_instruction,
    initialize_checked as build_initialize_checked_instruction,
    withdraw_stake as build_withdraw_stake_instruction,
)
from agent_wallet.solana_tx import (
    build_legacy_sol_transfer_message,
    encode_transaction_base64,
    serialize_legacy_transaction,
)
from agent_wallet.transaction_policy import verify_provider_swap_transaction
from agent_wallet.validation import validate_solana_address, validate_solana_mint
from agent_wallet.wallet_layer.base import (
    AgentWalletBackend,
    WalletBackendError,
    WalletCapabilities,
)
from agent_wallet.exceptions import ProviderError
from agent_wallet.wallet_layer.base58 import b58decode, b58encode

SOLANA_BASE_FEE_LAMPORTS = 5_000
SOLANA_STAKE_CREATE_SIGNATURE_FEE_LAMPORTS = 10_000
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"
STAKE_PROGRAM_ID = "Stake11111111111111111111111111111111111111"


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


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        rpc_url: str | list[str],
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

        self.rpc_urls = rpc_url if isinstance(rpc_url, list) else [rpc_url]
        self.rpc_url = self.rpc_urls[0]
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
            rpc_url=self.rpc_urls,
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

    async def get_staking_validators(
        self,
        limit: int = 20,
        include_delinquent: bool = False,
    ) -> dict[str, Any]:
        if limit <= 0:
            raise WalletBackendError("limit must be greater than zero.")
        vote_accounts = await solana_rpc.fetch_vote_accounts(
            rpc_url=self.rpc_urls,
            commitment=self.commitment,
        )
        validators: list[dict[str, Any]] = []
        for item in vote_accounts["current"]:
            validator = dict(item)
            validator["status"] = "current"
            validators.append(validator)
        if include_delinquent:
            for item in vote_accounts["delinquent"]:
                validator = dict(item)
                validator["status"] = "delinquent"
                validators.append(validator)
        validators.sort(
            key=lambda item: int(item.get("activatedStake") or 0),
            reverse=True,
        )
        selected = validators[:limit]
        return {
            "chain": "solana",
            "network": self.network,
            "limit": limit,
            "include_delinquent": include_delinquent,
            "validator_count": len(selected),
            "validators": selected,
            "source": "solana-rpc",
        }

    async def _fetch_stake_account_snapshot(self, stake_account: str) -> dict[str, Any]:
        stake_account = validate_solana_address(stake_account)
        account_info, balance, activation = await asyncio.gather(
            solana_rpc.fetch_account_info(
                stake_account,
                rpc_url=self.rpc_urls,
                encoding="jsonParsed",
            ),
            self.get_balance(stake_account),
            solana_rpc.fetch_stake_activation(
                stake_account,
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            ),
        )
        if account_info is None:
            raise WalletBackendError("Stake account was not found on Solana RPC.")
        if str(account_info.get("owner")) != STAKE_PROGRAM_ID:
            raise WalletBackendError("Provided account is not owned by the Solana Stake Program.")

        parsed = account_info.get("data", {}).get("parsed", {}) if isinstance(account_info, dict) else {}
        info = parsed.get("info", {}) if isinstance(parsed, dict) else {}
        meta = info.get("meta", {}) if isinstance(info, dict) else {}
        authorized = meta.get("authorized", {}) if isinstance(meta, dict) else {}
        lockup = meta.get("lockup", {}) if isinstance(meta, dict) else {}
        stake_info = info.get("stake", {}) if isinstance(info, dict) else {}
        delegation = stake_info.get("delegation", {}) if isinstance(stake_info, dict) else {}
        rent_exempt_reserve = meta.get("rentExemptReserve")
        rent_exempt_lamports = int(rent_exempt_reserve or 0)
        balance_lamports = int(round(float(balance["balance_native"]) * solana_rpc.LAMPORTS_PER_SOL))
        withdrawable_lamports = max(balance_lamports - rent_exempt_lamports, 0)
        return {
            "chain": "solana",
            "network": self.network,
            "stake_account": stake_account,
            "lamports": balance_lamports,
            "balance_native": balance["balance_native"],
            "rent_exempt_reserve_lamports": rent_exempt_lamports,
            "rent_exempt_reserve_native": rent_exempt_lamports / solana_rpc.LAMPORTS_PER_SOL,
            "estimated_withdrawable_lamports": withdrawable_lamports,
            "estimated_withdrawable_native": withdrawable_lamports / solana_rpc.LAMPORTS_PER_SOL,
            "account_type": parsed.get("type") if isinstance(parsed, dict) else None,
            "authorized_staker": authorized.get("staker"),
            "authorized_withdrawer": authorized.get("withdrawer"),
            "lockup": lockup,
            "delegation": delegation,
            "activation": activation,
            "raw_account": account_info,
            "source": "solana-rpc",
        }

    async def get_stake_account(self, stake_account: str) -> dict[str, Any]:
        return await self._fetch_stake_account_snapshot(stake_account)

    def _build_swap_fee_summary(
        self,
        *,
        swap_provider: str,
        quote_response: dict[str, Any],
        prioritization_fee_lamports: Any = None,
        compute_unit_limit: Any = None,
        signature_fee_lamports: Any = None,
        rent_fee_lamports: Any = None,
    ) -> dict[str, Any]:
        fee_bps = _coerce_int(quote_response.get("feeBps"))
        resolved_signature_fee = _coerce_int(signature_fee_lamports)
        resolved_priority_fee = _coerce_int(prioritization_fee_lamports)
        resolved_rent_fee = _coerce_int(rent_fee_lamports)

        if resolved_signature_fee is None and swap_provider == "jupiter-metis":
            resolved_signature_fee = SOLANA_BASE_FEE_LAMPORTS
        if resolved_signature_fee is None:
            resolved_signature_fee = _coerce_int(quote_response.get("signatureFeeLamports"))
        if resolved_priority_fee is None:
            resolved_priority_fee = _coerce_int(quote_response.get("prioritizationFeeLamports"))
        if resolved_rent_fee is None:
            resolved_rent_fee = _coerce_int(quote_response.get("rentFeeLamports"))

        known_lamport_parts = [
            value
            for value in (resolved_signature_fee, resolved_priority_fee, resolved_rent_fee)
            if isinstance(value, int)
        ]
        total_known_lamports = sum(known_lamport_parts)

        return {
            "swap_provider": swap_provider,
            "network_fee_lamports": total_known_lamports,
            "network_fee_sol": total_known_lamports / solana_rpc.LAMPORTS_PER_SOL,
            "signature_fee_lamports": resolved_signature_fee or 0,
            "prioritization_fee_lamports": resolved_priority_fee or 0,
            "rent_fee_lamports": resolved_rent_fee or 0,
            "route_fee_bps": fee_bps,
            "compute_unit_limit": _coerce_int(compute_unit_limit),
            "quoted_output_includes_route_fees": True,
        }

    def _format_swap_fee_label(self, fee_summary: dict[str, Any]) -> str:
        network_fee_sol = float(fee_summary.get("network_fee_sol") or 0)
        route_fee_bps = fee_summary.get("route_fee_bps")
        parts = [f"network fee ~{network_fee_sol:.6f} SOL"]
        if isinstance(route_fee_bps, int):
            parts.append(f"route fee {route_fee_bps} bps (already reflected in quoted output)")
        return "; ".join(parts)

    def _require_mainnet_jupiter(self, feature: str) -> None:
        if self.network != "mainnet":
            raise WalletBackendError(f"{feature} is only enabled for Solana mainnet.")

    async def get_jupiter_portfolio_platforms(self) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter portfolio")
        data = await jupiter.fetch_portfolio_platforms()
        platforms = data.get("platforms")
        if not isinstance(platforms, list):
            platforms = data.get("data") if isinstance(data.get("data"), list) else []
        return {
            "chain": "solana",
            "network": self.network,
            "platform_count": len(platforms),
            "platforms": platforms,
            "raw": data,
            "source": "jupiter-portfolio",
        }

    async def get_jupiter_portfolio(
        self,
        address: str | None = None,
        platforms: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter portfolio")
        wallet_address = address or self.address
        if not wallet_address:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        wallet_address = validate_solana_address(wallet_address)
        platform_filter: list[str] | None = None
        if platforms is not None:
            platform_filter = []
            for platform in platforms:
                if not isinstance(platform, str) or not platform.strip():
                    raise WalletBackendError("Each platform must be a non-empty string.")
                platform_filter.append(platform.strip())
        data = await jupiter.fetch_portfolio_positions(
            address=wallet_address,
            platforms=platform_filter,
        )
        positions = data.get("positions")
        if not isinstance(positions, list):
            positions = data.get("data") if isinstance(data.get("data"), list) else []
        return {
            "chain": "solana",
            "network": self.network,
            "address": wallet_address,
            "platforms": platform_filter or [],
            "position_count": len(positions),
            "positions": positions,
            "raw": data,
            "source": "jupiter-portfolio",
        }

    async def get_jupiter_staked_jup(self, address: str | None = None) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter staked JUP")
        wallet_address = address or self.address
        if not wallet_address:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        wallet_address = validate_solana_address(wallet_address)
        data = await jupiter.fetch_staked_jup(address=wallet_address)
        return {
            "chain": "solana",
            "network": self.network,
            "address": wallet_address,
            "raw": data,
            "source": "jupiter-portfolio",
        }

    async def get_jupiter_earn_tokens(self) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter Earn")
        data = await jupiter.fetch_earn_tokens()
        tokens = data.get("tokens")
        if not isinstance(tokens, list):
            tokens = data.get("data") if isinstance(data.get("data"), list) else []
        return {
            "chain": "solana",
            "network": self.network,
            "token_count": len(tokens),
            "tokens": tokens,
            "raw": data,
            "source": "jupiter-lend",
        }

    async def get_jupiter_earn_positions(
        self,
        users: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter Earn")
        resolved_users = users or [self.address]
        if not resolved_users or any(user is None for user in resolved_users):
            raise WalletBackendError("At least one wallet address is required for Earn positions.")
        normalized_users = [validate_solana_address(str(user)) for user in resolved_users]
        data = await jupiter.fetch_earn_positions(users=normalized_users)
        positions = data.get("positions")
        if not isinstance(positions, list):
            positions = data.get("data") if isinstance(data.get("data"), list) else []
        return {
            "chain": "solana",
            "network": self.network,
            "users": normalized_users,
            "position_count": len(positions),
            "positions": positions,
            "raw": data,
            "source": "jupiter-lend",
        }

    async def get_jupiter_earn_earnings(
        self,
        user: str | None = None,
        positions: list[str] | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter Earn")
        wallet_address = user or self.address
        if not wallet_address:
            raise WalletBackendError(
                "A wallet address is required for Jupiter Earn earnings lookup."
            )
        if not positions:
            raise WalletBackendError("positions must include at least one Earn position address.")
        wallet_address = validate_solana_address(wallet_address)
        normalized_positions = [validate_solana_address(str(position)) for position in positions]
        data = await jupiter.fetch_earn_earnings(
            user=wallet_address,
            positions=normalized_positions,
        )
        return {
            "chain": "solana",
            "network": self.network,
            "user": wallet_address,
            "positions": normalized_positions,
            "raw": data,
            "source": "jupiter-lend",
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

    async def preview_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict[str, Any]:
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if amount_native <= 0:
            raise WalletBackendError("amount must be greater than zero.")
        vote_account = validate_solana_address(vote_account)

        validator_set, balance, latest_blockhash, rent_exempt = await asyncio.gather(
            self.get_staking_validators(limit=200, include_delinquent=True),
            self.get_balance(owner),
            solana_rpc.fetch_latest_blockhash(
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            ),
            solana_rpc.fetch_minimum_balance_for_rent_exemption(
                STAKE_STATE_V2_SIZE,
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            ),
        )

        validator = next(
            (item for item in validator_set["validators"] if str(item.get("votePubkey")) == vote_account),
            None,
        )
        if validator is None:
            raise WalletBackendError("vote_account was not found in current Solana vote accounts.")

        stake_lamports = int(round(amount_native * solana_rpc.LAMPORTS_PER_SOL))
        if stake_lamports <= 0:
            raise WalletBackendError("amount is too small after converting to lamports.")
        rent_lamports = int(rent_exempt["lamports"])
        total_lamports = stake_lamports + rent_lamports
        available_lamports = int(round(balance["balance_native"] * solana_rpc.LAMPORTS_PER_SOL))
        total_with_fees = total_lamports + SOLANA_STAKE_CREATE_SIGNATURE_FEE_LAMPORTS
        if total_with_fees > available_lamports:
            raise WalletBackendError(
                "Insufficient SOL balance for native staking preview, including rent and estimated fees."
            )

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "native-stake",
            "owner": owner,
            "stake_account_address": None,
            "vote_account": vote_account,
            "validator": validator,
            "amount_native": amount_native,
            "stake_lamports": stake_lamports,
            "rent_exempt_lamports": rent_lamports,
            "rent_exempt_native": rent_lamports / solana_rpc.LAMPORTS_PER_SOL,
            "total_lamports": total_lamports,
            "estimated_fee_lamports": SOLANA_STAKE_CREATE_SIGNATURE_FEE_LAMPORTS,
            "estimated_fee_native": (
                SOLANA_STAKE_CREATE_SIGNATURE_FEE_LAMPORTS / solana_rpc.LAMPORTS_PER_SOL
            ),
            "balance_native_before": balance["balance_native"],
            "estimated_balance_native_after": (
                (available_lamports - total_with_fees) / solana_rpc.LAMPORTS_PER_SOL
            ),
            "latest_blockhash": latest_blockhash["blockhash"],
            "last_valid_block_height": latest_blockhash["last_valid_block_height"],
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "solana-rpc",
        }

    async def prepare_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")

        preview = await self.preview_native_stake(vote_account=vote_account, amount_native=amount_native)
        try:
            from solders.hash import Hash
            from solders.keypair import Keypair
            from solders.message import Message
            from solders.pubkey import Pubkey
            from solders.system_program import CreateAccountParams, create_account
            from solders.transaction import Transaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for native staking."
            ) from exc

        owner = str(preview["owner"])
        owner_pubkey = Pubkey.from_string(owner)
        vote_pubkey = Pubkey.from_string(str(preview["vote_account"]))
        wallet_keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        stake_keypair = Keypair()
        stake_account_address = str(stake_keypair.pubkey())
        blockhash = Hash.from_string(str(preview["latest_blockhash"]))

        instructions = [
            create_account(
                CreateAccountParams(
                    from_pubkey=owner_pubkey,
                    to_pubkey=stake_keypair.pubkey(),
                    lamports=int(preview["total_lamports"]),
                    space=STAKE_STATE_V2_SIZE,
                    owner=Pubkey.from_string(STAKE_PROGRAM_ID),
                )
            ),
            build_initialize_checked_instruction(
                stake_account=stake_keypair.pubkey(),
                staker=owner_pubkey,
                withdrawer=owner_pubkey,
            ),
            build_delegate_stake_instruction(
                stake_account=stake_keypair.pubkey(),
                vote_account=vote_pubkey,
                authority=owner_pubkey,
            ),
        ]
        message = Message.new_with_blockhash(instructions, owner_pubkey, blockhash)
        transaction = Transaction([wallet_keypair, stake_keypair], message, blockhash)

        fee_summary = self._build_swap_fee_summary(
            swap_provider=swap_provider,
            quote_response=preview["quote_response"],
            prioritization_fee_lamports=prioritization_fee_lamports,
            compute_unit_limit=compute_unit_limit,
        )

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": "native-stake",
            "owner": owner,
            "stake_account_address": stake_account_address,
            "vote_account": str(preview["vote_account"]),
            "amount_native": amount_native,
            "stake_lamports": int(preview["stake_lamports"]),
            "rent_exempt_lamports": int(preview["rent_exempt_lamports"]),
            "total_lamports": int(preview["total_lamports"]),
            "estimated_fee_lamports": int(preview["estimated_fee_lamports"]),
            "validator": preview["validator"],
            "transaction_base64": encode_transaction_base64(bytes(transaction)),
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": str(preview["latest_blockhash"]),
            "last_valid_block_height": preview["last_valid_block_height"],
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def execute_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict[str, Any]:
        prepared = await self.prepare_native_stake(vote_account=vote_account, amount_native=amount_native)
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )
        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_urls,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
            )
            confirmed = status is not None
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": "native-stake",
            "owner": prepared["owner"],
            "stake_account_address": prepared["stake_account_address"],
            "vote_account": prepared["vote_account"],
            "amount_native": prepared["amount_native"],
            "stake_lamports": prepared["stake_lamports"],
            "rent_exempt_lamports": prepared["rent_exempt_lamports"],
            "total_lamports": prepared["total_lamports"],
            "signature": signature,
            "broadcasted": bool(signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def preview_deactivate_stake(self, stake_account: str) -> dict[str, Any]:
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        snapshot, latest_blockhash = await asyncio.gather(
            self.get_stake_account(stake_account),
            solana_rpc.fetch_latest_blockhash(
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            ),
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "deactivate-stake",
            "authority": owner,
            "stake_account": snapshot["stake_account"],
            "activation": snapshot["activation"],
            "delegation": snapshot["delegation"],
            "latest_blockhash": latest_blockhash["blockhash"],
            "last_valid_block_height": latest_blockhash["last_valid_block_height"],
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "solana-rpc",
        }

    async def prepare_deactivate_stake(self, stake_account: str) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        preview = await self.preview_deactivate_stake(stake_account)
        try:
            from solders.hash import Hash
            from solders.keypair import Keypair
            from solders.message import Message
            from solders.pubkey import Pubkey
            from solders.transaction import Transaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for native staking."
            ) from exc
        authority_pubkey = Pubkey.from_string(str(preview["authority"]))
        stake_pubkey = Pubkey.from_string(str(preview["stake_account"]))
        wallet_keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        blockhash = Hash.from_string(str(preview["latest_blockhash"]))
        message = Message.new_with_blockhash(
            [build_deactivate_stake_instruction(stake_account=stake_pubkey, authority=authority_pubkey)],
            authority_pubkey,
            blockhash,
        )
        transaction = Transaction([wallet_keypair], message, blockhash)
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": "deactivate-stake",
            "authority": str(preview["authority"]),
            "stake_account": str(preview["stake_account"]),
            "transaction_base64": encode_transaction_base64(bytes(transaction)),
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": str(preview["latest_blockhash"]),
            "last_valid_block_height": preview["last_valid_block_height"],
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def execute_deactivate_stake(self, stake_account: str) -> dict[str, Any]:
        prepared = await self.prepare_deactivate_stake(stake_account)
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )
        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_urls,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
            )
            confirmed = status is not None
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": "deactivate-stake",
            "authority": prepared["authority"],
            "stake_account": prepared["stake_account"],
            "signature": signature,
            "broadcasted": bool(signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def preview_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if amount_native <= 0:
            raise WalletBackendError("amount must be greater than zero.")
        recipient_address = validate_solana_address(recipient or owner)
        snapshot, latest_blockhash = await asyncio.gather(
            self.get_stake_account(stake_account),
            solana_rpc.fetch_latest_blockhash(
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            ),
        )
        lamports = int(round(amount_native * solana_rpc.LAMPORTS_PER_SOL))
        if lamports > int(snapshot["estimated_withdrawable_lamports"]):
            raise WalletBackendError(
                "Requested withdraw amount exceeds the estimated withdrawable lamports for this stake account."
            )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "withdraw-stake",
            "authority": owner,
            "stake_account": snapshot["stake_account"],
            "recipient": recipient_address,
            "amount_native": amount_native,
            "amount_lamports": lamports,
            "activation": snapshot["activation"],
            "estimated_withdrawable_lamports": snapshot["estimated_withdrawable_lamports"],
            "latest_blockhash": latest_blockhash["blockhash"],
            "last_valid_block_height": latest_blockhash["last_valid_block_height"],
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "solana-rpc",
        }

    async def prepare_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        preview = await self.preview_withdraw_stake(
            stake_account=stake_account,
            amount_native=amount_native,
            recipient=recipient,
        )
        try:
            from solders.hash import Hash
            from solders.keypair import Keypair
            from solders.message import Message
            from solders.pubkey import Pubkey
            from solders.transaction import Transaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for native staking."
            ) from exc
        authority_pubkey = Pubkey.from_string(str(preview["authority"]))
        stake_pubkey = Pubkey.from_string(str(preview["stake_account"]))
        recipient_pubkey = Pubkey.from_string(str(preview["recipient"]))
        wallet_keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        blockhash = Hash.from_string(str(preview["latest_blockhash"]))
        message = Message.new_with_blockhash(
            [
                build_withdraw_stake_instruction(
                    stake_account=stake_pubkey,
                    recipient=recipient_pubkey,
                    authority=authority_pubkey,
                    lamports=int(preview["amount_lamports"]),
                )
            ],
            authority_pubkey,
            blockhash,
        )
        transaction = Transaction([wallet_keypair], message, blockhash)
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": "withdraw-stake",
            "authority": str(preview["authority"]),
            "stake_account": str(preview["stake_account"]),
            "recipient": str(preview["recipient"]),
            "amount_native": amount_native,
            "amount_lamports": int(preview["amount_lamports"]),
            "transaction_base64": encode_transaction_base64(bytes(transaction)),
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": str(preview["latest_blockhash"]),
            "last_valid_block_height": preview["last_valid_block_height"],
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def execute_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_withdraw_stake(
            stake_account=stake_account,
            amount_native=amount_native,
            recipient=recipient,
        )
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )
        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_urls,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
            )
            confirmed = status is not None
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": "withdraw-stake",
            "authority": prepared["authority"],
            "stake_account": prepared["stake_account"],
            "recipient": prepared["recipient"],
            "amount_native": prepared["amount_native"],
            "amount_lamports": prepared["amount_lamports"],
            "signature": signature,
            "broadcasted": bool(signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "sign_only": self.sign_only,
            "source": "solana-rpc",
        }

    async def _prepare_jupiter_lend_transaction(
        self,
        *,
        transaction_base64: str,
        action: str,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")

        try:
            from solders.keypair import Keypair
            from solders.message import to_bytes_versioned
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Jupiter Earn transaction signing."
            ) from exc

        unsigned_transaction = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))
        keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        signature = keypair.sign_message(to_bytes_versioned(unsigned_transaction.message))
        signed_transaction = VersionedTransaction.populate(
            unsigned_transaction.message,
            [signature],
        )
        owner = await self.get_address()
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": f"jupiter-earn-{action}",
            "owner": owner,
            "asset": asset,
            "amount_raw": amount_raw,
            "transaction_base64": encode_transaction_base64(bytes(signed_transaction)),
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "sign_only": self.sign_only,
            "source": "jupiter-lend",
        }

    async def _execute_prepared_jupiter_lend_transaction(self, prepared: dict[str, Any]) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )
        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_urls,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
            )
            confirmed = status is not None
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": prepared["asset_type"],
            "owner": prepared.get("owner"),
            "asset": prepared.get("asset"),
            "amount_raw": prepared.get("amount_raw"),
            "signature": signature,
            "broadcasted": bool(signature),
            "confirmed": confirmed,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "sign_only": self.sign_only,
            "source": "jupiter-lend",
        }

    async def preview_jupiter_earn_deposit(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter Earn")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if not isinstance(amount_raw, str) or not amount_raw.strip().isdigit():
            raise WalletBackendError("amount_raw must be a positive integer string.")
        asset = validate_solana_mint(asset)
        tokens = await self.get_jupiter_earn_tokens()
        token_entry = next(
            (
                item
                for item in tokens["tokens"]
                if isinstance(item, dict)
                and str(item.get("asset") or item.get("mint") or "").strip() == asset
            ),
            None,
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "jupiter-earn-deposit",
            "owner": owner,
            "asset": asset,
            "amount_raw": amount_raw.strip(),
            "token": token_entry,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "jupiter-lend",
        }

    async def prepare_jupiter_earn_deposit(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        preview = await self.preview_jupiter_earn_deposit(asset=asset, amount_raw=amount_raw)
        owner = str(preview["owner"])
        build = await jupiter.build_earn_deposit_transaction(
            asset=str(preview["asset"]),
            user_address=owner,
            amount_raw=str(preview["amount_raw"]),
        )
        prepared = await self._prepare_jupiter_lend_transaction(
            transaction_base64=str(build["transaction"]),
            action="deposit",
            asset=str(preview["asset"]),
            amount_raw=str(preview["amount_raw"]),
        )
        prepared["build_response"] = build
        return prepared

    async def execute_jupiter_earn_deposit(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        prepared = await self.prepare_jupiter_earn_deposit(asset=asset, amount_raw=amount_raw)
        result = await self._execute_prepared_jupiter_lend_transaction(prepared)
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_jupiter_earn_withdraw(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        self._require_mainnet_jupiter("Jupiter Earn")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if not isinstance(amount_raw, str) or not amount_raw.strip().isdigit():
            raise WalletBackendError("amount_raw must be a positive integer string.")
        asset = validate_solana_mint(asset)
        positions = await self.get_jupiter_earn_positions(users=[owner])
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "jupiter-earn-withdraw",
            "owner": owner,
            "asset": asset,
            "amount_raw": amount_raw.strip(),
            "positions": positions["positions"],
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "jupiter-lend",
        }

    async def prepare_jupiter_earn_withdraw(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        preview = await self.preview_jupiter_earn_withdraw(asset=asset, amount_raw=amount_raw)
        owner = str(preview["owner"])
        build = await jupiter.build_earn_withdraw_transaction(
            asset=str(preview["asset"]),
            user_address=owner,
            amount_raw=str(preview["amount_raw"]),
        )
        prepared = await self._prepare_jupiter_lend_transaction(
            transaction_base64=str(build["transaction"]),
            action="withdraw",
            asset=str(preview["asset"]),
            amount_raw=str(preview["amount_raw"]),
        )
        prepared["build_response"] = build
        return prepared

    async def execute_jupiter_earn_withdraw(
        self,
        asset: str,
        amount_raw: str,
    ) -> dict[str, Any]:
        prepared = await self.prepare_jupiter_earn_withdraw(asset=asset, amount_raw=amount_raw)
        result = await self._execute_prepared_jupiter_lend_transaction(prepared)
        result["build_response"] = prepared.get("build_response")
        return result

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
            rpc_url=self.rpc_urls,
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
            rpc_url=self.rpc_urls,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
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
            rpc_url=self.rpc_urls,
            commitment=self.commitment,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
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
        token_info = await solana_rpc.fetch_token_supply_info(mint, rpc_url=self.rpc_urls)
        return int(token_info.get("decimals") or 0)

    async def _resolve_token_program_id(self, mint: str) -> str:
        if mint == NATIVE_SOL_MINT:
            return TOKEN_PROGRAM_ID
        account_info = await solana_rpc.fetch_account_info(mint, rpc_url=self.rpc_urls)
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
                rpc_url=self.rpc_urls,
                token_program_id=TOKEN_PROGRAM_ID,
            ),
            solana_rpc.fetch_token_accounts_by_owner(
                owner,
                rpc_url=self.rpc_urls,
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

        sender_ata_exists = await solana_rpc.account_exists(sender_ata, rpc_url=self.rpc_urls)
        if not sender_ata_exists:
            raise WalletBackendError("Sender token account does not exist for this mint.")

        token_info = await solana_rpc.fetch_token_supply_info(mint, rpc_url=self.rpc_urls)
        resolved_decimals = int(
            decimals if decimals is not None else (token_info.get("decimals") or 0)
        )
        raw_amount = int(round(amount_ui * (10**resolved_decimals)))
        if raw_amount <= 0:
            raise WalletBackendError("amount is too small for the token decimals.")

        sender_balance = await solana_rpc.fetch_token_account_balance(
            sender_ata,
            rpc_url=self.rpc_urls,
        )
        sender_raw_balance = int(sender_balance.get("amount") or 0)
        if raw_amount > sender_raw_balance:
            raise WalletBackendError("Insufficient token balance for this transfer preview.")

        recipient_ata_exists = await solana_rpc.account_exists(recipient_ata, rpc_url=self.rpc_urls)
        latest_blockhash = await solana_rpc.fetch_latest_blockhash(
            rpc_url=self.rpc_urls,
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
            rpc_url=self.rpc_urls,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
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
            rpc_url=self.rpc_urls,
            commitment=self.commitment,
        )
        blockhash = Hash.from_string(str(latest_blockhash["blockhash"]))
        message = Message.new_with_blockhash(instructions, owner_pubkey, blockhash)
        transaction = Transaction([keypair], message, blockhash)

        submitted = await solana_rpc.send_transaction(
            transaction_base64=encode_transaction_base64(bytes(transaction)),
            rpc_url=self.rpc_urls,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
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

        sender = await self.get_address()
        quote_source = "jupiter-ultra"
        try:
            quote = await jupiter.fetch_ultra_order(
                input_mint=input_mint,
                output_mint=output_mint,
                amount_raw=raw_amount,
                taker=sender,
                slippage_bps=slippage_bps,
            )
        except ProviderError:
            quote = await jupiter.fetch_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount_raw=raw_amount,
                slippage_bps=slippage_bps,
            )
            quote_source = "jupiter-metis"

        out_amount_raw = int(quote.get("outAmount") or 0)
        other_threshold_raw = int(
            quote.get("otherAmountThreshold")
            or quote.get("minOutAmount")
            or 0
        )
        fee_summary = self._build_swap_fee_summary(
            swap_provider=quote_source,
            quote_response=quote,
        )
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
            "fee_summary": fee_summary,
            "estimated_total_fee_label": self._format_swap_fee_label(fee_summary),
            "quote_response": quote,
            "swap_provider": quote_source,
            "can_send": self.get_capabilities().can_send_transaction,
            "sign_only": self.sign_only,
            "source": quote_source,
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

        if prepared.get("swap_provider") == "jupiter-ultra":
            submitted = await jupiter.execute_ultra_order(
                signed_transaction_base64=str(prepared["transaction_base64"]),
                request_id=str(prepared["request_id"]),
            )
            onchain_signature = submitted.get("signature") or submitted.get("txid")
        else:
            submitted = await solana_rpc.send_transaction(
                transaction_base64=str(prepared["transaction_base64"]),
                rpc_url=self.rpc_urls,
            )
            onchain_signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(onchain_signature, str) and onchain_signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=onchain_signature,
                rpc_url=self.rpc_urls,
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
            "fee_summary": prepared.get("fee_summary"),
            "estimated_total_fee_label": prepared.get("estimated_total_fee_label"),
            "request_id": prepared.get("request_id"),
            "swap_provider": prepared.get("swap_provider"),
            "execute_response": submitted,
            "source": prepared.get("swap_provider") or "jupiter-metis",
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

        try:
            from solders.keypair import Keypair
            from solders.message import to_bytes_versioned
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Jupiter swap execution."
            ) from exc

        swap_provider = str(preview.get("swap_provider") or "jupiter-metis")
        request_id = None
        if swap_provider == "jupiter-ultra":
            swap_build = preview["quote_response"]
            unsigned_transaction = VersionedTransaction.from_bytes(
                base64.b64decode(str(swap_build["transaction"]))
            )
            request_id = swap_build.get("requestId")
            last_valid_block_height = swap_build.get("expireAt")
            prioritization_fee_lamports = swap_build.get("prioritizationFeeLamports")
            compute_unit_limit = swap_build.get("computeUnitLimit")
        else:
            swap_build = await jupiter.build_swap_transaction(
                user_public_key=sender,
                quote_response=preview["quote_response"],
            )
            unsigned_transaction = VersionedTransaction.from_bytes(
                base64.b64decode(str(swap_build["swapTransaction"]))
            )
            last_valid_block_height = swap_build.get("lastValidBlockHeight")
            prioritization_fee_lamports = swap_build.get("prioritizationFeeLamports")
            compute_unit_limit = swap_build.get("computeUnitLimit")

        verification = verify_provider_swap_transaction(
            unsigned_transaction.message,
            wallet_address=sender,
            input_mint=str(preview["input_mint"]),
            output_mint=str(preview["output_mint"]),
        )
        keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        signature = keypair.sign_message(to_bytes_versioned(unsigned_transaction.message))
        signed_transaction = VersionedTransaction.populate(
            unsigned_transaction.message,
            [signature],
        )
        fee_summary = self._build_swap_fee_summary(
            swap_provider=swap_provider,
            quote_response=preview["quote_response"],
            prioritization_fee_lamports=prioritization_fee_lamports,
            compute_unit_limit=compute_unit_limit,
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
            "last_valid_block_height": last_valid_block_height,
            "prioritization_fee_lamports": prioritization_fee_lamports,
            "compute_unit_limit": compute_unit_limit,
            "fee_summary": fee_summary,
            "estimated_total_fee_label": self._format_swap_fee_label(fee_summary),
            "verification": verification,
            "request_id": request_id,
            "swap_provider": swap_provider,
            "source": swap_provider,
        }
