"""Solana wallet backend focused on simple local or read-only operation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from agent_wallet.config import normalize_solana_network
from agent_wallet.models import AgentWalletCapabilities, SolanaWalletState
from agent_wallet.providers import bags, flash, flash_sdk_bridge, jupiter, kamino, lifi, solana_rpc
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
from agent_wallet.transaction_policy import (
    verify_provider_bags_transaction,
    verify_provider_flash_transaction,
    verify_provider_kamino_earn_transaction,
    verify_provider_kamino_lend_transaction,
    verify_provider_swap_simulation_result,
    verify_provider_swap_transaction,
)
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
SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS = 300
SOLANA_SWAP_INTENT_DEFAULT_MAX_FEE_LAMPORTS = 6_000_000
KAMINO_OPEN_POSITIONS_SCAN_CONCURRENCY = 6
# The Earn vaults catalog has no batch APY endpoint, so metrics are fetched
# per vault; cap the fan-out so one discovery call stays bounded.
KAMINO_EARN_METRICS_FETCH_LIMIT = 20


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


def _coerce_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _format_decimal(value: Decimal | None, *, places: int = 2) -> str | None:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-places)
    return str(value.quantize(quant))


def _jupiter_price_entry(price_data: dict[str, Any], mint: str) -> dict[str, Any] | None:
    entry = price_data.get(mint)
    if isinstance(entry, dict):
        return entry
    data = price_data.get("data")
    if isinstance(data, dict) and isinstance(data.get(mint), dict):
        return data[mint]
    return None


def _jupiter_usd_price(entry: dict[str, Any] | None) -> Decimal | None:
    if not isinstance(entry, dict):
        return None
    for key in ("usdPrice", "price", "usd", "value"):
        price = _coerce_decimal(entry.get(key))
        if price is not None:
            return price
    return None


def _require_positive_integer_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip().isdigit():
        raise WalletBackendError(f"{field_name} must be a positive integer string.")
    normalized = value.strip()
    if int(normalized) <= 0:
        raise WalletBackendError(f"{field_name} must be greater than zero.")
    return normalized


def _require_positive_decimal_string(value: Any, *, field_name: str) -> str:
    if isinstance(value, bool):
        raise WalletBackendError(f"{field_name} must be a positive decimal string.")
    text = str(value).strip()
    if not text:
        raise WalletBackendError(f"{field_name} must be a positive decimal string.")
    try:
        decimal_value = Decimal(text)
    except InvalidOperation as exc:
        raise WalletBackendError(f"{field_name} must be a positive decimal string.") from exc
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise WalletBackendError(f"{field_name} must be greater than zero.")
    normalized = format(decimal_value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _normalize_flash_symbol(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WalletBackendError(f"{field_name} must be a non-empty string.")
    return value.strip().upper()


def _normalize_flash_side(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WalletBackendError("side must be a non-empty string.")
    normalized = value.strip().lower()
    if normalized not in {"long", "short"}:
        raise WalletBackendError("side must be 'long' or 'short'.")
    return normalized


def _coerce_positive_int_from_any(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_non_negative_integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise WalletBackendError(f"{field_name} must be a non-negative integer.")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise WalletBackendError(f"{field_name} must be a non-negative integer.") from exc
    if normalized < 0:
        raise WalletBackendError(f"{field_name} must be a non-negative integer.")
    return normalized


def _kamino_entry_address(entry: Any, *keys: str) -> str:
    if not isinstance(entry, dict):
        return ""
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
        rpc_provider_mode: str | None = None,
        rpc_provider: str | None = None,
        rpc_transport: str | None = None,
        swap_provider: str | None = None,
        swap_transport: str | None = None,
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
        self.network = normalize_solana_network(network)
        self.signer = signer
        self.address = final_address
        self.sign_only = sign_only
        self.rpc_provider_mode = rpc_provider_mode
        self.rpc_provider = rpc_provider
        self.rpc_transport = rpc_transport
        self.swap_provider = swap_provider
        self.swap_transport = swap_transport

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

    async def _get_native_balance(self, address: str | None = None) -> dict[str, Any]:
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

    async def get_balance(self, address: str | None = None) -> dict[str, Any]:
        return await self.get_portfolio(address=address)

    async def get_portfolio(self, address: str | None = None) -> dict[str, Any]:
        wallet_address = address or self.address
        if not wallet_address:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        wallet_address = validate_solana_address(wallet_address)
        native_balance, tokens = await asyncio.gather(
            self._get_native_balance(wallet_address),
            self._fetch_token_entries(wallet_address, include_zero_balances=False),
        )
        tokens.sort(
            key=lambda item: float(item.get("amount_ui") or 0),
            reverse=True,
        )
        mints = [NATIVE_SOL_MINT]
        for token in tokens:
            mint = token.get("mint")
            if isinstance(mint, str) and mint.strip() and mint not in mints:
                mints.append(mint.strip())

        price_data_by_mint: dict[str, dict[str, Any]] = {}
        price_errors: list[str] = []
        token_metadata_by_mint: dict[str, dict[str, Any]] = {}
        token_metadata_errors: list[str] = []
        price_batches = [mints[index : index + 20] for index in range(0, len(mints), 20)]
        # Independent HTTP calls against a shared async client, so fetch every
        # price batch AND every token symbol/name lookup batch concurrently
        # instead of paying sequential round trips for wallets with many SPL
        # token accounts.
        all_results = await asyncio.gather(
            *(jupiter.fetch_prices(mints=batch) for batch in price_batches),
            *(jupiter.fetch_token_metadata(mints=batch) for batch in price_batches),
            return_exceptions=True,
        )
        batch_results = all_results[: len(price_batches)]
        metadata_batch_results = all_results[len(price_batches) :]
        for batch, result in zip(price_batches, batch_results):
            if isinstance(result, ProviderError):
                price_errors.append(str(result))
                continue
            if isinstance(result, BaseException):
                raise result
            for mint in batch:
                entry = _jupiter_price_entry(result, mint)
                if entry is not None:
                    price_data_by_mint[mint] = entry
        for result in metadata_batch_results:
            if isinstance(result, ProviderError):
                token_metadata_errors.append(str(result))
                continue
            if isinstance(result, BaseException):
                raise result
            token_metadata_by_mint.update(result)

        native_price = _jupiter_usd_price(price_data_by_mint.get(NATIVE_SOL_MINT))
        native_amount = _coerce_decimal(native_balance.get("balance_native"))
        native_value = (
            native_amount * native_price
            if native_amount is not None and native_price is not None
            else None
        )
        native_balance = {
            **native_balance,
            "mint": NATIVE_SOL_MINT,
            "symbol": "SOL",
            "balance_usd": _format_decimal(native_value),
            "price_usd": str(native_price) if native_price is not None else None,
            "value_usd": _format_decimal(native_value),
            "pricing_source": "jupiter-price" if native_price is not None else None,
        }

        enriched_tokens: list[dict[str, Any]] = []
        total_value = native_value or Decimal("0")
        priced_asset_count = 1 if native_value is not None else 0
        for token in tokens:
            mint = str(token.get("mint") or "").strip()
            amount = _coerce_decimal(token.get("amount_ui"))
            price = _jupiter_usd_price(price_data_by_mint.get(mint))
            value = amount * price if amount is not None and price is not None else None
            if value is not None:
                total_value += value
                priced_asset_count += 1
            metadata = token_metadata_by_mint.get(mint) or {}
            enriched_tokens.append(
                {
                    **token,
                    "symbol": metadata.get("symbol"),
                    "name": metadata.get("name"),
                    "price_usd": str(price) if price is not None else None,
                    "value_usd": _format_decimal(value),
                    "pricing_source": "jupiter-price" if price is not None else None,
                }
            )

        assets = [
            {
                "asset_type": "native",
                "mint": NATIVE_SOL_MINT,
                "symbol": "SOL",
                "amount_raw": str(
                    int(
                        (native_amount or Decimal("0"))
                        * Decimal(solana_rpc.LAMPORTS_PER_SOL)
                    )
                ),
                "amount_ui": native_balance.get("balance_native"),
                "price_usd": native_balance.get("price_usd"),
                "value_usd": native_balance.get("value_usd"),
                "pricing_source": native_balance.get("pricing_source"),
            }
        ]
        assets.extend(
            {
                "asset_type": "spl-token",
                "mint": token.get("mint"),
                "symbol": token.get("symbol"),
                "name": token.get("name"),
                "token_account": token.get("token_account"),
                "amount_raw": token.get("amount_raw"),
                "amount_ui": token.get("amount_ui"),
                "decimals": token.get("decimals"),
                "price_usd": token.get("price_usd"),
                "value_usd": token.get("value_usd"),
                "pricing_source": token.get("pricing_source"),
            }
            for token in enriched_tokens
        )
        assets.sort(
            key=lambda item: float(item.get("value_usd") or 0),
            reverse=True,
        )
        formatted_total_value = _format_decimal(total_value) if priced_asset_count else None
        return {
            "chain": "solana",
            "network": self.network,
            "address": wallet_address,
            "native_balance": native_balance,
            "balance_native": native_balance.get("balance_native"),
            "balance_usd": formatted_total_value,
            "native_price_usd": native_balance.get("price_usd"),
            "native_value_usd": native_balance.get("value_usd"),
            "tokens": enriched_tokens,
            "token_count": len(enriched_tokens),
            "assets": assets,
            "asset_count": len(assets),
            "priced_asset_count": priced_asset_count,
            "total_value_usd": formatted_total_value,
            "pricing_source": "jupiter-price" if price_data_by_mint else None,
            "pricing_errors": price_errors,
            "token_metadata_source": "jupiter-token-search" if token_metadata_by_mint else None,
            "token_metadata_errors": token_metadata_errors,
            "token_discovery_source": "solana-rpc",
            "source": "solana-rpc+jupiter-price",
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
            entry = _jupiter_price_entry(price_data, mint)
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

    async def get_lifi_supported_chains(self) -> dict[str, Any]:
        chains = await lifi.fetch_supported_chains()
        supported = lifi.format_openclaw_supported_chains(chains)
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "supported_by_openclaw": lifi.OPENCLAW_SUPPORTED_CHAINS,
            "chain_count": len(supported),
            "chains": supported,
            "source": "lifi",
        }

    async def get_lifi_quote(
        self,
        *,
        from_chain: str,
        to_chain: str,
        from_token: str,
        to_token: str,
        amount_in_raw: str,
        from_address: str | None = None,
        to_address: str | None = None,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict[str, Any]:
        from_chain_id = lifi.normalize_chain_id(from_chain, field_name="from_chain")
        to_chain_id = lifi.normalize_chain_id(to_chain, field_name="to_chain")
        resolved_from_address = str(from_address or "").strip()
        resolved_to_address = str(to_address or "").strip()
        wallet_address: str | None = None
        if from_chain_id == "1151111081099710" and not resolved_from_address:
            wallet_address = await self.get_address()
            resolved_from_address = str(wallet_address or "").strip()
        if to_chain_id == "1151111081099710" and not resolved_to_address:
            wallet_address = wallet_address or await self.get_address()
            resolved_to_address = str(wallet_address or "").strip()
        if not resolved_from_address:
            raise WalletBackendError("from_address is required when the LI.FI source chain is not Solana.")
        if not resolved_to_address:
            raise WalletBackendError("to_address is required when the LI.FI destination chain is not Solana.")

        payload = await lifi.fetch_quote(
            from_chain=from_chain_id,
            to_chain=to_chain_id,
            from_token=from_token,
            to_token=to_token,
            amount_in_raw=amount_in_raw,
            from_address=resolved_from_address,
            to_address=resolved_to_address,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "from_chain": lifi.chain_name_for_id(from_chain_id),
            "to_chain": lifi.chain_name_for_id(to_chain_id),
            "from_chain_id": from_chain_id,
            "to_chain_id": to_chain_id,
            "from_token": lifi.normalize_token_address(from_token, chain_id=from_chain_id),
            "to_token": lifi.normalize_token_address(to_token, chain_id=to_chain_id),
            "amount_in_raw": amount_in_raw,
            "from_address": resolved_from_address,
            "to_address": resolved_to_address,
            "slippage": slippage,
            "allow_bridges": allow_bridges,
            "deny_bridges": deny_bridges,
            "prefer_bridges": prefer_bridges,
            "tool": payload.get("tool"),
            "tool_details": payload.get("toolDetails"),
            "action": payload.get("action"),
            "estimate": payload.get("estimate"),
            "included_steps": payload.get("includedSteps"),
            "transaction_request": payload.get("transactionRequest"),
            "quote": payload,
            "source": "lifi",
        }

    async def get_lifi_transfer_status(
        self,
        *,
        tx_hash: str,
        bridge: str | None = None,
        from_chain: str | None = None,
        to_chain: str | None = None,
    ) -> dict[str, Any]:
        payload = await lifi.fetch_transfer_status(
            tx_hash=tx_hash,
            bridge=bridge,
            from_chain=from_chain,
            to_chain=to_chain,
        )
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "tx_hash": tx_hash,
            "bridge": bridge,
            "from_chain": from_chain,
            "to_chain": to_chain,
            "status": payload.get("status"),
            "substatus": payload.get("substatus"),
            "sending": payload.get("sending"),
            "receiving": payload.get("receiving"),
            "transfer": payload,
            "source": "lifi",
        }

    def _build_lifi_fee_summary(self, *, quote: dict[str, Any]) -> dict[str, Any]:
        estimate = quote.get("estimate") if isinstance(quote.get("estimate"), dict) else {}
        fee_costs = [item for item in estimate.get("feeCosts") or [] if isinstance(item, dict)]
        gas_costs = [item for item in estimate.get("gasCosts") or [] if isinstance(item, dict)]
        return {
            "swap_provider": "lifi",
            "tool": quote.get("tool"),
            "tool_details": quote.get("toolDetails"),
            "fee_costs": fee_costs,
            "gas_costs": gas_costs,
            "execution_duration_seconds": estimate.get("executionDuration"),
            "from_amount_usd": estimate.get("fromAmountUSD"),
            "to_amount_usd": estimate.get("toAmountUSD"),
            "quoted_output_includes_route_fees": True,
        }

    def _lifi_token_metadata(self, token: Any, fallback_address: str) -> dict[str, Any]:
        raw = token if isinstance(token, dict) else {}
        decimals = _coerce_int(raw.get("decimals"))
        return {
            "address": str(raw.get("address") or fallback_address or "").strip(),
            "chain_id": raw.get("chainId"),
            "symbol": raw.get("symbol"),
            "name": raw.get("name"),
            "decimals": decimals,
            "coin_key": raw.get("coinKey"),
            "price_usd": raw.get("priceUSD"),
            "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else [],
            "source": "lifi",
        }

    def _format_lifi_amount(self, amount: Any, decimals: int | None) -> float | None:
        parsed = _coerce_positive_int_from_any(amount)
        if parsed is None or decimals is None or decimals < 0:
            return None
        return parsed / (10**decimals)

    def _normalize_solana_lifi_preview_payload(
        self,
        *,
        quote: dict[str, Any],
        owner: str,
        destination_chain_id: str,
        destination_chain: str,
        input_token: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None,
        allow_bridges: list[str] | None,
        deny_bridges: list[str] | None,
        prefer_bridges: list[str] | None,
    ) -> dict[str, Any]:
        action = quote.get("action") if isinstance(quote.get("action"), dict) else {}
        estimate = quote.get("estimate") if isinstance(quote.get("estimate"), dict) else {}
        transaction_request = quote.get("transactionRequest")
        transaction_data = (
            str(transaction_request.get("data") or "").strip()
            if isinstance(transaction_request, dict)
            else ""
        )
        normalized_input_token = lifi.normalize_token_address(input_token, chain_id="1151111081099710")
        normalized_output_token = lifi.normalize_token_address(output_token, chain_id=destination_chain_id)
        input_metadata = self._lifi_token_metadata(action.get("fromToken"), normalized_input_token)
        output_metadata = self._lifi_token_metadata(action.get("toToken"), normalized_output_token)
        input_decimals = input_metadata.get("decimals")
        output_decimals = output_metadata.get("decimals")
        estimated_output_amount_raw = str(estimate.get("toAmount") or "0")
        minimum_output_amount_raw = str(estimate.get("toAmountMin") or estimate.get("toAmount") or "0")
        quote_id = str(quote.get("id") or "").strip() or None
        transaction_id = str(quote.get("transactionId") or "").strip() or None
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "solana-lifi-cross-chain-swap",
            "owner": owner,
            "source_chain": "solana",
            "source_chain_id": "1151111081099710",
            "destination_chain": destination_chain,
            "destination_chain_id": destination_chain_id,
            "input_token": normalized_input_token,
            "input_mint": normalized_input_token,
            "output_token": normalized_output_token,
            "destination_address": destination_address,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": self._format_lifi_amount(amount_in_raw, input_decimals),
            "input_decimals": input_decimals,
            "input_symbol": input_metadata.get("symbol"),
            "estimated_output_amount_raw": estimated_output_amount_raw,
            "estimated_output_amount_ui": self._format_lifi_amount(
                estimated_output_amount_raw,
                output_decimals,
            ),
            "minimum_output_amount_raw": minimum_output_amount_raw,
            "minimum_output_amount_ui": self._format_lifi_amount(
                minimum_output_amount_raw,
                output_decimals,
            ),
            "output_decimals": output_decimals,
            "output_symbol": output_metadata.get("symbol"),
            "slippage": slippage,
            "allow_bridges": allow_bridges,
            "deny_bridges": deny_bridges,
            "prefer_bridges": prefer_bridges,
            "quote_type": quote.get("type"),
            "quote_id": quote_id,
            "transaction_id": transaction_id,
            "tool": quote.get("tool"),
            "tool_details": quote.get("toolDetails"),
            "fee_summary": self._build_lifi_fee_summary(quote=quote),
            "route_plan": quote.get("includedSteps") or [],
            "transaction_data_hash": (
                hashlib.sha256(transaction_data.encode("utf-8")).hexdigest()
                if transaction_data
                else None
            ),
            "input_token_metadata": input_metadata,
            "output_token_metadata": output_metadata,
            "swap_provider": "lifi",
            "can_send": self.get_capabilities().can_send_transaction,
            "sign_only": self.sign_only,
            "source": "lifi",
        }

    @staticmethod
    async def preview_solana_lifi_cross_chain_swap(
        self,
        *,
        input_token: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.network != "mainnet":
            raise WalletBackendError("LI.FI Solana-origin cross-chain swaps are only enabled for Solana mainnet.")
        amount_in_raw = _require_positive_integer_string(amount_in_raw, field_name="amount_in_raw")
        destination_chain_id = lifi.normalize_chain_id(destination_chain, field_name="destination_chain")
        if destination_chain_id == "1151111081099710":
            raise WalletBackendError("Use swap_solana_tokens for Solana-only swaps.")
        destination_chain_name = lifi.chain_name_for_id(destination_chain_id)
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if not isinstance(destination_address, str) or not destination_address.strip():
            raise WalletBackendError("destination_address is required.")

        quote = await lifi.fetch_quote(
            from_chain="solana",
            to_chain=destination_chain_id,
            from_token=input_token,
            to_token=output_token,
            amount_in_raw=amount_in_raw,
            from_address=owner,
            to_address=destination_address.strip(),
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        return self._normalize_solana_lifi_preview_payload(
            quote=quote,
            owner=owner,
            destination_chain_id=destination_chain_id,
            destination_chain=destination_chain_name,
            input_token=input_token,
            output_token=output_token,
            destination_address=destination_address.strip(),
            amount_in_raw=amount_in_raw,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )

    def _lifi_transaction_data_from_quote(self, quote: dict[str, Any]) -> str:
        transaction_request = quote.get("transactionRequest")
        if not isinstance(transaction_request, dict):
            raise WalletBackendError("LI.FI quote returned no Solana transactionRequest.")
        transaction_data = str(transaction_request.get("data") or "").strip()
        if not transaction_data:
            raise WalletBackendError("LI.FI quote returned no Solana transactionRequest.data.")
        return transaction_data

    async def _verify_solana_lifi_transaction(
        self,
        message: Any,
        *,
        wallet_address: str,
        input_token: str,
    ) -> dict[str, Any]:
        keys = [str(value) for value in getattr(message, "account_keys", []) or []]
        if not keys:
            raise WalletBackendError("LI.FI transaction does not include account keys.")
        header = getattr(message, "header", None)
        required_signature_count = int(getattr(header, "num_required_signatures", 0) or 0)
        if required_signature_count <= 0 or required_signature_count > len(keys):
            raise WalletBackendError("LI.FI transaction signer metadata is inconsistent.")
        required_signer_keys = keys[:required_signature_count]
        if wallet_address not in required_signer_keys:
            raise WalletBackendError(
                "LI.FI transaction does not require the connected wallet as an authorized signer."
            )
        if required_signature_count > 2:
            raise WalletBackendError(
                "LI.FI transaction requires unexpected additional signers and was rejected."
            )
        loaded_addresses = await self._resolve_versioned_message_lookup_addresses(message)
        all_keys = keys + loaded_addresses
        program_ids: list[str] = []
        for instruction in list(getattr(message, "instructions", []) or []):
            index = int(getattr(instruction, "program_id_index", -1))
            if index < 0 or index >= len(all_keys):
                raise WalletBackendError("LI.FI transaction contains an invalid program id index.")
            program_ids.append(all_keys[index])
        return {
            "wallet_address": wallet_address,
            "fee_payer": keys[0],
            "required_signer_keys": required_signer_keys,
            "required_signature_count": required_signature_count,
            "wallet_signer_index": required_signer_keys.index(wallet_address),
            "sponsored_fee_payer": keys[0] != wallet_address,
            "program_ids": program_ids,
            "non_core_program_ids": [
                pid
                for pid in program_ids
                if pid
                not in {
                    "11111111111111111111111111111111",
                    "ComputeBudget111111111111111111111111111111",
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
                    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
                    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
                    "AddressLookupTab1e1111111111111111111111111",
                }
            ],
            "account_key_count": len(all_keys),
            "instruction_count": len(list(getattr(message, "instructions", []) or [])),
            "input_token": input_token,
            "verified": True,
        }

    async def execute_solana_lifi_cross_chain_swap(
        self,
        *,
        input_token: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )
        amount_in_raw = _require_positive_integer_string(amount_in_raw, field_name="amount_in_raw")
        if not isinstance(destination_address, str) or not destination_address.strip():
            raise WalletBackendError("destination_address is required.")
        destination_address = destination_address.strip()
        preview = await self.preview_solana_lifi_cross_chain_swap(
            input_token=input_token,
            destination_chain=destination_chain,
            output_token=output_token,
            destination_address=destination_address,
            amount_in_raw=amount_in_raw,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        if minimum_output_amount_raw is not None:
            minimum_output_amount_raw = _require_positive_integer_string(
                minimum_output_amount_raw,
                field_name="minimum_output_amount_raw",
            )
            quoted_minimum = _coerce_positive_int_from_any(preview.get("minimum_output_amount_raw")) or 0
            if quoted_minimum < int(minimum_output_amount_raw):
                raise WalletBackendError(
                    "LI.FI quote changed below the approved minimum output. Generate a new preview and approval.",
                    code="swap_quote_changed",
                    details={
                        "approved_minimum_output_amount_raw": minimum_output_amount_raw,
                        "quoted_minimum_output_amount_raw": str(quoted_minimum),
                    },
                )

        quote = await lifi.fetch_quote(
            from_chain="solana",
            to_chain=str(preview["destination_chain_id"]),
            from_token=input_token,
            to_token=output_token,
            amount_in_raw=amount_in_raw,
            from_address=str(preview["owner"]),
            to_address=destination_address,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        final_preview = self._normalize_solana_lifi_preview_payload(
            quote=quote,
            owner=str(preview["owner"]),
            destination_chain_id=str(preview["destination_chain_id"]),
            destination_chain=str(preview["destination_chain"]),
            input_token=input_token,
            output_token=output_token,
            destination_address=destination_address,
            amount_in_raw=amount_in_raw,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        if minimum_output_amount_raw is not None:
            quoted_minimum = _coerce_positive_int_from_any(final_preview.get("minimum_output_amount_raw")) or 0
            if quoted_minimum < int(minimum_output_amount_raw):
                raise WalletBackendError(
                    "LI.FI quote changed below the approved minimum output. Generate a new preview and approval.",
                    code="swap_quote_changed",
                    details={
                        "approved_minimum_output_amount_raw": minimum_output_amount_raw,
                        "quoted_minimum_output_amount_raw": str(quoted_minimum),
                    },
                )
        transaction_data = self._lifi_transaction_data_from_quote(quote)
        try:
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for LI.FI transaction signing."
            ) from exc
        try:
            unsigned_transaction = VersionedTransaction.from_bytes(base64.b64decode(transaction_data))
        except Exception as exc:
            raise WalletBackendError("LI.FI Solana transaction could not be decoded.") from exc
        verification = await self._verify_solana_lifi_transaction(
            unsigned_transaction.message,
            wallet_address=str(final_preview["owner"]),
            input_token=str(final_preview["input_token"]),
        )
        signed_transaction_base64 = await self._sign_versioned_provider_transaction(
            transaction_base64=transaction_data,
            wallet_signer_index=int(verification.get("wallet_signer_index") or 0),
        )
        simulation = await solana_rpc.simulate_transaction(
            transaction_base64=signed_transaction_base64,
            rpc_url=self.rpc_urls,
            commitment=self.commitment,
        )
        simulation_value = simulation.get("value") if isinstance(simulation.get("value"), dict) else {}
        if isinstance(simulation_value, dict) and simulation_value.get("err") is not None:
            raise WalletBackendError(
                "LI.FI Solana transaction simulation failed.",
                code="transaction_simulation_failed",
                details={"simulation": simulation_value},
            )
        submitted = await solana_rpc.send_transaction(
            transaction_base64=signed_transaction_base64,
            rpc_url=self.rpc_urls,
        )
        signature = str(submitted.get("signature") or "").strip()
        status = None
        if signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
            )
        return {
            **final_preview,
            "mode": "execute",
            "signature": signature or None,
            "source_tx_hash": signature or None,
            "broadcasted": bool(signature),
            "confirmed": status is not None,
            "confirmation_status": status.get("confirmationStatus") if status else None,
            "slot": status.get("slot") if status else None,
            "simulation": simulation_value,
            "verification": verification,
            "execute_response": submitted,
            "quote_id": quote.get("id") or preview.get("quote_id"),
            "transaction_id": quote.get("transactionId") or preview.get("transaction_id"),
            "source": "lifi",
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
            self._get_native_balance(stake_account),
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
        platform_fee = quote_response.get("platformFee")
        fee_bps = _coerce_int(quote_response.get("feeBps"))
        if fee_bps is None and isinstance(platform_fee, dict):
            fee_bps = _coerce_int(platform_fee.get("feeBps"))
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

    def _swap_fee_lamports(self, payload: dict[str, Any]) -> int | None:
        fee_summary = payload.get("fee_summary")
        if isinstance(fee_summary, dict):
            network_fee = _coerce_int(fee_summary.get("network_fee_lamports"))
            if network_fee is not None:
                return network_fee
        return None

    def _default_swap_intent_max_fee_lamports(self, fee_summary: dict[str, Any]) -> int:
        estimated_fee = _coerce_int(fee_summary.get("network_fee_lamports")) or 0
        return max(
            estimated_fee * 3,
            estimated_fee + 100_000,
            SOLANA_SWAP_INTENT_DEFAULT_MAX_FEE_LAMPORTS,
        )

    def _swap_minimum_output_floor(self, *, out_amount_raw: int, slippage_bps: int) -> int:
        if out_amount_raw <= 0:
            return 0
        if slippage_bps <= 0:
            raise WalletBackendError("slippage_bps must be greater than zero.")
        return max(1, (out_amount_raw * max(0, 10_000 - slippage_bps)) // 10_000)

    def _require_mainnet_bags(self, feature: str) -> None:
        if self.network != "mainnet":
            raise WalletBackendError(f"{feature} is only enabled for Solana mainnet.")

    def _normalize_bags_claimers(self, claimers: list[str]) -> list[str]:
        if not isinstance(claimers, list) or not claimers:
            raise WalletBackendError("claimers must be a non-empty array of Solana wallet addresses.")
        if len(claimers) > 100:
            raise WalletBackendError("Bags fee share supports at most 100 claimers.")
        normalized: list[str] = []
        for raw in claimers:
            if not isinstance(raw, str) or not raw.strip():
                raise WalletBackendError(
                    "claimers must be a non-empty array of Solana wallet addresses."
                )
            normalized.append(validate_solana_address(raw.strip()))
        return normalized

    def _normalize_bags_basis_points(self, basis_points: list[int]) -> list[int]:
        if not isinstance(basis_points, list) or not basis_points:
            raise WalletBackendError("basis_points must be a non-empty array of integers.")
        normalized = [
            _coerce_non_negative_integer(value, field_name="basis_points")
            for value in basis_points
        ]
        if sum(normalized) != 10_000:
            raise WalletBackendError("basis_points must sum to exactly 10000.")
        return normalized

    def _bags_decode_serialized_transaction_bytes(self, serialized_transaction: str) -> bytes:
        serialized = str(serialized_transaction).strip()
        if not serialized:
            raise WalletBackendError("Bags serialized transaction is empty.")
        try:
            return base64.b64decode(serialized, validate=True)
        except (ValueError, binascii.Error):
            return b58decode(serialized)

    def _bags_extract_serialized_transaction_string(self, payload: Any) -> str:
        if isinstance(payload, str):
            cleaned = payload.strip()
            return cleaned if cleaned else ""
        if isinstance(payload, dict):
            for key in ("transaction", "tx", "response"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _bags_extract_serialized_transaction_strings(self, payload: Any) -> list[str]:
        if isinstance(payload, str):
            cleaned = payload.strip()
            return [cleaned] if cleaned else []
        if isinstance(payload, list):
            normalized: list[str] = []
            for item in payload:
                value = self._bags_extract_serialized_transaction_string(item)
                if value:
                    normalized.append(value)
            return normalized
        if isinstance(payload, dict):
            normalized: list[str] = []
            for key in ("transactions", "txs", "responses"):
                value = payload.get(key)
                if isinstance(value, list):
                    normalized.extend(self._bags_extract_serialized_transaction_strings(value))
            for key in (
                "transaction",
                "launchTransaction",
                "serializedTransaction",
                "swapTransaction",
                "response",
                "tx",
            ):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    normalized.append(value.strip())
            return normalized
        return []

    def _bags_extract_fee_share_config_transaction_strings(self, payload: Any) -> list[str]:
        if not isinstance(payload, dict):
            return self._bags_extract_serialized_transaction_strings(payload)
        transaction_strings: list[str] = []
        transactions = payload.get("transactions")
        if isinstance(transactions, list):
            transaction_strings.extend(self._bags_extract_serialized_transaction_strings(transactions))
        bundles = payload.get("bundles")
        if isinstance(bundles, list):
            for bundle in bundles:
                if isinstance(bundle, list):
                    transaction_strings.extend(self._bags_extract_serialized_transaction_strings(bundle))
                else:
                    value = self._bags_extract_serialized_transaction_string(bundle)
                    if value:
                        transaction_strings.append(value)
        return transaction_strings

    def _bags_extract_transaction_base64s(self, payload: Any) -> list[str]:
        def _normalize(item: Any) -> list[str]:
            if isinstance(item, str):
                cleaned = item.strip()
                return [cleaned] if cleaned else []
            if isinstance(item, list):
                normalized: list[str] = []
                for value in item:
                    normalized.extend(_normalize(value))
                return normalized
            if isinstance(item, dict):
                for key in ("tx", "transaction", "serializedTransaction", "swapTransaction", "launchTransaction"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        return [value.strip()]
                for key in ("transactions", "claimTransactions", "txs", "responses", "response"):
                    value = item.get(key)
                    if isinstance(value, (list, dict, str)):
                        normalized = _normalize(value)
                        if normalized:
                            return normalized
            return []

        return _normalize(payload)

    def _bags_extract_token_info_fields(self, payload: Any) -> tuple[str, str]:
        if not isinstance(payload, dict):
            raise WalletBackendError("Bags token info response is missing metadata fields.")
        token_mint = str(payload.get("tokenMint") or "").strip()
        token_launch = payload.get("tokenLaunch") if isinstance(payload.get("tokenLaunch"), dict) else {}
        token_metadata = payload.get("tokenMetadata")
        metadata_candidates: list[Any] = [
            token_launch.get("uri") if isinstance(token_launch.get("uri"), str) else None,
            token_launch.get("ipfs") if isinstance(token_launch.get("ipfs"), str) else None,
            token_launch.get("metadataUri") if isinstance(token_launch.get("metadataUri"), str) else None,
            token_metadata if isinstance(token_metadata, str) else None,
            token_metadata.get("uri") if isinstance(token_metadata, dict) else None,
            token_metadata.get("ipfs") if isinstance(token_metadata, dict) else None,
            token_metadata.get("metadataUri") if isinstance(token_metadata, dict) else None,
            payload.get("ipfs") if isinstance(payload.get("ipfs"), str) else None,
            payload.get("metadataUri") if isinstance(payload.get("metadataUri"), str) else None,
            payload.get("uri") if isinstance(payload.get("uri"), str) else None,
        ]
        ipfs = next((str(candidate).strip() for candidate in metadata_candidates if isinstance(candidate, str) and candidate.strip()), "")
        if not token_mint:
            raise WalletBackendError("Bags token info response is missing tokenMint.")
        if not ipfs:
            raise WalletBackendError("Bags token info response is missing metadata reference.")
        return token_mint, ipfs

    def _bags_extract_config_key(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            raise WalletBackendError("Bags fee share config response is missing config key.")
        config_key = str(
            payload.get("meteoraConfigKey")
            or payload.get("configKey")
            or payload.get("key")
            or ""
        ).strip()
        if not config_key:
            raise WalletBackendError("Bags fee share config response is missing config key.")
        return config_key

    async def _prepare_bags_transactions(
        self,
        *,
        transaction_base64s: list[str],
        token_mint: str,
        action: str,
        owner: str,
        asset_type: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        if not transaction_base64s:
            raise WalletBackendError(f"{action} did not return any transactions.")
        try:
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Bags transaction signing."
            ) from exc

        signed_transactions: list[str] = []
        verifications: list[dict[str, Any]] = []
        for transaction_base64 in transaction_base64s:
            unsigned_transaction = VersionedTransaction.from_bytes(
                self._bags_decode_serialized_transaction_bytes(transaction_base64)
            )
            loaded_addresses = await self._resolve_versioned_message_lookup_addresses(
                unsigned_transaction.message
            )
            verification = verify_provider_bags_transaction(
                unsigned_transaction.message,
                wallet_address=owner,
                token_mint=token_mint,
                action=action,
                loaded_addresses=loaded_addresses,
            )
            signed_transactions.append(
                await self._sign_versioned_provider_transaction(
                    transaction_base64=transaction_base64,
                    wallet_signer_index=int(verification.get("wallet_signer_index") or 0),
                )
            )
            verifications.append(verification)

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": asset_type,
            "owner": owner,
            "token_mint": token_mint,
            "transaction_count": len(signed_transactions),
            "transactions_base64": signed_transactions,
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "verification": verifications[0] if len(verifications) == 1 else None,
            "verifications": verifications,
            "sign_only": self.sign_only,
            "source": "bags",
            **extra,
        }

    async def _execute_prepared_bags_transactions(
        self,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )
        serialized = prepared.get("transactions_base64")
        if not isinstance(serialized, list) or not serialized:
            raise WalletBackendError("Prepared Bags transaction payload is missing transactions.")

        signatures: list[str] = []
        statuses: list[dict[str, Any] | None] = []
        for transaction_base64 in serialized:
            submitted = await solana_rpc.send_transaction(
                transaction_base64=str(transaction_base64),
                rpc_url=self.rpc_urls,
            )
            signature = str(submitted.get("signature") or "").strip()
            signatures.append(signature)
            status = None
            if signature:
                status = await solana_rpc.wait_for_confirmation(
                    signature=signature,
                    rpc_url=self.rpc_urls,
                )
            statuses.append(status)

        confirmed = all(status is not None for status in statuses)
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": prepared["asset_type"],
            "owner": prepared.get("owner"),
            "token_mint": prepared.get("token_mint"),
            "transaction_count": len(serialized),
            "signatures": signatures,
            "signature": signatures[0] if len(signatures) == 1 else None,
            "broadcasted": any(bool(item) for item in signatures),
            "confirmed": confirmed,
            "confirmation_statuses": [
                status.get("confirmationStatus") if status else None for status in statuses
            ],
            "slots": [status.get("slot") if status else None for status in statuses],
            "verification": prepared.get("verification"),
            "verifications": prepared.get("verifications"),
            "source": "bags",
        }

    def _require_mainnet_jupiter(self, feature: str) -> None:
        if self.network != "mainnet":
            raise WalletBackendError(f"{feature} is only enabled for Solana mainnet.")

    def _require_mainnet_flash(self, feature: str) -> None:
        if self.network != "mainnet":
            raise WalletBackendError(f"{feature} is only enabled for Solana mainnet.")

    def _require_mainnet_kamino(self, feature: str) -> None:
        if self.network != "mainnet":
            raise WalletBackendError(f"{feature} is only enabled for Solana mainnet.")

    async def get_flash_trade_markets(
        self,
        pool_name: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_flash("Flash Trade")
        normalized_pool_name: str | None = None
        if pool_name is not None:
            if not isinstance(pool_name, str) or not pool_name.strip():
                raise WalletBackendError("pool_name must be a non-empty string when provided.")
            normalized_pool_name = pool_name.strip()
        try:
            data = await flash.fetch_markets(pool_name=normalized_pool_name)
        except ProviderError:
            data = await flash_sdk_bridge.get_markets(
                pool_name=normalized_pool_name,
                network=self.network,
            )
        markets = data.get("markets")
        if not isinstance(markets, list):
            markets = []
        return {
            "chain": "solana",
            "network": self.network,
            "pool_name": normalized_pool_name,
            "market_count": len(markets),
            "markets": markets,
            "raw": data,
            "source": str(data.get("source") or "flash-trade"),
        }

    async def get_flash_trade_positions(
        self,
        owner: str | None = None,
        pool_name: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_flash("Flash Trade")
        wallet_address = owner or self.address
        if not wallet_address:
            raise WalletBackendError(
                "A wallet address is required for Flash Trade position lookup."
            )
        wallet_address = validate_solana_address(wallet_address)
        normalized_pool_name: str | None = None
        if pool_name is not None:
            if not isinstance(pool_name, str) or not pool_name.strip():
                raise WalletBackendError("pool_name must be a non-empty string when provided.")
            normalized_pool_name = pool_name.strip()
        try:
            data = await flash.fetch_positions(
                owner=wallet_address,
                pool_name=normalized_pool_name,
            )
        except ProviderError:
            data = await flash_sdk_bridge.get_positions(
                owner=wallet_address,
                pool_name=normalized_pool_name,
                network=self.network,
            )
        positions = data.get("positions")
        if not isinstance(positions, list):
            positions = []
        return {
            "chain": "solana",
            "network": self.network,
            "owner": wallet_address,
            "pool_name": normalized_pool_name,
            "position_count": len(positions),
            "positions": positions,
            "raw": data,
            "source": str(data.get("source") or "flash-trade"),
        }

    async def preview_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
    ) -> dict[str, Any]:
        self._require_mainnet_flash("Flash Trade")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        normalized_pool_name = str(pool_name).strip()
        if not normalized_pool_name:
            raise WalletBackendError("pool_name is required.")
        normalized_market_symbol = _normalize_flash_symbol(
            market_symbol,
            field_name="market_symbol",
        )
        normalized_collateral_symbol = _normalize_flash_symbol(
            collateral_symbol,
            field_name="collateral_symbol",
        )
        normalized_collateral_amount_raw = _require_positive_integer_string(
            collateral_amount_raw,
            field_name="collateral_amount_raw",
        )
        normalized_leverage = _require_positive_decimal_string(leverage, field_name="leverage")
        normalized_side = _normalize_flash_side(side)
        market_snapshot = await self.get_flash_trade_markets(pool_name=normalized_pool_name)
        matching_market = next(
            (
                item
                for item in market_snapshot["markets"]
                if isinstance(item, dict)
                and str(item.get("market_symbol") or item.get("symbol") or "").strip().upper()
                == normalized_market_symbol
                and str(item.get("side") or "").strip().lower() == normalized_side
                and str(item.get("collateral_symbol") or "").strip().upper()
                == normalized_collateral_symbol
            ),
            None,
        )
        if matching_market is None:
            raise WalletBackendError(
                "Requested Flash market is not available in the selected pool for the requested collateral and side."
            )
        bridge_preview = await flash_sdk_bridge.preview_open_position(
            owner=owner,
            pool_name=normalized_pool_name,
            market_symbol=normalized_market_symbol,
            collateral_symbol=normalized_collateral_symbol,
            collateral_amount_raw=normalized_collateral_amount_raw,
            leverage=normalized_leverage,
            side=normalized_side,
            network=self.network,
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "flash-trade-open-position",
            "owner": owner,
            "pool_name": normalized_pool_name,
            "market_symbol": normalized_market_symbol,
            "collateral_symbol": normalized_collateral_symbol,
            "collateral_amount_raw": normalized_collateral_amount_raw,
            "leverage": normalized_leverage,
            "side": normalized_side,
            "market": matching_market,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "flash-sdk-bridge",
            **bridge_preview,
        }

    async def preview_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
    ) -> dict[str, Any]:
        self._require_mainnet_flash("Flash Trade")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        normalized_pool_name = str(pool_name).strip()
        if not normalized_pool_name:
            raise WalletBackendError("pool_name is required.")
        normalized_market_symbol = _normalize_flash_symbol(
            market_symbol,
            field_name="market_symbol",
        )
        normalized_side = _normalize_flash_side(side)
        positions_snapshot = await self.get_flash_trade_positions(
            owner=owner,
            pool_name=normalized_pool_name,
        )
        matching_position = next(
            (
                item
                for item in positions_snapshot["positions"]
                if isinstance(item, dict)
                and str(item.get("symbol") or item.get("marketSymbol") or "").strip().upper()
                == normalized_market_symbol
                and str(item.get("side") or "").strip().lower() == normalized_side
            ),
            None,
        )
        if matching_position is None:
            raise WalletBackendError(
                "No matching Flash position was found for the selected market, side, and pool."
            )
        bridge_preview = await flash_sdk_bridge.preview_close_position_same_collateral(
            owner=owner,
            pool_name=normalized_pool_name,
            market_symbol=normalized_market_symbol,
            side=normalized_side,
            network=self.network,
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "flash-trade-close-position",
            "owner": owner,
            "pool_name": normalized_pool_name,
            "market_symbol": normalized_market_symbol,
            "side": normalized_side,
            "position": matching_position,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "flash-sdk-bridge",
            **bridge_preview,
        }

    async def _prepare_flash_trade_transaction(
        self,
        *,
        preview: dict[str, Any],
        bridge_prepared: dict[str, Any],
        action: str,
        asset_type: str,
    ) -> dict[str, Any]:
        bridge_mode = str(bridge_prepared.get("bridge_mode") or "").strip().lower()
        if bridge_mode == "mock":
            prepared = {
                "chain": "solana",
                "network": self.network,
                "mode": "prepare",
                "asset_type": asset_type,
                "owner": preview.get("owner"),
                "pool_name": preview.get("pool_name"),
                "market_symbol": preview.get("market_symbol"),
                "collateral_symbol": preview.get("collateral_symbol"),
                "collateral_amount_raw": preview.get("collateral_amount_raw"),
                "leverage": preview.get("leverage"),
                "side": preview.get("side"),
                "signed": False,
                "broadcasted": False,
                "confirmed": False,
                "sign_only": self.sign_only,
                "source": "flash-sdk-bridge",
                "bridge_mode": "mock",
                "mock_prepare_only": True,
                "mock_warning": (
                    f"{action} is running in FLASH_SDK_BRIDGE_MODE=mock. "
                    "Prepare returns a dry-run execution plan only; execute is disabled until the bridge runs in real mode."
                ),
                "build_response": bridge_prepared,
            }
            for key in (
                "estimated_size_usd",
                "estimated_size_amount_raw",
                "estimated_collateral_usd",
                "estimated_collateral_amount_raw",
                "estimated_entry_price",
                "estimated_liquidation_price",
                "estimated_entry_fee_usd",
                "estimated_total_fee_usd",
                "estimated_fee_rate_bps",
                "estimated_available_liquidity_usd",
                "estimated_borrow_fee_rate",
                "position_size_usd",
                "position_size_amount_raw",
                "close_amount_raw",
                "estimated_receive_amount_usd",
                "estimated_mark_price",
                "estimated_existing_liquidation_price",
                "estimated_new_liquidation_price",
                "estimated_profit_usd",
                "estimated_loss_usd",
                "estimated_settled_pnl_usd",
                "estimated_exit_fee_usd",
                "estimated_total_fees_usd",
                "estimated_existing_leverage",
                "estimated_new_leverage",
                "is_profitable",
                "is_solvent",
                "is_partial_close",
                "position_pubkey",
            ):
                if key in preview:
                    prepared[key] = preview[key]
            return prepared

        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        try:
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Flash Trade transaction signing."
            ) from exc

        owner = str(preview.get("owner") or await self.get_address() or "").strip()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        transaction_base64 = str(bridge_prepared.get("transaction_base64") or "").strip()
        if not transaction_base64:
            raise WalletBackendError(f"{action} bridge response is missing transaction_base64.")

        unsigned_transaction = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))
        loaded_addresses = await self._resolve_versioned_message_lookup_addresses(
            unsigned_transaction.message
        )
        market_address = validate_solana_address(str(bridge_prepared.get("market_address") or ""))
        target_custody_address = validate_solana_address(
            str(bridge_prepared.get("target_custody_address") or "")
        )
        collateral_custody_address = validate_solana_address(
            str(bridge_prepared.get("collateral_custody_address") or "")
        )
        position_address_raw = str(bridge_prepared.get("position_address") or "").strip() or None
        collateral_mint_raw = str(bridge_prepared.get("collateral_mint") or "").strip() or None
        expected_program_ids_raw = bridge_prepared.get("expected_program_ids")
        if not isinstance(expected_program_ids_raw, list) or not expected_program_ids_raw:
            raise WalletBackendError(f"{action} bridge response is missing expected_program_ids.")
        expected_program_ids = [
            validate_solana_address(str(value))
            for value in expected_program_ids_raw
            if str(value).strip()
        ]
        verification = verify_provider_flash_transaction(
            unsigned_transaction.message,
            wallet_address=owner,
            market_address=market_address,
            target_custody_address=target_custody_address,
            collateral_custody_address=collateral_custody_address,
            action=action,
            expected_program_ids=expected_program_ids,
            position_address=(
                validate_solana_address(position_address_raw)
                if position_address_raw is not None
                else None
            ),
            collateral_mint=(
                validate_solana_mint(collateral_mint_raw)
                if collateral_mint_raw is not None
                else None
            ),
            loaded_addresses=loaded_addresses,
        )
        signed_transaction_base64 = await self._sign_versioned_provider_transaction(
            transaction_base64=transaction_base64,
            wallet_signer_index=int(verification.get("wallet_signer_index") or 0),
        )
        prepared = {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": asset_type,
            "owner": owner,
            "pool_name": preview.get("pool_name"),
            "market_symbol": preview.get("market_symbol"),
            "collateral_symbol": preview.get("collateral_symbol"),
            "collateral_amount_raw": preview.get("collateral_amount_raw"),
            "leverage": preview.get("leverage"),
            "side": preview.get("side"),
            "transaction_base64": signed_transaction_base64,
            "transaction_encoding": str(bridge_prepared.get("transaction_encoding") or "base64"),
            "transaction_format": str(bridge_prepared.get("transaction_format") or "versioned"),
            "last_valid_block_height": bridge_prepared.get("last_valid_block_height"),
            "latest_blockhash": bridge_prepared.get("latest_blockhash"),
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "verification": verification,
            "sign_only": self.sign_only,
            "source": "flash-sdk-bridge",
            "build_response": bridge_prepared,
        }
        for key in (
            "estimated_size_usd",
            "estimated_size_amount_raw",
            "estimated_collateral_usd",
            "estimated_collateral_amount_raw",
            "estimated_entry_price",
            "estimated_liquidation_price",
            "estimated_entry_fee_usd",
            "estimated_total_fee_usd",
            "estimated_fee_rate_bps",
            "estimated_available_liquidity_usd",
            "estimated_borrow_fee_rate",
            "position_size_usd",
            "position_size_amount_raw",
            "close_amount_raw",
            "estimated_receive_amount_usd",
            "estimated_mark_price",
            "estimated_existing_liquidation_price",
            "estimated_new_liquidation_price",
            "estimated_profit_usd",
            "estimated_loss_usd",
            "estimated_settled_pnl_usd",
            "estimated_exit_fee_usd",
            "estimated_total_fees_usd",
            "estimated_existing_leverage",
            "estimated_new_leverage",
            "is_profitable",
            "is_solvent",
            "is_partial_close",
            "position_pubkey",
        ):
            if key in preview:
                prepared[key] = preview[key]
        return prepared

    async def prepare_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
    ) -> dict[str, Any]:
        preview = await self.preview_flash_trade_open_position(
            pool_name=pool_name,
            market_symbol=market_symbol,
            collateral_symbol=collateral_symbol,
            collateral_amount_raw=collateral_amount_raw,
            leverage=leverage,
            side=side,
        )
        bridge_prepared = await flash_sdk_bridge.prepare_open_position(
            owner=str(preview["owner"]),
            pool_name=str(preview["pool_name"]),
            market_symbol=str(preview["market_symbol"]),
            collateral_symbol=str(preview["collateral_symbol"]),
            collateral_amount_raw=str(preview["collateral_amount_raw"]),
            leverage=str(preview["leverage"]),
            side=str(preview["side"]),
            network=self.network,
        )
        return await self._prepare_flash_trade_transaction(
            preview=preview,
            bridge_prepared=bridge_prepared,
            action="Flash Trade open position",
            asset_type="flash-trade-open-position",
        )

    async def _prepare_flash_trade_open_position_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        bridge_prepared = await flash_sdk_bridge.prepare_open_position(
            owner=str(preview["owner"]),
            pool_name=str(preview["pool_name"]),
            market_symbol=str(preview["market_symbol"]),
            collateral_symbol=str(preview["collateral_symbol"]),
            collateral_amount_raw=str(preview["collateral_amount_raw"]),
            leverage=str(preview["leverage"]),
            side=str(preview["side"]),
            network=self.network,
        )
        return await self._prepare_flash_trade_transaction(
            preview=preview,
            bridge_prepared=bridge_prepared,
            action="Flash Trade open position",
            asset_type="flash-trade-open-position",
        )

    async def prepare_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
    ) -> dict[str, Any]:
        preview = await self.preview_flash_trade_close_position(
            pool_name=pool_name,
            market_symbol=market_symbol,
            side=side,
        )
        bridge_prepared = await flash_sdk_bridge.prepare_close_position_same_collateral(
            owner=str(preview["owner"]),
            pool_name=str(preview["pool_name"]),
            market_symbol=str(preview["market_symbol"]),
            side=str(preview["side"]),
            network=self.network,
        )
        return await self._prepare_flash_trade_transaction(
            preview=preview,
            bridge_prepared=bridge_prepared,
            action="Flash Trade close position",
            asset_type="flash-trade-close-position",
        )

    async def _prepare_flash_trade_close_position_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        bridge_prepared = await flash_sdk_bridge.prepare_close_position_same_collateral(
            owner=str(preview["owner"]),
            pool_name=str(preview["pool_name"]),
            market_symbol=str(preview["market_symbol"]),
            side=str(preview["side"]),
            network=self.network,
        )
        return await self._prepare_flash_trade_transaction(
            preview=preview,
            bridge_prepared=bridge_prepared,
            action="Flash Trade close position",
            asset_type="flash-trade-close-position",
        )

    async def _execute_prepared_flash_trade_transaction(
        self,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        if str(prepared.get("bridge_mode") or "").strip().lower() == "mock":
            raise WalletBackendError(
                "Flash Trade execute is unavailable while FLASH_SDK_BRIDGE_MODE=mock. Switch the Flash SDK bridge to real mode first."
            )
        result = await self._execute_prepared_provider_transaction(
            prepared,
            source="flash-sdk-bridge",
        )
        for key in (
            "pool_name",
            "market_symbol",
            "collateral_symbol",
            "collateral_amount_raw",
            "leverage",
            "side",
            "estimated_size_usd",
            "estimated_size_amount_raw",
            "estimated_collateral_usd",
            "estimated_collateral_amount_raw",
            "estimated_entry_price",
            "estimated_liquidation_price",
            "estimated_entry_fee_usd",
            "estimated_total_fee_usd",
            "position_size_usd",
            "position_size_amount_raw",
            "close_amount_raw",
            "estimated_receive_amount_usd",
            "estimated_mark_price",
            "estimated_existing_liquidation_price",
            "estimated_new_liquidation_price",
            "estimated_profit_usd",
            "estimated_loss_usd",
            "estimated_settled_pnl_usd",
            "estimated_exit_fee_usd",
            "estimated_total_fees_usd",
            "position_pubkey",
            "verification",
        ):
            if key in prepared:
                result[key] = prepared[key]
        if "build_response" in prepared:
            result["build_response"] = prepared["build_response"]
        return result

    async def execute_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = (
            dict(approved_preview)
            if isinstance(approved_preview, dict)
            else await self.preview_flash_trade_open_position(
                pool_name=pool_name,
                market_symbol=market_symbol,
                collateral_symbol=collateral_symbol,
                collateral_amount_raw=collateral_amount_raw,
                leverage=leverage,
                side=side,
            )
        )
        prepared = await self._prepare_flash_trade_open_position_from_preview(preview)
        return await self._execute_prepared_flash_trade_transaction(prepared)

    async def execute_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = (
            dict(approved_preview)
            if isinstance(approved_preview, dict)
            else await self.preview_flash_trade_close_position(
                pool_name=pool_name,
                market_symbol=market_symbol,
                side=side,
            )
        )
        prepared = await self._prepare_flash_trade_close_position_from_preview(preview)
        return await self._execute_prepared_flash_trade_transaction(prepared)

    async def get_kamino_portfolio(self, user: str | None = None) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino portfolio")
        wallet_address = user or self.address
        if not wallet_address:
            raise WalletBackendError("A wallet address is required for Kamino portfolio lookup.")
        wallet_address = validate_solana_address(wallet_address)
        data = await kamino.fetch_portfolio(user=wallet_address)

        sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}

        def _section_items(key: str) -> list[Any]:
            value = data.get(key)
            return value if isinstance(value, list) else []

        lending = _section_items("lending")
        multiply = _section_items("multiply")
        leverage = _section_items("leverage")
        liquidity = _section_items("liquidity")
        earn = _section_items("earn")
        private_credit = _section_items("privateCredit")
        staking = _section_items("staking")

        return {
            "chain": "solana",
            "network": self.network,
            "user": wallet_address,
            "timestamp": data.get("timestamp"),
            "sections": sections,
            "lending_count": len(lending),
            "multiply_count": len(multiply),
            "leverage_count": len(leverage),
            "liquidity_count": len(liquidity),
            "earn_count": len(earn),
            "private_credit_count": len(private_credit),
            "staking_count": len(staking),
            "position_count": (
                len(lending)
                + len(multiply)
                + len(leverage)
                + len(liquidity)
                + len(earn)
                + len(private_credit)
                + len(staking)
            ),
            "lending": lending,
            "multiply": multiply,
            "leverage": leverage,
            "liquidity": liquidity,
            "earn": earn,
            "private_credit": private_credit,
            "staking": staking,
            "raw": data,
            "source": "kamino",
        }

    @staticmethod
    def _kamino_vault_summary(entry: Any) -> dict[str, Any] | None:
        """Compact one raw /kvaults entry (address + full on-chain state dump)
        into the fields an agent needs for discovery. The raw state is ~2 KB
        per vault and carries no yield data, so passing it through verbatim
        only burns agent context."""
        if not isinstance(entry, dict):
            return None
        address = _kamino_entry_address(entry, "address")
        state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
        if not address:
            return None

        def _int_or_none(value: Any) -> int | None:
            try:
                return int(str(value))
            except (TypeError, ValueError):
                return None

        return {
            "vault": address,
            "name": str(state.get("name") or "").strip() or None,
            "token_mint": str(state.get("tokenMint") or "").strip() or None,
            "shares_mint": str(state.get("sharesMint") or "").strip() or None,
            "management_fee_bps": _int_or_none(state.get("managementFeeBps")),
            "performance_fee_bps": _int_or_none(state.get("performanceFeeBps")),
            "min_deposit_amount": str(state.get("minDepositAmount") or "0"),
            "creation_timestamp": _int_or_none(state.get("creationTimestamp")),
            "prev_aum_raw": str(state.get("prevAum") or "0"),
        }

    @staticmethod
    def _kamino_vault_metrics_summary(metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "apy": metrics.get("apy"),
            "apy_actual": metrics.get("apyActual"),
            "apy_7d": metrics.get("apy7d"),
            "apy_30d": metrics.get("apy30d"),
            "apy_farm_rewards": metrics.get("apyFarmRewards"),
            "tokens_invested_usd": metrics.get("tokensInvestedUsd"),
            "tokens_available_usd": metrics.get("tokensAvailableUsd"),
            "share_price": metrics.get("sharePrice"),
            "number_of_holders": metrics.get("numberOfHolders"),
        }

    async def get_kamino_vaults(
        self,
        vault_address: str | None = None,
        token_mint: str | None = None,
        include_metrics: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino Earn")

        if isinstance(vault_address, str) and vault_address.strip():
            vault_address = validate_solana_address(vault_address.strip())
            data = await kamino.fetch_earn_vaults()
            entries = data.get("vaults") if isinstance(data.get("vaults"), list) else []
            summary = next(
                (
                    candidate
                    for entry in entries
                    if (candidate := self._kamino_vault_summary(entry))
                    and candidate["vault"] == vault_address
                ),
                None,
            )
            if summary is None:
                raise WalletBackendError(f"No Kamino Earn vault matched: {vault_address}")
            metrics = await kamino.fetch_earn_vault_metrics(
                vault=vault_address, network=self.network
            )
            summary["metrics"] = self._kamino_vault_metrics_summary(metrics)
            return {
                "chain": "solana",
                "network": self.network,
                "vault_count": 1,
                "vaults": [summary],
                "source": "kamino",
            }

        max_limit = 100
        effective_limit = 50
        if limit is not None:
            if not isinstance(limit, int) or limit <= 0:
                raise WalletBackendError("limit must be a positive integer.")
            effective_limit = min(limit, max_limit)

        mint_filter = None
        if isinstance(token_mint, str) and token_mint.strip():
            mint_filter = validate_solana_address(token_mint.strip())

        data = await kamino.fetch_earn_vaults()
        entries = data.get("vaults") if isinstance(data.get("vaults"), list) else []
        summaries = [
            summary
            for entry in entries
            if (summary := self._kamino_vault_summary(entry)) is not None
        ]
        total_count = len(summaries)
        if mint_filter:
            summaries = [item for item in summaries if item["token_mint"] == mint_filter]

        def _aum_key(item: dict[str, Any]) -> float:
            # prevAum is a decimal string on active vaults (e.g.
            # "21724442402923.2067…"); parsing it as int would throw on the
            # fractional part and sink every production vault to rank 0.
            try:
                return float(item["prev_aum_raw"])
            except (TypeError, ValueError):
                return 0.0

        # prevAum is in raw token units, so it is only a rough pre-rank across
        # mixed mints; with a token_mint filter it is directly comparable.
        summaries.sort(key=_aum_key, reverse=True)

        metrics_errors: list[dict[str, Any]] = []
        if include_metrics:
            candidates = summaries[: min(effective_limit, KAMINO_EARN_METRICS_FETCH_LIMIT)]
            semaphore = asyncio.Semaphore(KAMINO_OPEN_POSITIONS_SCAN_CONCURRENCY)

            async def _attach_metrics(item: dict[str, Any]) -> None:
                try:
                    async with semaphore:
                        metrics = await kamino.fetch_earn_vault_metrics(
                            vault=item["vault"], network=self.network
                        )
                except (ProviderError, WalletBackendError) as exc:
                    metrics_errors.append({"vault": item["vault"], "error": str(exc)})
                    return
                item["metrics"] = self._kamino_vault_metrics_summary(metrics)

            await asyncio.gather(*[_attach_metrics(item) for item in candidates])

            def _apy_key(item: dict[str, Any]) -> float:
                metrics = item.get("metrics")
                try:
                    return float((metrics or {}).get("apy") or 0)
                except (TypeError, ValueError):
                    return 0.0

            candidates.sort(key=_apy_key, reverse=True)
            summaries = candidates

        vaults = summaries[:effective_limit]
        result: dict[str, Any] = {
            "chain": "solana",
            "network": self.network,
            "total_vault_count": total_count,
            "token_mint_filter": mint_filter,
            "include_metrics": bool(include_metrics),
            "vault_count": len(vaults),
            "vaults": vaults,
            "source": "kamino",
        }
        if metrics_errors:
            result["metrics_errors"] = metrics_errors
        return result

    async def get_kamino_earn_positions(self, user: str | None = None) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino Earn")
        wallet_address = user or self.address
        if not wallet_address:
            raise WalletBackendError("A wallet address is required for Kamino Earn position lookup.")
        wallet_address = validate_solana_address(wallet_address)
        data = await kamino.fetch_earn_user_positions(
            user=wallet_address,
            network=self.network,
        )
        positions = data.get("positions")
        if not isinstance(positions, list):
            positions = []
        return {
            "chain": "solana",
            "network": self.network,
            "user": wallet_address,
            "position_count": len(positions),
            "positions": positions,
            "raw": data,
            "source": "kamino",
        }

    async def get_kamino_liquidity_positions(self, user: str | None = None) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino Liquidity")
        portfolio = await self.get_kamino_portfolio(user=user)
        liquidity = portfolio.get("liquidity")
        if not isinstance(liquidity, list):
            liquidity = []
        sections = portfolio.get("sections")
        liquidity_section = sections.get("liquidity") if isinstance(sections, dict) else {}
        return {
            "chain": "solana",
            "network": self.network,
            "user": portfolio["user"],
            "timestamp": portfolio.get("timestamp"),
            "positions_indexed": bool(liquidity_section.get("indexed"))
            if isinstance(liquidity_section, dict)
            else None,
            "positions_refreshed_on": liquidity_section.get("positionsRefreshedOn")
            if isinstance(liquidity_section, dict)
            else None,
            "prices_refreshed_on": liquidity_section.get("pricesRefreshedOn")
            if isinstance(liquidity_section, dict)
            else None,
            "errors": liquidity_section.get("errors")
            if isinstance(liquidity_section, dict) and isinstance(liquidity_section.get("errors"), list)
            else [],
            "position_count": len(liquidity),
            "positions": liquidity,
            "raw": portfolio.get("raw"),
            "source": "kamino+portfolio",
        }

    async def get_kamino_lend_markets(self) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        data = await kamino.fetch_lend_markets()
        markets = data.get("markets")
        if not isinstance(markets, list):
            markets = []
        return {
            "chain": "solana",
            "network": self.network,
            "market_count": len(markets),
            "markets": markets,
            "raw": data,
            "source": "kamino",
        }

    async def get_kamino_lend_market_reserves(self, market: str) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        market = validate_solana_address(market)
        data = await kamino.fetch_lend_market_reserves(
            market=market,
            network=self.network,
        )
        reserves = data.get("reserves")
        if not isinstance(reserves, list):
            reserves = []
        return {
            "chain": "solana",
            "network": self.network,
            "market": market,
            "reserve_count": len(reserves),
            "reserves": reserves,
            "raw": data,
            "source": "kamino",
        }

    async def get_kamino_lend_user_obligations(
        self,
        market: str,
        user: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        wallet_address = user or self.address
        if not wallet_address:
            raise WalletBackendError("A wallet address is required for Kamino obligation lookup.")
        market = validate_solana_address(market)
        wallet_address = validate_solana_address(wallet_address)
        data = await kamino.fetch_lend_user_obligations(
            market=market,
            user=wallet_address,
            network=self.network,
        )
        obligations = data.get("obligations")
        if not isinstance(obligations, list):
            obligations = []
        return {
            "chain": "solana",
            "network": self.network,
            "market": market,
            "user": wallet_address,
            "obligation_count": len(obligations),
            "obligations": obligations,
            "raw": data,
            "source": "kamino",
        }

    async def get_kamino_lend_user_rewards(self, user: str | None = None) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        wallet_address = user or self.address
        if not wallet_address:
            raise WalletBackendError("A wallet address is required for Kamino rewards lookup.")
        wallet_address = validate_solana_address(wallet_address)
        data = await kamino.fetch_lend_user_rewards(user=wallet_address)
        rewards = data.get("rewards")
        if not isinstance(rewards, list):
            rewards = []
        return {
            "chain": "solana",
            "network": self.network,
            "user": wallet_address,
            "reward_count": len(rewards),
            "rewards": rewards,
            "avg_base_apy": data.get("avgBaseApy"),
            "avg_boosted_apy": data.get("avgBoostedApy"),
            "avg_max_apy": data.get("avgMaxApy"),
            "raw": data,
            "source": "kamino",
        }

    async def get_kamino_open_positions(self, user: str | None = None) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        wallet_address = user or self.address
        if not wallet_address:
            raise WalletBackendError("A wallet address is required for Kamino position lookup.")
        wallet_address = validate_solana_address(wallet_address)

        markets_snapshot = await self.get_kamino_lend_markets()
        markets = markets_snapshot.get("markets")
        if not isinstance(markets, list):
            markets = []

        lookup_errors: list[dict[str, Any]] = []
        semaphore = asyncio.Semaphore(KAMINO_OPEN_POSITIONS_SCAN_CONCURRENCY)

        def _market_address(entry: Any) -> str:
            return _kamino_entry_address(entry, "lendingMarket", "market", "address")

        def _market_name(entry: Any) -> str | None:
            if isinstance(entry, dict):
                value = entry.get("name")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return None

        async def _fetch_market_obligations(
            market_entry: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any]] | None:
            market_address = _market_address(market_entry)
            if not market_address:
                return None
            try:
                async with semaphore:
                    obligations_snapshot = await self.get_kamino_lend_user_obligations(
                        market=market_address,
                        user=wallet_address,
                    )
            except (ProviderError, WalletBackendError) as exc:
                lookup_errors.append(
                    {
                        "stage": "market_obligations",
                        "market": market_address,
                        "market_name": _market_name(market_entry),
                        "error": str(exc),
                    }
                )
                return None
            if int(obligations_snapshot.get("obligation_count") or 0) <= 0:
                return None
            return market_entry, obligations_snapshot

        market_results = await asyncio.gather(
            *[
                _fetch_market_obligations(market_entry)
                for market_entry in markets
                if isinstance(market_entry, dict)
            ]
        )
        active_markets = [result for result in market_results if result is not None]
        discovered_obligation_count = sum(
            int(obligations_snapshot.get("obligation_count") or 0)
            for _, obligations_snapshot in active_markets
        )

        try:
            reward_snapshot = await self.get_kamino_lend_user_rewards(user=wallet_address)
        except (ProviderError, WalletBackendError) as exc:
            lookup_errors.append(
                {
                    "stage": "rewards",
                    "user": wallet_address,
                    "error": str(exc),
                }
            )
            reward_snapshot = {
                "chain": "solana",
                "network": self.network,
                "user": wallet_address,
                "reward_count": 0,
                "rewards": [],
                "avg_base_apy": None,
                "avg_boosted_apy": None,
                "avg_max_apy": None,
                "source": "kamino",
            }
        reward_items = reward_snapshot.get("rewards")
        if not isinstance(reward_items, list):
            reward_items = []

        positions: list[dict[str, Any]] = []
        markets_with_positions: list[dict[str, Any]] = []
        total_collateral_value = Decimal("0")
        total_borrow_value = Decimal("0")

        for market_entry, obligations_snapshot in active_markets:
            market_address = _market_address(market_entry)
            market_name = _market_name(market_entry)
            market_description = (
                market_entry.get("description")
                if isinstance(market_entry, dict) and isinstance(market_entry.get("description"), str)
                else None
            )
            markets_with_positions.append(
                {
                    "market": market_address,
                    "market_name": market_name,
                    "obligation_count": int(obligations_snapshot.get("obligation_count") or 0),
                }
            )

            try:
                reserve_snapshot = await self.get_kamino_lend_market_reserves(market=market_address)
            except (ProviderError, WalletBackendError) as exc:
                lookup_errors.append(
                    {
                        "stage": "market_reserves",
                        "market": market_address,
                        "market_name": market_name,
                        "error": str(exc),
                    }
                )
                reserve_snapshot = {
                    "chain": "solana",
                    "network": self.network,
                    "market": market_address,
                    "reserve_count": 0,
                    "reserves": [],
                    "source": "kamino",
                }
            reserves = reserve_snapshot.get("reserves")
            if not isinstance(reserves, list):
                reserves = []
            reserve_by_address = {
                address: reserve
                for reserve in reserves
                if isinstance(reserve, dict)
                and (address := _kamino_entry_address(reserve, "reserve"))
            }
            reserve_by_mint = {
                mint: reserve
                for reserve in reserves
                if isinstance(reserve, dict)
                and isinstance((mint := reserve.get("liquidityTokenMint")), str)
                and mint.strip()
            }
            reserve_by_symbol = {
                symbol.upper(): reserve
                for reserve in reserves
                if isinstance(reserve, dict)
                and isinstance((symbol := reserve.get("liquidityToken")), str)
                and symbol.strip()
            }

            def _reward_metrics_for_reserve(
                *,
                reserve_address: str | None,
                side: str,
            ) -> list[dict[str, Any]]:
                if not reserve_address:
                    return []
                reserve_key = "depositReserve" if side == "deposit" else "borrowReserve"
                metrics: list[dict[str, Any]] = []
                for reward in reward_items:
                    if not isinstance(reward, dict):
                        continue
                    reward_market = _kamino_entry_address(reward, "market")
                    if reward_market and reward_market != market_address:
                        continue
                    reward_reserve = _kamino_entry_address(reward, reserve_key)
                    if reward_reserve != reserve_address:
                        continue
                    metrics.append(
                        {
                            "reward_mint": _kamino_entry_address(reward, "rewardMint", "rewardToken"),
                            "tokens_earned": reward.get("tokensEarned"),
                            "tokens_per_second": reward.get("tokensPerSecond"),
                            "base_apy": reward.get("baseApy"),
                            "boosted_apy": reward.get("boostedApy"),
                            "max_apy": reward.get("maxApy"),
                            "usd_amount": reward.get("usdAmount"),
                            "usd_amount_boosted": reward.get("usdAmountBoosted"),
                            "staking_boost": reward.get("stakingBoost"),
                            "effective_staking_boost": reward.get("effectiveStakingBoost"),
                            "last_calculated": reward.get("lastCalculated"),
                        }
                    )
                return metrics

            obligations = obligations_snapshot.get("obligations")
            if not isinstance(obligations, list):
                obligations = []
            for obligation in obligations:
                if not isinstance(obligation, dict):
                    continue
                obligation_address = _kamino_entry_address(
                    obligation,
                    "obligationAddress",
                    "loanId",
                    "address",
                )
                if not obligation_address:
                    continue
                try:
                    loan_data = await kamino.fetch_lend_loan_info(
                        obligation=obligation_address,
                        network=self.network,
                    )
                except ProviderError as exc:
                    lookup_errors.append(
                        {
                            "stage": "loan_info",
                            "market": market_address,
                            "market_name": market_name,
                            "obligation_address": obligation_address,
                            "error": str(exc),
                        }
                    )
                    continue

                loan_info = loan_data.get("loanInfo")
                if not isinstance(loan_info, dict):
                    loan_info = {}
                collateral = loan_info.get("collateral")
                if not isinstance(collateral, dict):
                    collateral = {}
                debt = loan_info.get("debt")
                if not isinstance(debt, dict):
                    debt = {}
                deposit_entries = collateral.get("deposits")
                if not isinstance(deposit_entries, list):
                    deposit_entries = []
                borrow_entries = debt.get("borrows")
                if not isinstance(borrow_entries, list):
                    borrow_entries = []

                state = obligation.get("state")
                if not isinstance(state, dict):
                    state = {}
                state_deposits = [
                    entry
                    for entry in state.get("deposits", [])
                    if isinstance(entry, dict)
                    and (_coerce_decimal(entry.get("depositedAmount")) or Decimal("0")) > 0
                ]
                state_borrows = [
                    entry
                    for entry in state.get("borrows", [])
                    if isinstance(entry, dict)
                    and (
                        (_coerce_decimal(entry.get("borrowedAmountSf")) or Decimal("0")) > 0
                        or (_coerce_decimal(entry.get("marketValueSf")) or Decimal("0")) > 0
                    )
                ]

                def _match_reserve(
                    *,
                    token_mint: str | None,
                    token_name: str | None,
                    fallback_entry: Any,
                    reserve_key: str,
                ) -> tuple[str | None, dict[str, Any] | None]:
                    fallback_address = _kamino_entry_address(fallback_entry, reserve_key)
                    if fallback_address and fallback_address in reserve_by_address:
                        return fallback_address, reserve_by_address[fallback_address]
                    if token_mint and token_mint in reserve_by_mint:
                        reserve_entry = reserve_by_mint[token_mint]
                        return _kamino_entry_address(reserve_entry, "reserve") or None, reserve_entry
                    symbol = token_name.strip().upper() if isinstance(token_name, str) and token_name.strip() else None
                    if symbol and symbol in reserve_by_symbol:
                        reserve_entry = reserve_by_symbol[symbol]
                        return _kamino_entry_address(reserve_entry, "reserve") or None, reserve_entry
                    return fallback_address or None, None

                def _enrich_position_entries(
                    *,
                    entries: list[dict[str, Any]],
                    state_entries: list[dict[str, Any]],
                    side: str,
                ) -> list[dict[str, Any]]:
                    enriched: list[dict[str, Any]] = []
                    reserve_key = "depositReserve" if side == "deposit" else "borrowReserve"
                    for index, entry in enumerate(entries):
                        if not isinstance(entry, dict):
                            continue
                        token_mint = entry.get("tokenMint")
                        token_name = entry.get("tokenName")
                        fallback_entry = state_entries[index] if index < len(state_entries) else None
                        reserve_address, reserve_metrics = _match_reserve(
                            token_mint=token_mint if isinstance(token_mint, str) else None,
                            token_name=token_name if isinstance(token_name, str) else None,
                            fallback_entry=fallback_entry,
                            reserve_key=reserve_key,
                        )
                        reward_metrics = _reward_metrics_for_reserve(
                            reserve_address=reserve_address,
                            side=side,
                        )
                        enriched.append(
                            {
                                "reserve": reserve_address,
                                "token_mint": token_mint,
                                "token_name": token_name,
                                "token_amount": entry.get("tokenAmount"),
                                "token_value_usd": entry.get("tokenValue"),
                                "token_price_usd": entry.get("tokenPrice"),
                                "max_ltv": entry.get("maxLtv"),
                                "liquidation_ltv": entry.get("liquidationLtv"),
                                "max_withdrawable_amount": entry.get("maxWithdrawableAmount"),
                                "max_withdrawable_value_usd": entry.get("maxWithdrawableValue"),
                                "max_borrowable_amount": entry.get("maxBorrowableAmount"),
                                "max_borrowable_value_usd": entry.get("maxBorrowableValue"),
                                "borrow_factor": entry.get("borrowFactor"),
                                "reserve_supply_apy": (
                                    reserve_metrics.get("supplyApy")
                                    if isinstance(reserve_metrics, dict)
                                    else None
                                ),
                                "reserve_borrow_apy": (
                                    reserve_metrics.get("borrowApy")
                                    if isinstance(reserve_metrics, dict)
                                    else None
                                ),
                                "reserve_max_ltv": (
                                    reserve_metrics.get("maxLtv")
                                    if isinstance(reserve_metrics, dict)
                                    else None
                                ),
                                "reward_metrics": reward_metrics,
                                "reward_count": len(reward_metrics),
                            }
                        )
                    return enriched

                enriched_deposits = _enrich_position_entries(
                    entries=deposit_entries,
                    state_entries=state_deposits,
                    side="deposit",
                )
                enriched_borrows = _enrich_position_entries(
                    entries=borrow_entries,
                    state_entries=state_borrows,
                    side="borrow",
                )

                collateral_value = sum(
                    (
                        _coerce_decimal(entry.get("token_value_usd")) or Decimal("0")
                        for entry in enriched_deposits
                    ),
                    Decimal("0"),
                )
                borrow_value = sum(
                    (
                        _coerce_decimal(entry.get("token_value_usd")) or Decimal("0")
                        for entry in enriched_borrows
                    ),
                    Decimal("0"),
                )
                total_collateral_value += collateral_value
                total_borrow_value += borrow_value
                refreshed_stats = obligation.get("refreshedStats")
                if not isinstance(refreshed_stats, dict):
                    refreshed_stats = {}
                position_type = "borrow-lend"
                if enriched_deposits and not enriched_borrows:
                    position_type = "lend"
                elif enriched_borrows and not enriched_deposits:
                    position_type = "borrow"

                positions.append(
                    {
                        "obligation_address": obligation_address,
                        "market": market_address,
                        "market_name": market_name,
                        "market_description": market_description,
                        "user": wallet_address,
                        "position_type": position_type,
                        "has_debt": bool(enriched_borrows),
                        "timestamp": loan_data.get("timestamp"),
                        "solana_slot": loan_data.get("solanaSlot"),
                        "elevation_group": loan_data.get("elevationGroup"),
                        "leverage": loan_data.get("leverage"),
                        "collateral_value_usd": _format_decimal(collateral_value),
                        "borrow_value_usd": _format_decimal(borrow_value),
                        "net_value_usd": _format_decimal(collateral_value - borrow_value),
                        "loan_info": {
                            "current_ltv": loan_info.get("currentLtv"),
                            "max_ltv": loan_info.get("maxLtv"),
                            "liquidation_ltv": loan_info.get("liquidationLtv"),
                            "close_factor": loan_info.get("closeFactor"),
                            "collateral": {
                                "deposit_count": len(enriched_deposits),
                                "total_value_usd": _format_decimal(collateral_value),
                                "deposits": enriched_deposits,
                            },
                            "debt": {
                                "borrow_count": len(enriched_borrows),
                                "total_value_usd": _format_decimal(borrow_value),
                                "borrows": enriched_borrows,
                            },
                        },
                        "refreshed_stats": {
                            "borrow_limit": refreshed_stats.get("borrowLimit"),
                            "borrow_liquidation_limit": refreshed_stats.get("borrowLiquidationLimit"),
                            "borrow_utilization": refreshed_stats.get("borrowUtilization"),
                            "net_account_value": refreshed_stats.get("netAccountValue"),
                        },
                        "source": "kamino+klend-loans",
                    }
                )

        return {
            "chain": "solana",
            "network": self.network,
            "user": wallet_address,
            "market_count_scanned": len(markets),
            "markets_with_positions_count": len(markets_with_positions),
            "markets_with_positions": markets_with_positions,
            "discovered_obligation_count": discovered_obligation_count,
            "position_count": len(positions),
            "positions": positions,
            "total_collateral_value_usd": _format_decimal(total_collateral_value),
            "total_borrow_value_usd": _format_decimal(total_borrow_value),
            "total_net_value_usd": _format_decimal(total_collateral_value - total_borrow_value),
            "reward_summary": {
                "reward_count": int(reward_snapshot.get("reward_count") or 0),
                "avg_base_apy": reward_snapshot.get("avg_base_apy"),
                "avg_boosted_apy": reward_snapshot.get("avg_boosted_apy"),
                "avg_max_apy": reward_snapshot.get("avg_max_apy"),
            },
            "lookup_errors": lookup_errors,
            "source": "kamino+klend-loans",
        }

    async def get_state(self) -> SolanaWalletState:
        balance_native = None
        if self.address:
            balance = await self._get_native_balance(self.address)
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

    async def _resolve_versioned_message_lookup_addresses(self, message: Any) -> list[str]:
        lookups = list(getattr(message, "address_table_lookups", []) or [])
        if not lookups:
            return []
        try:
            from solders.address_lookup_table_account import AddressLookupTable
        except ImportError as exc:
            raise WalletBackendError(
                "solders package is required for Kamino lookup table verification."
            ) from exc

        loaded_addresses: list[str] = []
        for lookup in lookups:
            table_address = str(lookup.account_key)
            account_info = await solana_rpc.fetch_account_info(
                table_address,
                rpc_url=self.rpc_urls,
                encoding="base64",
            )
            if not account_info:
                raise WalletBackendError(
                    f"Failed to load address lookup table account {table_address}."
                )
            data = account_info.get("data")
            if not isinstance(data, list) or not data or not isinstance(data[0], str):
                raise WalletBackendError(
                    f"Address lookup table {table_address} returned invalid account data."
                )
            try:
                raw = base64.b64decode(data[0])
                table = AddressLookupTable.deserialize(raw)
            except Exception as exc:
                raise WalletBackendError(
                    f"Address lookup table {table_address} could not be decoded."
                ) from exc
            addresses = list(table.addresses)
            loaded_addresses.extend(
                str(addresses[int(index)]) for index in list(lookup.writable_indexes)
            )
            loaded_addresses.extend(
                str(addresses[int(index)]) for index in list(lookup.readonly_indexes)
            )
        return loaded_addresses

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
            self._get_native_balance(owner),
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

    async def _sign_versioned_provider_transaction(
        self,
        *,
        transaction_base64: str,
        wallet_signer_index: int,
    ) -> str:
        try:
            from solders.keypair import Keypair
            from solders.message import to_bytes_versioned
            from solders.transaction import Transaction, VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for provider transaction signing."
            ) from exc

        raw_transaction = self._bags_decode_serialized_transaction_bytes(transaction_base64)
        keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
        try:
            unsigned_transaction = VersionedTransaction.from_bytes(raw_transaction)
        except (TypeError, ValueError):
            unsigned_transaction = Transaction.from_bytes(raw_transaction)
            signatures = list(unsigned_transaction.signatures)
            if wallet_signer_index >= len(signatures):
                raise WalletBackendError(
                    "Provider transaction signer layout is incompatible with local signing."
                )
            unsigned_transaction.partial_sign(
                [keypair],
                unsigned_transaction.message.recent_blockhash,
            )
            return encode_transaction_base64(bytes(unsigned_transaction))
        signature = keypair.sign_message(to_bytes_versioned(unsigned_transaction.message))
        signatures = list(unsigned_transaction.signatures)
        if wallet_signer_index >= len(signatures):
            raise WalletBackendError(
                "Provider transaction signer layout is incompatible with local signing."
            )
        signatures[wallet_signer_index] = signature
        signed_transaction = VersionedTransaction.populate(
            unsigned_transaction.message,
            signatures,
        )
        return encode_transaction_base64(bytes(signed_transaction))

    async def _execute_prepared_provider_transaction(
        self,
        prepared: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )
        kamino_verified = bool((prepared.get("kamino_safety") or {}).get("verified"))
        submitted = await solana_rpc.send_transaction(
            transaction_base64=str(prepared["transaction_base64"]),
            rpc_url=self.rpc_urls,
            skip_preflight=source == "kamino" and kamino_verified,
        )
        signature = submitted.get("signature")
        status = None
        confirmed = False
        if isinstance(signature, str) and signature:
            status = await solana_rpc.wait_for_confirmation(
                signature=signature,
                rpc_url=self.rpc_urls,
                timeout_seconds=60.0 if source == "kamino" else 20.0,
                poll_interval_seconds=2.0 if source == "kamino" else 1.0,
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
            "source": source,
            "simulation": prepared.get("simulation"),
            "kamino_safety": prepared.get("kamino_safety"),
        }

    def _find_kamino_reserve_entry(
        self,
        *,
        reserves: list[Any],
        reserve: str,
    ) -> dict[str, Any] | None:
        for item in reserves:
            if _kamino_entry_address(item, "reserve", "address", "pubkey") == reserve:
                return item
        return None

    def _find_kamino_vault_entry(
        self,
        *,
        vaults: list[Any],
        kvault: str,
    ) -> dict[str, Any] | None:
        for item in vaults:
            if _kamino_entry_address(item, "address", "kvault", "vault", "pubkey") == kvault:
                return item
        return None

    def _find_kamino_earn_position_entry(
        self,
        *,
        positions: list[Any],
        kvault: str,
    ) -> dict[str, Any] | None:
        for item in positions:
            if not isinstance(item, dict):
                continue
            if _kamino_entry_address(item, "vaultAddress", "kvault", "vault", "address", "pubkey") == kvault:
                return item
        return None

    def _find_kamino_obligation_matches(
        self,
        *,
        obligations: list[Any],
        reserve: str,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for item in obligations:
            if not isinstance(item, dict):
                continue
            state = item.get("state")
            if not isinstance(state, dict):
                continue
            deposits = state.get("deposits")
            borrows = state.get("borrows")
            deposit_match = any(
                isinstance(entry, dict)
                and str(entry.get("depositReserve") or "").strip() == reserve
                and str(entry.get("depositedAmount") or "0").strip() not in {"", "0"}
                for entry in (deposits or [])
            )
            borrow_match = any(
                isinstance(entry, dict)
                and str(entry.get("borrowReserve") or "").strip() == reserve
                and str(entry.get("borrowedAmountSf") or "0").strip() not in {"", "0"}
                for entry in (borrows or [])
            )
            if deposit_match or borrow_match:
                matches.append(item)
        return matches

    def _resolve_kamino_obligation_selection(
        self,
        *,
        obligations: list[Any],
        obligation_address: str | None,
        action: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        candidates = [item for item in obligations if isinstance(item, dict)]
        requested = str(obligation_address or "").strip()
        if requested:
            requested = validate_solana_address(requested)
            for item in candidates:
                if (
                    _kamino_entry_address(
                        item,
                        "obligationAddress",
                        "obligation",
                        "address",
                        "pubkey",
                        "loanId",
                    )
                    == requested
                ):
                    return candidates, item
            raise WalletBackendError(
                f"Requested obligation_address is not available for Kamino {action} in the selected market."
            )
        if len(candidates) == 1:
            return candidates, candidates[0]
        return candidates, None

    async def _prepare_kamino_lend_transaction(
        self,
        *,
        transaction_base64: str,
        action: str,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        try:
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Kamino transaction signing."
            ) from exc
        owner = await self.get_address()
        unsigned_transaction = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))
        loaded_addresses = await self._resolve_versioned_message_lookup_addresses(
            unsigned_transaction.message
        )
        verification = verify_provider_kamino_lend_transaction(
            unsigned_transaction.message,
            wallet_address=str(owner),
            market_address=market,
            reserve_address=reserve,
            action=f"Kamino {action}",
            obligation_address=obligation_address,
            loaded_addresses=loaded_addresses,
        )
        signed_transaction_base64 = await self._sign_versioned_provider_transaction(
            transaction_base64=transaction_base64,
            wallet_signer_index=int(verification.get("wallet_signer_index") or 0),
        )
        simulation_value: dict[str, Any] | None = None
        kamino_safety: dict[str, Any]
        try:
            simulation = await solana_rpc.simulate_transaction(
                transaction_base64=signed_transaction_base64,
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            )
            simulation_value = (
                simulation.get("value") if isinstance(simulation.get("value"), dict) else {}
            )
            if isinstance(simulation_value, dict) and simulation_value.get("err") is not None:
                raise WalletBackendError(
                    f"Kamino {action} transaction simulation failed.",
                    code="kamino_simulation_failed",
                    details={
                        "simulation": simulation_value,
                        "action": action,
                        "market": market,
                        "reserve": reserve,
                    },
                )
            kamino_safety = {
                "verified": True,
                "simulation_unavailable": False,
            }
        except ProviderError as exc:
            kamino_safety = {
                "verified": False,
                "simulation_unavailable": True,
                "warning": (
                    "Kamino simulation could not be completed via the configured Solana RPC. "
                    "Proceeding with structural provider verification only."
                ),
                "error": str(exc),
            }
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": f"kamino-lend-{action}",
            "owner": owner,
            "market": market,
            "reserve": reserve,
            "obligation_address": obligation_address,
            "amount_ui": amount_ui,
            "transaction_base64": signed_transaction_base64,
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "verification": verification,
            "simulation": simulation_value,
            "kamino_safety": kamino_safety,
            "sign_only": self.sign_only,
            "source": "kamino",
        }

    async def _prepare_kamino_earn_transaction(
        self,
        *,
        transaction_base64: str,
        action: str,
        kvault: str,
        amount_ui: str,
        vault_token_mint: str | None = None,
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        try:
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Kamino transaction signing."
            ) from exc
        owner = await self.get_address()
        unsigned_transaction = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))
        loaded_addresses = await self._resolve_versioned_message_lookup_addresses(
            unsigned_transaction.message
        )
        verification = verify_provider_kamino_earn_transaction(
            unsigned_transaction.message,
            wallet_address=str(owner),
            vault_address=kvault,
            action=f"Kamino Earn {action}",
            vault_token_mint=vault_token_mint,
            loaded_addresses=loaded_addresses,
        )
        signed_transaction_base64 = await self._sign_versioned_provider_transaction(
            transaction_base64=transaction_base64,
            wallet_signer_index=int(verification.get("wallet_signer_index") or 0),
        )
        simulation_value: dict[str, Any] | None = None
        kamino_safety: dict[str, Any]
        try:
            simulation = await solana_rpc.simulate_transaction(
                transaction_base64=signed_transaction_base64,
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            )
            simulation_value = (
                simulation.get("value") if isinstance(simulation.get("value"), dict) else {}
            )
            if isinstance(simulation_value, dict) and simulation_value.get("err") is not None:
                raise WalletBackendError(
                    f"Kamino Earn {action} transaction simulation failed.",
                    code="kamino_simulation_failed",
                    details={
                        "simulation": simulation_value,
                        "action": action,
                        "kvault": kvault,
                    },
                )
            kamino_safety = {
                "verified": True,
                "simulation_unavailable": False,
            }
        except ProviderError as exc:
            kamino_safety = {
                "verified": False,
                "simulation_unavailable": True,
                "warning": (
                    "Kamino simulation could not be completed via the configured Solana RPC. "
                    "Proceeding with structural provider verification only."
                ),
                "error": str(exc),
            }
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": f"kamino-earn-{action}",
            "owner": owner,
            "kvault": kvault,
            "amount_ui": amount_ui,
            "vault_token_mint": vault_token_mint,
            "transaction_base64": signed_transaction_base64,
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "verification": verification,
            "simulation": simulation_value,
            "kamino_safety": kamino_safety,
            "sign_only": self.sign_only,
            "source": "kamino",
        }

    def _kamino_preview_from_approved(
        self,
        approved_preview: dict[str, Any] | None,
        *,
        asset_type: str,
    ) -> dict[str, Any] | None:
        if not isinstance(approved_preview, dict):
            return None
        if str(approved_preview.get("asset_type") or "").strip() != asset_type:
            return None
        return dict(approved_preview)

    async def preview_kamino_earn_deposit(
        self,
        kvault: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino Earn")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        kvault = validate_solana_address(kvault)
        amount_ui = _require_positive_decimal_string(amount_ui, field_name="amount_ui")
        vault_snapshot = await self.get_kamino_vaults()
        vault_entry = self._find_kamino_vault_entry(
            vaults=list(vault_snapshot["vaults"]),
            kvault=kvault,
        )
        if vault_entry is None:
            raise WalletBackendError("Requested Kamino Earn vault is not available.")
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "kamino-earn-deposit",
            "owner": owner,
            "kvault": kvault,
            "amount_ui": amount_ui,
            "vault_info": vault_entry,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_earn_deposit(
        self,
        kvault: str,
        amount_ui: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = self._kamino_preview_from_approved(
            approved_preview,
            asset_type="kamino-earn-deposit",
        ) or await self.preview_kamino_earn_deposit(
            kvault=kvault,
            amount_ui=amount_ui,
        )
        owner = str(preview["owner"])
        build = await kamino.build_earn_deposit_transaction(
            wallet=owner,
            kvault=str(preview["kvault"]),
            amount_ui=str(preview["amount_ui"]),
        )
        vault_info = preview.get("vault_info") if isinstance(preview.get("vault_info"), dict) else {}
        vault_state = vault_info.get("state") if isinstance(vault_info.get("state"), dict) else {}
        prepared = await self._prepare_kamino_earn_transaction(
            transaction_base64=str(build["transaction"]),
            action="deposit",
            kvault=str(preview["kvault"]),
            amount_ui=str(preview["amount_ui"]),
            vault_token_mint=(
                str(vault_state.get("tokenMint")).strip()
                if str(vault_state.get("tokenMint") or "").strip()
                else None
            ),
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_earn_deposit(
        self,
        kvault: str,
        amount_ui: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_earn_deposit(
            kvault=kvault,
            amount_ui=amount_ui,
            approved_preview=approved_preview,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_earn_withdraw(
        self,
        kvault: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino Earn")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        kvault = validate_solana_address(kvault)
        amount_ui = _require_positive_decimal_string(amount_ui, field_name="amount_ui")
        vault_snapshot = await self.get_kamino_vaults()
        vault_entry = self._find_kamino_vault_entry(
            vaults=list(vault_snapshot["vaults"]),
            kvault=kvault,
        )
        if vault_entry is None:
            raise WalletBackendError("Requested Kamino Earn vault is not available.")
        positions_snapshot = await self.get_kamino_earn_positions(user=owner)
        position_entry = self._find_kamino_earn_position_entry(
            positions=list(positions_snapshot["positions"]),
            kvault=kvault,
        )
        if position_entry is None:
            raise WalletBackendError("No Kamino Earn position found for the requested vault.")
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "kamino-earn-withdraw",
            "owner": owner,
            "kvault": kvault,
            "amount_ui": amount_ui,
            "vault_info": vault_entry,
            "position_info": position_entry,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_earn_withdraw(
        self,
        kvault: str,
        amount_ui: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = self._kamino_preview_from_approved(
            approved_preview,
            asset_type="kamino-earn-withdraw",
        ) or await self.preview_kamino_earn_withdraw(
            kvault=kvault,
            amount_ui=amount_ui,
        )
        owner = str(preview["owner"])
        build = await kamino.build_earn_withdraw_transaction(
            wallet=owner,
            kvault=str(preview["kvault"]),
            amount_ui=str(preview["amount_ui"]),
        )
        vault_info = preview.get("vault_info") if isinstance(preview.get("vault_info"), dict) else {}
        vault_state = vault_info.get("state") if isinstance(vault_info.get("state"), dict) else {}
        prepared = await self._prepare_kamino_earn_transaction(
            transaction_base64=str(build["transaction"]),
            action="withdraw",
            kvault=str(preview["kvault"]),
            amount_ui=str(preview["amount_ui"]),
            vault_token_mint=(
                str(vault_state.get("tokenMint")).strip()
                if str(vault_state.get("tokenMint") or "").strip()
                else None
            ),
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_earn_withdraw(
        self,
        kvault: str,
        amount_ui: str,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_earn_withdraw(
            kvault=kvault,
            amount_ui=amount_ui,
            approved_preview=approved_preview,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        market = validate_solana_address(market)
        reserve = validate_solana_address(reserve)
        amount_ui = _require_positive_decimal_string(amount_ui, field_name="amount_ui")
        reserve_snapshot = await self.get_kamino_lend_market_reserves(market)
        reserve_entry = self._find_kamino_reserve_entry(
            reserves=list(reserve_snapshot["reserves"]),
            reserve=reserve,
        )
        if reserve_entry is None:
            raise WalletBackendError("Requested reserve is not available in the selected Kamino market.")
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "kamino-lend-deposit",
            "owner": owner,
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": reserve_entry,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = self._kamino_preview_from_approved(
            approved_preview,
            asset_type="kamino-lend-deposit",
        ) or await self.preview_kamino_lend_deposit(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
        )
        owner = str(preview["owner"])
        build = await kamino.build_lend_deposit_transaction(
            wallet=owner,
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
        )
        prepared = await self._prepare_kamino_lend_transaction(
            transaction_base64=str(build["transaction"]),
            action="deposit",
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_deposit(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            approved_preview=approved_preview,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        market = validate_solana_address(market)
        reserve = validate_solana_address(reserve)
        amount_ui = _require_positive_decimal_string(amount_ui, field_name="amount_ui")
        reserve_snapshot = await self.get_kamino_lend_market_reserves(market)
        reserve_entry = self._find_kamino_reserve_entry(
            reserves=list(reserve_snapshot["reserves"]),
            reserve=reserve,
        )
        if reserve_entry is None:
            raise WalletBackendError("Requested reserve is not available in the selected Kamino market.")
        obligations = await self.get_kamino_lend_user_obligations(market=market, user=owner)
        obligation_matches = self._find_kamino_obligation_matches(
            obligations=list(obligations["obligations"]),
            reserve=reserve,
        )
        if not obligation_matches:
            raise WalletBackendError("No Kamino obligation found for the requested reserve.")
        obligation_options, selected_obligation = self._resolve_kamino_obligation_selection(
            obligations=obligation_matches,
            obligation_address=obligation_address,
            action="withdraw",
        )
        selected_obligation_address = _kamino_entry_address(
            selected_obligation,
            "obligationAddress",
            "obligation",
            "address",
            "pubkey",
            "loanId",
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "kamino-lend-withdraw",
            "owner": owner,
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": reserve_entry,
            "obligations": obligation_options,
            "obligation_options": [
                _kamino_entry_address(item, "obligationAddress", "obligation", "address", "pubkey", "loanId")
                for item in obligation_options
                if _kamino_entry_address(item, "obligationAddress", "obligation", "address", "pubkey", "loanId")
            ],
            "obligation_address": selected_obligation_address or None,
            "requires_obligation_address": selected_obligation is None and len(obligation_options) > 1,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = self._kamino_preview_from_approved(
            approved_preview,
            asset_type="kamino-lend-withdraw",
        ) or await self.preview_kamino_lend_withdraw(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
        )
        selected_obligation_address = str(preview.get("obligation_address") or "").strip()
        if bool(preview.get("requires_obligation_address")) and not selected_obligation_address:
            raise WalletBackendError(
                "Kamino withdraw requires obligation_address when multiple obligations match the selected market/reserve."
            )
        owner = str(preview["owner"])
        build = await kamino.build_lend_withdraw_transaction(
            wallet=owner,
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
        )
        prepared = await self._prepare_kamino_lend_transaction(
            transaction_base64=str(build["transaction"]),
            action="withdraw",
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
            obligation_address=selected_obligation_address or None,
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_withdraw(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
            approved_preview=approved_preview,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        market = validate_solana_address(market)
        reserve = validate_solana_address(reserve)
        amount_ui = _require_positive_decimal_string(amount_ui, field_name="amount_ui")
        reserve_snapshot = await self.get_kamino_lend_market_reserves(market)
        reserve_entry = self._find_kamino_reserve_entry(
            reserves=list(reserve_snapshot["reserves"]),
            reserve=reserve,
        )
        if reserve_entry is None:
            raise WalletBackendError("Requested reserve is not available in the selected Kamino market.")
        obligations = await self.get_kamino_lend_user_obligations(market=market, user=owner)
        if int(obligations["obligation_count"]) <= 0:
            raise WalletBackendError("Kamino borrow requires an existing obligation in the selected market.")
        obligation_options, selected_obligation = self._resolve_kamino_obligation_selection(
            obligations=list(obligations["obligations"]),
            obligation_address=obligation_address,
            action="borrow",
        )
        selected_obligation_address = _kamino_entry_address(
            selected_obligation,
            "obligationAddress",
            "obligation",
            "address",
            "pubkey",
            "loanId",
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "kamino-lend-borrow",
            "owner": owner,
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": reserve_entry,
            "obligations": obligation_options,
            "obligation_options": [
                _kamino_entry_address(item, "obligationAddress", "obligation", "address", "pubkey", "loanId")
                for item in obligation_options
                if _kamino_entry_address(item, "obligationAddress", "obligation", "address", "pubkey", "loanId")
            ],
            "obligation_address": selected_obligation_address or None,
            "requires_obligation_address": selected_obligation is None and len(obligation_options) > 1,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = self._kamino_preview_from_approved(
            approved_preview,
            asset_type="kamino-lend-borrow",
        ) or await self.preview_kamino_lend_borrow(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
        )
        selected_obligation_address = str(preview.get("obligation_address") or "").strip()
        if bool(preview.get("requires_obligation_address")) and not selected_obligation_address:
            raise WalletBackendError(
                "Kamino borrow requires obligation_address when multiple obligations exist in the selected market."
            )
        owner = str(preview["owner"])
        build = await kamino.build_lend_borrow_transaction(
            wallet=owner,
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
        )
        prepared = await self._prepare_kamino_lend_transaction(
            transaction_base64=str(build["transaction"]),
            action="borrow",
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
            obligation_address=selected_obligation_address or None,
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_borrow(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
            approved_preview=approved_preview,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_kamino("Kamino lending")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        market = validate_solana_address(market)
        reserve = validate_solana_address(reserve)
        amount_ui = _require_positive_decimal_string(amount_ui, field_name="amount_ui")
        reserve_snapshot = await self.get_kamino_lend_market_reserves(market)
        reserve_entry = self._find_kamino_reserve_entry(
            reserves=list(reserve_snapshot["reserves"]),
            reserve=reserve,
        )
        if reserve_entry is None:
            raise WalletBackendError("Requested reserve is not available in the selected Kamino market.")
        obligations = await self.get_kamino_lend_user_obligations(market=market, user=owner)
        obligation_matches = self._find_kamino_obligation_matches(
            obligations=list(obligations["obligations"]),
            reserve=reserve,
        )
        if not obligation_matches:
            raise WalletBackendError("No Kamino debt position found for the requested reserve.")
        obligation_options, selected_obligation = self._resolve_kamino_obligation_selection(
            obligations=obligation_matches,
            obligation_address=obligation_address,
            action="repay",
        )
        selected_obligation_address = _kamino_entry_address(
            selected_obligation,
            "obligationAddress",
            "obligation",
            "address",
            "pubkey",
            "loanId",
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "kamino-lend-repay",
            "owner": owner,
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": reserve_entry,
            "obligations": obligation_options,
            "obligation_options": [
                _kamino_entry_address(item, "obligationAddress", "obligation", "address", "pubkey", "loanId")
                for item in obligation_options
                if _kamino_entry_address(item, "obligationAddress", "obligation", "address", "pubkey", "loanId")
            ],
            "obligation_address": selected_obligation_address or None,
            "requires_obligation_address": selected_obligation is None and len(obligation_options) > 1,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = self._kamino_preview_from_approved(
            approved_preview,
            asset_type="kamino-lend-repay",
        ) or await self.preview_kamino_lend_repay(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
        )
        selected_obligation_address = str(preview.get("obligation_address") or "").strip()
        if bool(preview.get("requires_obligation_address")) and not selected_obligation_address:
            raise WalletBackendError(
                "Kamino repay requires obligation_address when multiple debt obligations match the selected market/reserve."
            )
        owner = str(preview["owner"])
        build = await kamino.build_lend_repay_transaction(
            wallet=owner,
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
        )
        prepared = await self._prepare_kamino_lend_transaction(
            transaction_base64=str(build["transaction"]),
            action="repay",
            market=str(preview["market"]),
            reserve=str(preview["reserve"]),
            amount_ui=str(preview["amount_ui"]),
            obligation_address=selected_obligation_address or None,
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
        obligation_address: str | None = None,
        approved_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_repay(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
            obligation_address=obligation_address,
            approved_preview=approved_preview,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
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
        balance = await self._get_native_balance(sender)
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

    async def preview_bags_token_launch(
        self,
        *,
        name: str,
        symbol: str,
        description: str,
        base_mint: str,
        claimers: list[str],
        basis_points: list[int],
        initial_buy_sol: float,
        image_url: str | None = None,
        website: str | None = None,
        twitter: str | None = None,
        telegram: str | None = None,
        discord: str | None = None,
        bags_config_type: int | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_bags("Bags token launch")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        normalized_name = str(name).strip()
        normalized_symbol = str(symbol).strip()
        normalized_description = str(description).strip()
        if not normalized_name:
            raise WalletBackendError("name is required.")
        if not normalized_symbol:
            raise WalletBackendError("symbol is required.")
        if not normalized_description:
            raise WalletBackendError("description is required.")
        normalized_base_mint = validate_solana_mint(base_mint)
        normalized_claimers = self._normalize_bags_claimers(claimers)
        normalized_basis_points = self._normalize_bags_basis_points(basis_points)
        if len(normalized_claimers) != len(normalized_basis_points):
            raise WalletBackendError("claimers and basis_points must have the same length.")
        if owner not in normalized_claimers:
            raise WalletBackendError(
                "claimers must explicitly include the connected wallet address as the creator fee recipient."
            )
        if isinstance(initial_buy_sol, bool) or float(initial_buy_sol) < 0:
            raise WalletBackendError("initial_buy_sol must be a non-negative number.")
        initial_buy_lamports = int(round(float(initial_buy_sol) * solana_rpc.LAMPORTS_PER_SOL))
        if initial_buy_lamports < 0:
            raise WalletBackendError("initial_buy_sol must be a non-negative number.")
        normalized_bags_config_type = (
            _coerce_non_negative_integer(bags_config_type, field_name="bags_config_type")
            if bags_config_type is not None
            else None
        )
        preview = {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "bags-token-launch",
            "owner": owner,
            "wallet": owner,
            "token_name": normalized_name,
            "token_symbol": normalized_symbol,
            "description": normalized_description,
            "image_url": str(image_url or "").strip() or None,
            "website": str(website or "").strip() or None,
            "twitter": str(twitter or "").strip() or None,
            "telegram": str(telegram or "").strip() or None,
            "discord": str(discord or "").strip() or None,
            "base_mint": normalized_base_mint,
            "claimers": normalized_claimers,
            "basis_points": normalized_basis_points,
            "claimers_count": len(normalized_claimers),
            "total_basis_points": sum(normalized_basis_points),
            "initial_buy_sol": float(initial_buy_sol),
            "initial_buy_lamports": initial_buy_lamports,
            "bags_config_type": normalized_bags_config_type,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "bags",
        }
        return preview

    async def execute_bags_token_launch(
        self,
        *,
        name: str,
        symbol: str,
        description: str,
        base_mint: str,
        claimers: list[str],
        basis_points: list[int],
        initial_buy_sol: float,
        image_url: str | None = None,
        website: str | None = None,
        twitter: str | None = None,
        telegram: str | None = None,
        discord: str | None = None,
        bags_config_type: int | None = None,
    ) -> dict[str, Any]:
        preview = await self.preview_bags_token_launch(
            name=name,
            symbol=symbol,
            description=description,
            base_mint=base_mint,
            claimers=claimers,
            basis_points=basis_points,
            initial_buy_sol=initial_buy_sol,
            image_url=image_url,
            website=website,
            twitter=twitter,
            telegram=telegram,
            discord=discord,
            bags_config_type=bags_config_type,
        )
        return await self.execute_bags_token_launch_from_preview(preview)

    async def execute_bags_token_launch_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        if str(preview.get("asset_type") or "").strip().lower() != "bags-token-launch":
            raise WalletBackendError("preview payload is not a Bags token launch preview.")
        if str(preview.get("network") or self.network).strip().lower() != self.network:
            raise WalletBackendError("preview payload network does not match the wallet backend.")
        if str(preview.get("owner") or owner) != owner:
            raise WalletBackendError("preview payload owner does not match the connected wallet.")
        if int(preview.get("claimers_count") or 0) > 7:
            raise WalletBackendError(
                "Bags fee-share launches with more than 7 fee claimers require lookup table "
                "creation, which this backend does not generate yet."
            )

        token_info_payload = {
            "name": str(preview["token_name"]),
            "symbol": str(preview["token_symbol"]),
            "description": str(preview["description"]),
        }
        optional_metadata = {
            "imageUrl": preview.get("image_url"),
            "website": preview.get("website"),
            "twitter": preview.get("twitter"),
            "telegram": preview.get("telegram"),
            "discord": preview.get("discord"),
        }
        for key, value in optional_metadata.items():
            if isinstance(value, str) and value.strip():
                token_info_payload[key] = value.strip()

        token_info_response = await bags.create_token_info(token_info_payload)
        token_mint, ipfs = self._bags_extract_token_info_fields(token_info_response)
        fee_share_payload: dict[str, Any] = {
            "payer": owner,
            "baseMint": token_mint,
            "claimersArray": list(preview["claimers"]),
            "basisPointsArray": [int(value) for value in preview["basis_points"]],
        }
        if preview.get("bags_config_type") is not None:
            fee_share_payload["bagsConfigType"] = int(preview["bags_config_type"])
        fee_share_response = await bags.create_fee_share_config(fee_share_payload)
        config_key = self._bags_extract_config_key(fee_share_response)
        fee_share_execution: dict[str, Any] | None = None
        if bool(fee_share_response.get("needsCreation")):
            fee_share_transactions = self._bags_extract_fee_share_config_transaction_strings(
                fee_share_response
            )
            if not fee_share_transactions:
                raise WalletBackendError(
                    "Bags fee share config requested creation but returned no transactions."
                )
            fee_share_prepared = await self._prepare_bags_transactions(
                transaction_base64s=fee_share_transactions,
                token_mint=token_mint,
                action="Bags fee share config",
                owner=owner,
                asset_type="bags-fee-share-config",
                extra={
                    "wallet": owner,
                    "base_mint": preview["base_mint"],
                    "claimers": preview["claimers"],
                    "basis_points": preview["basis_points"],
                    "claimers_count": preview["claimers_count"],
                    "total_basis_points": preview["total_basis_points"],
                    "config_key": config_key,
                    "fee_share_response": fee_share_response,
                },
            )
            fee_share_execution = await self._execute_prepared_bags_transactions(fee_share_prepared)
        launch_transaction_response = await bags.create_launch_transaction(
            {
                "ipfs": ipfs,
                "tokenMint": token_mint,
                "wallet": owner,
                "configKey": config_key,
                "initialBuyLamports": str(int(preview["initial_buy_lamports"])),
            }
        )
        transactions = self._bags_extract_serialized_transaction_strings(launch_transaction_response)
        prepared = await self._prepare_bags_transactions(
            transaction_base64s=transactions,
            token_mint=token_mint,
            action="Bags token launch",
            owner=owner,
            asset_type="bags-token-launch",
            extra={
                "wallet": owner,
                "token_name": preview["token_name"],
                "token_symbol": preview["token_symbol"],
                "base_mint": preview["base_mint"],
                "claimers": preview["claimers"],
                "basis_points": preview["basis_points"],
                "claimers_count": preview["claimers_count"],
                "total_basis_points": preview["total_basis_points"],
                "initial_buy_sol": preview["initial_buy_sol"],
                "initial_buy_lamports": preview["initial_buy_lamports"],
                "config_key": config_key,
                "ipfs": ipfs,
                "token_info_response": token_info_response,
                "fee_share_response": fee_share_response,
                "fee_share_execution": fee_share_execution,
                "launch_transaction_response": launch_transaction_response,
            },
        )
        result = await self._execute_prepared_bags_transactions(prepared)
        result.update(
            {
                "wallet": owner,
                "token_name": preview["token_name"],
                "token_symbol": preview["token_symbol"],
                "base_mint": preview["base_mint"],
                "claimers": preview["claimers"],
                "basis_points": preview["basis_points"],
                "claimers_count": preview["claimers_count"],
                "total_basis_points": preview["total_basis_points"],
                "initial_buy_sol": preview["initial_buy_sol"],
                "initial_buy_lamports": preview["initial_buy_lamports"],
                "config_key": config_key,
                "ipfs": ipfs,
                "token_info_response": token_info_response,
                "fee_share_response": fee_share_response,
                "fee_share_execution": fee_share_execution,
                "launch_transaction_response": launch_transaction_response,
            }
        )
        return result

    async def preview_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS,
        exclude_routers: list[str] | None = None,
        exclude_dexes: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.network != "mainnet":
            raise WalletBackendError("Provider-routed swaps are only enabled for Solana mainnet.")
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
        quote_source = "jupiter-v2-order"
        try:
            quote = await jupiter.fetch_swap_v2_order(
                input_mint=input_mint,
                output_mint=output_mint,
                amount_raw=raw_amount,
                taker=sender,
                exclude_routers=exclude_routers,
            )
        except ProviderError:
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
                    exclude_dexes=exclude_dexes,
                )
                quote_source = "jupiter-metis"

        out_amount_raw = int(quote.get("outAmount") or 0)
        other_threshold_raw = self._swap_minimum_output_floor(
            out_amount_raw=out_amount_raw,
            slippage_bps=slippage_bps,
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
            "owner": sender,
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

    async def preview_swap_intent(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS,
        minimum_output_amount_raw: int | None = None,
        max_fee_lamports: int | None = None,
        valid_for_seconds: int = 120,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if valid_for_seconds <= 0 or valid_for_seconds > 120:
            raise WalletBackendError("valid_for_seconds must be between 1 and 120.")
        if max_attempts <= 0 or max_attempts > 5:
            raise WalletBackendError("max_attempts must be between 1 and 5.")
        slippage_bps = max(int(slippage_bps), SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS)
        max_attempts = max(int(max_attempts), 3)

        indicative = await self.preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        indicative_output_raw = int(indicative.get("estimated_output_amount_raw") or 0)
        slippage_floor_raw = self._swap_minimum_output_floor(
            out_amount_raw=indicative_output_raw,
            slippage_bps=slippage_bps,
        )
        requested_min_output_raw = (
            int(minimum_output_amount_raw)
            if minimum_output_amount_raw is not None
            else None
        )
        if requested_min_output_raw is not None:
            min_output_raw = min(requested_min_output_raw, slippage_floor_raw)
            minimum_output_policy = (
                "explicit_clamped_to_slippage_floor"
                if requested_min_output_raw > slippage_floor_raw
                else "explicit"
            )
        else:
            min_output_raw = slippage_floor_raw
            minimum_output_policy = "slippage_floor"
        if min_output_raw <= 0:
            raise WalletBackendError("minimum_output_amount_raw could not be derived from the indicative quote.")
        output_decimals = int(indicative.get("output_decimals") or 0)
        min_output_ui = min_output_raw / (10**output_decimals)

        fee_summary = (
            indicative.get("fee_summary")
            if isinstance(indicative.get("fee_summary"), dict)
            else {}
        )
        fee_limit = (
            int(max_fee_lamports)
            if max_fee_lamports is not None
            else self._default_swap_intent_max_fee_lamports(fee_summary)
        )
        if fee_limit < 0:
            raise WalletBackendError("max_fee_lamports must be non-negative.")

        return {
            "chain": "solana",
            "network": self.network,
            "mode": "intent_preview",
            "asset_type": "solana-swap-intent",
            "owner": indicative.get("owner"),
            "input_mint": indicative["input_mint"],
            "output_mint": indicative["output_mint"],
            "input_amount_ui": indicative["input_amount_ui"],
            "input_amount_raw": indicative["input_amount_raw"],
            "input_decimals": indicative.get("input_decimals"),
            "output_decimals": indicative.get("output_decimals"),
            "indicative_output_amount_ui": indicative.get("estimated_output_amount_ui"),
            "indicative_output_amount_raw": indicative.get("estimated_output_amount_raw"),
            "minimum_output_amount_ui": min_output_ui,
            "minimum_output_amount_raw": min_output_raw,
            "requested_minimum_output_amount_raw": requested_min_output_raw,
            "minimum_output_policy": minimum_output_policy,
            "max_slippage_bps": slippage_bps,
            "slippage_bps": slippage_bps,
            "max_fee_lamports": fee_limit,
            "max_fee_sol": fee_limit / solana_rpc.LAMPORTS_PER_SOL,
            "valid_for_seconds": valid_for_seconds,
            "valid_until_epoch_seconds": int(time.time()) + valid_for_seconds,
            "max_attempts": max_attempts,
            "allowed_providers": ["jupiter-v2-order", "jupiter-ultra", "jupiter-metis"],
            "recipient_policy": "owner-only",
            "spend_policy": "exact-input",
            "indicative_swap_provider": indicative.get("swap_provider"),
            "indicative_price_impact_pct": indicative.get("price_impact_pct"),
            "indicative_route_plan": indicative.get("route_plan", []),
            "indicative_fee_summary": fee_summary,
            "intent_note": (
                "This is an intent approval preview. Execute will fetch a fresh quote and "
                "only sign/send if it remains inside these approved limits."
            ),
            "can_send": self.get_capabilities().can_send_transaction,
            "sign_only": self.sign_only,
            "source": "swap-intent",
        }

    async def execute_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS,
    ) -> dict[str, Any]:
        preview = await self.preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        return await self.execute_swap_from_preview(preview)

    async def _submit_prepared_swap(
        self,
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        if self.sign_only:
            raise WalletBackendError(
                "This wallet backend is in sign-only mode. Disable sign_only to broadcast transactions."
            )

        if prepared.get("swap_provider") == "jupiter-v2-order":
            submitted = await jupiter.execute_swap_v2_order(
                signed_transaction_base64=str(prepared["transaction_base64"]),
                request_id=str(prepared["request_id"]),
                last_valid_block_height=_coerce_int(prepared.get("last_valid_block_height")),
            )
            onchain_signature = submitted.get("signature") or submitted.get("txid")
        elif prepared.get("swap_provider") == "jupiter-ultra":
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
            "owner": prepared.get("owner"),
            "input_mint": prepared["input_mint"],
            "output_mint": prepared["output_mint"],
            "input_amount_ui": prepared["input_amount_ui"],
            "estimated_output_amount_ui": prepared["estimated_output_amount_ui"],
            "minimum_output_amount_ui": prepared["minimum_output_amount_ui"],
            "minimum_output_amount_raw": prepared.get("minimum_output_amount_raw"),
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
            "swap_safety": prepared.get("swap_safety"),
            "simulation": prepared.get("simulation"),
            "execute_response": submitted,
            "source": prepared.get("swap_provider") or "jupiter-metis",
        }

    async def execute_swap_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = await self.prepare_swap_from_preview(preview)
        return await self._submit_prepared_swap(prepared)

    async def execute_swap_intent(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS,
        minimum_output_amount_raw: int | None = None,
        max_fee_lamports: int | None = None,
        valid_until_epoch_seconds: int | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if valid_until_epoch_seconds is not None and int(time.time()) > int(valid_until_epoch_seconds):
            raise WalletBackendError("Approved swap intent has expired. Create a fresh intent preview.")
        if max_attempts <= 0 or max_attempts > 5:
            raise WalletBackendError("max_attempts must be between 1 and 5.")
        slippage_bps = max(int(slippage_bps), SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS)
        max_attempts = max(int(max_attempts), 3)

        attempts: list[dict[str, Any]] = []
        last_error: str | None = None
        _simulation_failed = False
        for attempt_index in range(max_attempts):
            if valid_until_epoch_seconds is not None and int(time.time()) > int(valid_until_epoch_seconds):
                break
            try:
                exclude_routers = ["jupiterz"] if attempt_index > 0 else None
                # On retries after a simulation failure, exclude DEXes known to fail
                # simulation for Token-2022 tokens with extensions such as
                # scaledUiAmountConfig, pausableConfig, or permanentDelegate
                # (e.g. Backpack xStock tokens). GoonFi V2 is the primary offender;
                # ZeroFi handles these tokens correctly.
                exclude_dexes: list[str] | None = None
                if _simulation_failed and attempt_index > 0:
                    exclude_dexes = ["GoonFi V2"]
                preview = await self.preview_swap(
                    input_mint=input_mint,
                    output_mint=output_mint,
                    amount_ui=amount_ui,
                    slippage_bps=slippage_bps,
                    exclude_routers=exclude_routers,
                    exclude_dexes=exclude_dexes,
                )
                estimated_output_raw = int(preview.get("estimated_output_amount_raw") or 0)
                if (
                    minimum_output_amount_raw is not None
                    and estimated_output_raw < int(minimum_output_amount_raw)
                ):
                    attempts.append(
                        {
                            "attempt": attempt_index + 1,
                            "swap_provider": preview.get("swap_provider"),
                            "rejected": "quote_below_minimum_output",
                            "estimated_output_amount_raw": estimated_output_raw,
                            "minimum_output_amount_raw": int(minimum_output_amount_raw),
                        }
                    )
                    last_error = "Fresh swap quote is below the approved minimum output."
                    continue

                prepared = await self.prepare_swap_from_preview(preview)
                prepared_fee = self._swap_fee_lamports(prepared)
                if (
                    max_fee_lamports is not None
                    and prepared_fee is not None
                    and prepared_fee > int(max_fee_lamports)
                ):
                    attempts.append(
                        {
                            "attempt": attempt_index + 1,
                            "swap_provider": prepared.get("swap_provider"),
                            "rejected": "fee_above_limit",
                            "fee_lamports": prepared_fee,
                            "max_fee_lamports": int(max_fee_lamports),
                        }
                    )
                    last_error = "Fresh swap fee exceeds the approved fee limit."
                    continue

                result = await self._submit_prepared_swap(prepared)
                result["intent_execution"] = {
                    "approved_minimum_output_amount_raw": minimum_output_amount_raw,
                    "approved_max_fee_lamports": max_fee_lamports,
                    "fresh_quote_used": True,
                    "attempt_count": attempt_index + 1,
                    "max_attempts": max_attempts,
                    "attempts": attempts
                    + [
                        {
                            "attempt": attempt_index + 1,
                            "swap_provider": prepared.get("swap_provider"),
                            "status": "submitted",
                        }
                    ],
                }
                return result
            except (WalletBackendError, ProviderError) as exc:
                last_error = str(exc)
                if "simulation failed" in str(exc).lower():
                    _simulation_failed = True
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "rejected": "execution_error",
                        "error": str(exc),
                    }
                )
                if "sign-only mode" in str(exc).lower():
                    break
            if attempt_index + 1 < max_attempts:
                await asyncio.sleep(min(0.5 * (attempt_index + 1), 1.5))

        reason_suffix = f" Last reason: {last_error}" if last_error else ""
        raise WalletBackendError(
            "Solana swap intent execution failed within the approved limits. Funds were not moved."
            + reason_suffix,
            details={
                "reason": last_error,
                "attempts": attempts,
                "minimum_output_amount_raw": minimum_output_amount_raw,
                "max_fee_lamports": max_fee_lamports,
                "max_attempts": max_attempts,
            },
        )

    async def prepare_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = SOLANA_SWAP_DEFAULT_SLIPPAGE_BPS,
    ) -> dict[str, Any]:
        preview = await self.preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        return await self.prepare_swap_from_preview(preview)

    async def prepare_swap_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.signer:
            raise WalletBackendError("Solana signer is not configured.")

        sender = await self.get_address()
        if not sender:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )

        if str(preview.get("asset_type") or "").strip().lower() != "swap":
            raise WalletBackendError("preview payload is not a swap preview.")
        if str(preview.get("network") or self.network).strip().lower() != self.network:
            raise WalletBackendError("preview payload network does not match the wallet backend.")
        if str(preview.get("owner") or sender) != sender:
            raise WalletBackendError("preview payload owner does not match the connected wallet.")

        try:
            from solders.keypair import Keypair
            from solders.message import to_bytes_versioned
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for provider-routed swap execution."
            ) from exc

        swap_provider = str(preview.get("swap_provider") or "jupiter-metis")
        request_id = None
        if swap_provider in {"jupiter-v2-order", "jupiter-ultra"}:
            swap_build = preview["quote_response"]
            unsigned_transaction = VersionedTransaction.from_bytes(
                base64.b64decode(str(swap_build["transaction"]))
            )
            request_id = swap_build.get("requestId")
            blockhash_metadata = swap_build.get("blockhashWithMetadata")
            last_valid_block_height = (
                blockhash_metadata.get("lastValidBlockHeight")
                if isinstance(blockhash_metadata, dict)
                else None
            )
            if last_valid_block_height is None:
                last_valid_block_height = (
                    swap_build.get("lastValidBlockHeight")
                    or swap_build.get("expireAt")
                )
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
        signatures = list(unsigned_transaction.signatures)
        wallet_signer_index = int(verification.get("wallet_signer_index") or 0)
        if wallet_signer_index >= len(signatures):
            raise WalletBackendError(
                "Provider swap transaction signer layout is incompatible with local signing."
            )
        signatures[wallet_signer_index] = signature
        signed_transaction = VersionedTransaction.populate(
            unsigned_transaction.message,
            signatures,
        )
        signed_transaction_base64 = encode_transaction_base64(bytes(signed_transaction))
        simulation_value: dict[str, Any] | None = None
        swap_safety: dict[str, Any]
        try:
            simulation = await solana_rpc.simulate_transaction(
                transaction_base64=signed_transaction_base64,
                rpc_url=self.rpc_urls,
                commitment=self.commitment,
            )
            simulation_value = (
                simulation.get("value") if isinstance(simulation.get("value"), dict) else {}
            )
            swap_safety = verify_provider_swap_simulation_result(
                simulation_value,
                wallet_address=sender,
                wallet_account_index=wallet_signer_index,
                input_mint=str(preview["input_mint"]),
                output_mint=str(preview["output_mint"]),
                input_amount_raw=int(preview["input_amount_raw"]),
                minimum_output_amount_raw=int(preview["minimum_output_amount_raw"]),
            )
        except ProviderError as exc:
            swap_safety = {
                "verified": False,
                "simulation_unavailable": True,
                "warning": (
                    "Swap simulation could not be completed via the configured Solana RPC. "
                    "Proceeding with structural provider verification to preserve swap "
                    "availability."
                ),
                "error": str(exc),
            }
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
            "owner": sender,
            "input_mint": preview["input_mint"],
            "output_mint": preview["output_mint"],
            "input_amount_ui": preview["input_amount_ui"],
            "input_amount_raw": preview["input_amount_raw"],
            "estimated_output_amount_ui": preview["estimated_output_amount_ui"],
            "minimum_output_amount_ui": preview["minimum_output_amount_ui"],
            "minimum_output_amount_raw": preview["minimum_output_amount_raw"],
            "slippage_bps": preview["slippage_bps"],
            "price_impact_pct": preview["price_impact_pct"],
            "transaction_base64": signed_transaction_base64,
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
            "swap_safety": swap_safety,
            "simulation": simulation_value,
            "request_id": request_id,
            "swap_provider": swap_provider,
            "source": swap_provider,
        }
