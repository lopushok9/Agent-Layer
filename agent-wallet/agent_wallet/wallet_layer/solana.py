"""Solana wallet backend focused on simple local or read-only operation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from agent_wallet.models import AgentWalletCapabilities, SolanaWalletState
from agent_wallet.providers import bags, jupiter, kamino, lifi, solana_rpc
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
    verify_provider_kamino_lend_transaction,
    verify_provider_lend_transaction,
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
BAGS_MINT_SUFFIX = "BAGS"


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
        self.network = network
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
        for index in range(0, len(mints), 20):
            batch = mints[index : index + 20]
            try:
                price_data = await jupiter.fetch_prices(mints=batch)
            except ProviderError as exc:
                price_errors.append(str(exc))
                continue
            for mint in batch:
                entry = _jupiter_price_entry(price_data, mint)
                if entry is not None:
                    price_data_by_mint[mint] = entry

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
            enriched_tokens.append(
                {
                    **token,
                    "price_usd": str(price) if price is not None else None,
                    "value_usd": _format_decimal(value),
                    "pricing_source": "jupiter-price" if price is not None else None,
                    "price_raw": price_data_by_mint.get(mint),
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

    async def get_bags_claimable_positions(
        self,
        wallet: str | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_bags("Bags fee claims")
        wallet_address = wallet or self.address
        if not wallet_address:
            raise WalletBackendError("A wallet address is required for Bags claimable positions.")
        wallet_address = validate_solana_address(wallet_address)
        raw = await bags.fetch_claimable_positions(wallet_address)
        positions = self._bags_claim_positions_list(raw)
        return {
            "chain": "solana",
            "network": self.network,
            "wallet": wallet_address,
            "position_count": len(positions),
            "positions": positions,
            "raw": raw,
            "source": "bags",
        }

    async def get_bags_fee_analytics(
        self,
        token_mint: str,
        *,
        include_claim_events: bool = False,
        mode: str = "offset",
        limit: int | None = None,
        offset: int | None = None,
        from_ts: int | None = None,
        to_ts: int | None = None,
    ) -> dict[str, Any]:
        self._require_mainnet_bags("Bags fee analytics")
        normalized_mint = validate_solana_mint(token_mint)
        if mode not in {"offset", "time"}:
            raise WalletBackendError("mode must be 'offset' or 'time'.")
        if limit is not None and limit <= 0:
            raise WalletBackendError("limit must be greater than zero when provided.")
        if offset is not None and offset < 0:
            raise WalletBackendError("offset must be greater than or equal to zero when provided.")
        if from_ts is not None and from_ts < 0:
            raise WalletBackendError("from_ts must be greater than or equal to zero.")
        if to_ts is not None and to_ts < 0:
            raise WalletBackendError("to_ts must be greater than or equal to zero.")

        tasks = [
            bags.fetch_lifetime_fees(normalized_mint),
            bags.fetch_claim_stats(normalized_mint),
        ]
        if include_claim_events:
            tasks.append(
                bags.fetch_claim_events(
                    token_mint=normalized_mint,
                    mode=mode,
                    limit=limit,
                    offset=offset,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )
            )
        results = await asyncio.gather(*tasks)
        claim_events = results[2] if include_claim_events else None
        return {
            "chain": "solana",
            "network": self.network,
            "token_mint": normalized_mint,
            "lifetime_fees": results[0],
            "claim_stats": results[1],
            "claim_events": claim_events,
            "include_claim_events": include_claim_events,
            "source": "bags",
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

    def _prefer_bags_swap_route(self, input_mint: str, output_mint: str) -> bool:
        if str(self.swap_provider or "").strip().lower() == "bags":
            return True
        return input_mint.endswith(BAGS_MINT_SUFFIX) or output_mint.endswith(BAGS_MINT_SUFFIX)

    async def _fetch_bags_swap_quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_raw: int,
        slippage_bps: int,
    ) -> dict[str, Any]:
        return await bags.fetch_trade_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=amount_raw,
            slippage_bps=slippage_bps,
        )

    async def _fetch_jupiter_swap_quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        amount_raw: int,
        taker: str | None,
        slippage_bps: int,
    ) -> tuple[dict[str, Any], str]:
        try:
            quote = await jupiter.fetch_ultra_order(
                input_mint=input_mint,
                output_mint=output_mint,
                amount_raw=amount_raw,
                taker=taker,
                slippage_bps=slippage_bps,
            )
            return quote, "jupiter-ultra"
        except ProviderError as ultra_error:
            try:
                quote = await jupiter.fetch_quote(
                    input_mint=input_mint,
                    output_mint=output_mint,
                    amount_raw=amount_raw,
                    slippage_bps=slippage_bps,
                )
                return quote, "jupiter-metis"
            except ProviderError as metis_error:
                raise ProviderError(
                    "jupiter",
                    f"Jupiter Ultra and Metis quote failed: {ultra_error}; {metis_error}",
                ) from metis_error

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

    def _bags_claim_positions_list(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("positions", "claimablePositions", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

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

    def _require_mainnet_kamino(self, feature: str) -> None:
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
            tokens = []
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
            positions = []
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
        earnings = data.get("earnings")
        if not isinstance(earnings, list):
            earnings = []
        return {
            "chain": "solana",
            "network": self.network,
            "user": wallet_address,
            "positions": normalized_positions,
            "earnings": earnings,
            "raw": data,
            "source": "jupiter-lend",
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
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for provider transaction signing."
            ) from exc

        unsigned_transaction = VersionedTransaction.from_bytes(
            self._bags_decode_serialized_transaction_bytes(transaction_base64)
        )
        keypair = Keypair.from_bytes(self.signer.export_keypair_bytes())
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
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise WalletBackendError(
                "solana and solders packages are required for Jupiter Earn transaction signing."
            ) from exc
        unsigned_transaction = VersionedTransaction.from_bytes(base64.b64decode(transaction_base64))
        owner = await self.get_address()
        verification = verify_provider_lend_transaction(
            unsigned_transaction.message,
            wallet_address=str(owner),
            asset_mint=asset,
            action=f"Jupiter Earn {action}",
        )
        signed_transaction_base64 = await self._sign_versioned_provider_transaction(
            transaction_base64=transaction_base64,
            wallet_signer_index=int(verification.get("wallet_signer_index") or 0),
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": f"jupiter-earn-{action}",
            "owner": owner,
            "asset": asset,
            "amount_raw": amount_raw,
            "transaction_base64": signed_transaction_base64,
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "verification": verification,
            "sign_only": self.sign_only,
            "source": "jupiter-lend",
        }

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
            "source": source,
        }

    async def _execute_prepared_jupiter_lend_transaction(self, prepared: dict[str, Any]) -> dict[str, Any]:
        return await self._execute_prepared_provider_transaction(
            prepared,
            source="jupiter-lend",
        )

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

    async def _prepare_kamino_lend_transaction(
        self,
        *,
        transaction_base64: str,
        action: str,
        market: str,
        reserve: str,
        amount_ui: str,
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
            loaded_addresses=loaded_addresses,
        )
        signed_transaction_base64 = await self._sign_versioned_provider_transaction(
            transaction_base64=transaction_base64,
            wallet_signer_index=int(verification.get("wallet_signer_index") or 0),
        )
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": f"kamino-lend-{action}",
            "owner": owner,
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "transaction_base64": signed_transaction_base64,
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "verification": verification,
            "sign_only": self.sign_only,
            "source": "kamino",
        }

    async def preview_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
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
    ) -> dict[str, Any]:
        preview = await self.preview_kamino_lend_deposit(
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
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_deposit(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
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
            "obligations": obligation_matches,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        preview = await self.preview_kamino_lend_withdraw(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
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
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_withdraw(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
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
            "obligations": obligations["obligations"],
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        preview = await self.preview_kamino_lend_borrow(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
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
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_borrow(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

    async def preview_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
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
            "obligations": obligation_matches,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "kamino",
        }

    async def prepare_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        preview = await self.preview_kamino_lend_repay(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
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
        )
        prepared["build_response"] = build
        return prepared

    async def execute_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict[str, Any]:
        prepared = await self.prepare_kamino_lend_repay(
            market=market,
            reserve=reserve,
            amount_ui=amount_ui,
        )
        result = await self._execute_prepared_provider_transaction(prepared, source="kamino")
        result["build_response"] = prepared.get("build_response")
        return result

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
        amount_raw = _require_positive_integer_string(amount_raw, field_name="amount_raw")
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
        if token_entry is None:
            raise WalletBackendError("Requested asset is not currently available in Jupiter Earn.")
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "jupiter-earn-deposit",
            "owner": owner,
            "asset": asset,
            "amount_raw": amount_raw,
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
        amount_raw = _require_positive_integer_string(amount_raw, field_name="amount_raw")
        asset = validate_solana_mint(asset)
        positions = await self.get_jupiter_earn_positions(users=[owner])
        matching_positions = [
            item
            for item in positions["positions"]
            if isinstance(item, dict)
            and str(item.get("asset") or item.get("mint") or "").strip() == asset
        ]
        if not matching_positions:
            raise WalletBackendError("No Jupiter Earn position found for the requested asset.")
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "jupiter-earn-withdraw",
            "owner": owner,
            "asset": asset,
            "amount_raw": amount_raw,
            "positions": matching_positions,
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

    async def preview_bags_fee_claim(self, token_mint: str) -> dict[str, Any]:
        self._require_mainnet_bags("Bags fee claims")
        owner = await self.get_address()
        if not owner:
            raise WalletBackendError(
                "No Solana wallet address configured. Set SOLANA_AGENT_PUBLIC_KEY or a signer."
            )
        normalized_mint = validate_solana_mint(token_mint)
        positions_payload = await self.get_bags_claimable_positions(owner)
        positions = [
            item
            for item in positions_payload["positions"]
            if str(item.get("tokenMint") or item.get("token_mint") or "").strip() == normalized_mint
        ]
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "bags-fee-claim",
            "owner": owner,
            "fee_claimer": owner,
            "token_mint": normalized_mint,
            "claimable_position_count": len(positions),
            "claimable_positions": positions,
            "sign_only": self.sign_only,
            "can_send": self.get_capabilities().can_send_transaction,
            "source": "bags",
        }

    async def execute_bags_fee_claim(
        self,
        token_mint: str,
    ) -> dict[str, Any]:
        preview = await self.preview_bags_fee_claim(token_mint)
        return await self.execute_bags_fee_claim_from_preview(preview)

    async def execute_bags_fee_claim_from_preview(
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
        if str(preview.get("asset_type") or "").strip().lower() != "bags-fee-claim":
            raise WalletBackendError("preview payload is not a Bags fee claim preview.")
        if str(preview.get("network") or self.network).strip().lower() != self.network:
            raise WalletBackendError("preview payload network does not match the wallet backend.")
        if str(preview.get("owner") or owner) != owner:
            raise WalletBackendError("preview payload owner does not match the connected wallet.")
        if int(preview.get("claimable_position_count") or 0) <= 0:
            raise WalletBackendError("No claimable Bags fee positions were found for this token.")

        token_mint = validate_solana_mint(str(preview.get("token_mint") or ""))
        claim_payload = await bags.build_claim_transactions(
            {
                "feeClaimer": owner,
                "tokenMint": token_mint,
            }
        )
        transactions = self._bags_extract_transaction_base64s(claim_payload)
        prepared = await self._prepare_bags_transactions(
            transaction_base64s=transactions,
            token_mint=token_mint,
            action="Bags fee claim",
            owner=owner,
            asset_type="bags-fee-claim",
            extra={
                "fee_claimer": owner,
                "claimable_position_count": int(preview.get("claimable_position_count") or 0),
                "claimable_positions": preview.get("claimable_positions"),
                "claim_response": claim_payload,
            },
        )
        result = await self._execute_prepared_bags_transactions(prepared)
        result["fee_claimer"] = owner
        result["claimable_position_count"] = int(preview.get("claimable_position_count") or 0)
        result["claimable_positions"] = preview.get("claimable_positions")
        result["claim_response"] = claim_payload
        return result

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
        slippage_bps: int = 50,
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
        if self._prefer_bags_swap_route(input_mint, output_mint):
            quote = await self._fetch_bags_swap_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount_raw=raw_amount,
                slippage_bps=slippage_bps,
            )
            quote_source = "bags"
        else:
            try:
                quote, quote_source = await self._fetch_jupiter_swap_quote(
                    input_mint=input_mint,
                    output_mint=output_mint,
                    amount_raw=raw_amount,
                    taker=sender,
                    slippage_bps=slippage_bps,
                )
            except ProviderError as jupiter_error:
                try:
                    quote = await self._fetch_bags_swap_quote(
                        input_mint=input_mint,
                        output_mint=output_mint,
                        amount_raw=raw_amount,
                        slippage_bps=slippage_bps,
                    )
                    quote_source = "bags"
                except ProviderError:
                    raise jupiter_error

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

    async def execute_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        preview = await self.preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        return await self.execute_swap_from_preview(preview)

    async def execute_swap_from_preview(
        self,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = await self.prepare_swap_from_preview(preview)
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

    async def prepare_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
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
        if swap_provider == "jupiter-ultra":
            swap_build = preview["quote_response"]
            unsigned_transaction = VersionedTransaction.from_bytes(
                base64.b64decode(str(swap_build["transaction"]))
            )
            request_id = swap_build.get("requestId")
            last_valid_block_height = swap_build.get("expireAt")
            prioritization_fee_lamports = swap_build.get("prioritizationFeeLamports")
            compute_unit_limit = swap_build.get("computeUnitLimit")
        elif swap_provider == "bags":
            swap_build = await bags.build_swap_transaction(
                user_public_key=sender,
                quote_response=preview["quote_response"],
            )
            unsigned_transaction = VersionedTransaction.from_bytes(
                base64.b64decode(str(swap_build["swapTransaction"]))
            )
            last_valid_block_height = swap_build.get("lastValidBlockHeight")
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
