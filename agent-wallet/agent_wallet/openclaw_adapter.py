"""Thin OpenClaw-facing adapter for agent wallet backends."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent_wallet.approval import inspect_approval_token, verify_approval_token
from agent_wallet.exceptions import ProviderError
from agent_wallet.models import AgentToolResult, AgentToolSpec
from agent_wallet.providers import x402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError


def _canonical_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def preview_payload_digest(preview: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_text(preview).encode("utf-8")).hexdigest()


WALLET_RUNTIME_INSTRUCTIONS = """
Use wallet tools only when the user explicitly asks for wallet-related actions.
Treat any signing request as sensitive.
Before signing a message, make sure the user intent is explicit and the purpose is clear.
Never claim that funds were moved unless a transfer tool explicitly returns a confirmed transaction result.
If the wallet backend is sign-only, do not describe the action as broadcast on-chain.
If the backend supports signing but should not broadcast, prefer preview and host-mediated execution planning instead of returning signed transactions to the agent.
For transfers, prefer preview mode first. Only use execute mode after explicit user approval.
Prepare mode must never expose signed transaction bytes to the agent.
Execute mode requires a host-issued approval token bound to the exact operation being performed.
On mainnet, execute mode requires an approval token that includes an explicit mainnet confirmation.
Before any mainnet execute, restate the network, operation type, asset, amount, and destination, validator, or stake account.
If the preview result includes a confirmation_summary or mainnet_warning, surface it before asking for confirmation.
Never bypass the approval token requirement for wallet writes.
In OpenClaw, switch between Solana, EVM, and Bitcoin wallets with set_wallet_backend.
The plugin config is the startup default, not something to edit during a normal conversation.
For EVM wallets, switch between Ethereum and Base with set_evm_network or by passing the
network argument to EVM tools. Do not edit code, plugin config, or environment variables
just to switch the active EVM network.
""".strip()

# Keep the backend implementation in place, but hide these agent-facing tools for now.
TEMPORARILY_DISABLED_TOOLS = {
    "get_jupiter_portfolio_platforms",
    "get_jupiter_portfolio",
    "get_jupiter_staked_jup",
}
EVM_NATIVE_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"
SOLANA_NATIVE_TOKEN_ADDRESS = "11111111111111111111111111111111"
LIFI_CHAIN_ALIASES = {
    "eth": "1",
    "ethereum": "1",
    "mainnet": "1",
    "eth-mainnet": "1",
    "1": "1",
    "base": "8453",
    "base-mainnet": "8453",
    "8453": "8453",
    "sol": "1151111081099710",
    "solana": "1151111081099710",
    "1151111081099710": "1151111081099710",
}


class OpenClawWalletAdapter:
    """Expose wallet backend primitives as safe agent-facing tools."""

    def __init__(self, backend: AgentWalletBackend):
        self.backend = backend

    def _is_mainnet_network(self, network: Any) -> bool:
        chain = str(getattr(self.backend, "chain", "")).strip().lower()
        normalized = str(network or "").strip().lower()
        if chain == "bitcoin":
            return normalized == "bitcoin"
        if chain == "evm":
            return normalized in {"ethereum", "base", "eip155:1", "eip155:8453"}
        if chain == "solana":
            return normalized in {"mainnet", "solana:5eykt4usfv8p8njdtrepy1vzkqzkvdp"}
        return normalized == "mainnet"

    def _is_mainnet(self) -> bool:
        return self._is_mainnet_network(getattr(self.backend, "network", ""))

    def _is_mainnet_for_backend(self, backend: AgentWalletBackend) -> bool:
        return self._is_mainnet_network(getattr(backend, "network", ""))

    def _supports_evm_velora(self) -> bool:
        return str(getattr(self.backend, "chain", "")).strip().lower() == "evm" and self._is_mainnet()

    def _supports_evm_velora_for_backend(self, backend: AgentWalletBackend) -> bool:
        return str(getattr(backend, "chain", "")).strip().lower() == "evm" and self._is_mainnet_for_backend(backend)

    def _normalize_evm_tool_network(self, value: Any) -> str:
        network = str(value or "").strip().lower()
        aliases = {
            "mainnet": "ethereum",
            "eth": "ethereum",
            "eth-mainnet": "ethereum",
            "base-mainnet": "base",
            "base_sepolia": "base-sepolia",
        }
        network = aliases.get(network, network)
        if network not in {"ethereum", "base"}:
            raise WalletBackendError("EVM network must be 'ethereum' or 'base'.")
        return network

    def _resolve_backend_for_args(self, args: dict[str, Any]) -> AgentWalletBackend:
        if str(getattr(self.backend, "chain", "")).strip().lower() != "evm":
            return self.backend
        requested_network = args.get("network")
        if requested_network is None:
            return self.backend
        if not isinstance(requested_network, str) or not requested_network.strip():
            raise WalletBackendError("network must be a non-empty string when provided.")
        return self.backend.with_network(self._normalize_evm_tool_network(requested_network))

    def _normalize_positive_limit(self, value: Any, *, field_name: str, default: int, maximum: int) -> int:
        if value is None:
            return default
        if not isinstance(value, int) or value <= 0:
            raise WalletBackendError(f"{field_name} must be a positive integer.")
        return min(value, maximum)

    def _normalize_lifi_slippage(self, value: Any) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise WalletBackendError("slippage must be a number when provided.")
        if value < 0 or value > 1:
            raise WalletBackendError("slippage must be between 0 and 1, for example 0.01 for 1%.")
        return value

    def _normalize_optional_string_list(self, value: Any, *, field_name: str) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
            return items or None
        if not isinstance(value, list):
            raise WalletBackendError(f"{field_name} must be an array of strings when provided.")
        items: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise WalletBackendError(f"{field_name} must contain only non-empty strings.")
            items.append(item.strip())
        return items

    def _canonicalize_lifi_chain_identifier(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        return LIFI_CHAIN_ALIASES.get(text, text)

    def _canonicalize_lifi_token_identifier(self, value: Any, *, chain_id: str) -> str:
        text = str(value or "").strip()
        alias = text.lower()
        if chain_id in {"1", "8453"}:
            if alias in {"native", "eth", "ethereum"}:
                return EVM_NATIVE_TOKEN_ADDRESS
            if alias.startswith("0x") and len(alias) == 42:
                return alias
            return text
        if chain_id == "1151111081099710" and alias in {"native", "sol", "solana"}:
            return SOLANA_NATIVE_TOKEN_ADDRESS
        return text

    def _require_prepare_intent(self, user_intent: Any) -> None:
        if user_intent is not True:
            raise WalletBackendError(
                "Prepare mode requires explicit user intent confirmation."
            )

    def _x402_tool_specs(self) -> list[AgentToolSpec]:
        return [
            AgentToolSpec(
                name="x402_search_services",
                description=(
                    "Search x402-paid services through CDP Bazaar or Agentic Market. "
                    "This is read-only discovery and does not spend funds."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "discovery_provider": {
                            "type": "string",
                            "enum": ["auto", "cdp_bazaar", "agentic_market"],
                        },
                        "network": {"type": "string"},
                        "asset": {"type": "string"},
                        "scheme": {"type": "string"},
                        "max_usd_price": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="x402_get_service_details",
                description=(
                    "Resolve one x402 service or resource into a normalized details payload. "
                    "Use a resource URL for CDP Bazaar or a domain/service id for Agentic Market."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "reference": {"type": "string"},
                        "discovery_provider": {
                            "type": "string",
                            "enum": ["auto", "cdp_bazaar", "agentic_market"],
                        },
                    },
                    "required": ["reference"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="x402_preview_request",
                description=(
                    "Make an unpaid HTTP request to an x402 endpoint, detect HTTP 402, parse "
                    "PAYMENT-REQUIRED, and summarize the payment options. This does not pay or execute."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "method": {"type": "string"},
                        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                        "query": {"type": "object", "additionalProperties": True},
                        "json_body": {},
                        "text_body": {"type": "string"},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="x402_pay_request",
                description=(
                    "Prepare or execute an x402 paid request using the active wallet backend. "
                    "This milestone executes the Solana exact buyer flow and keeps EVM as prepare-only."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "method": {"type": "string"},
                        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                        "query": {"type": "object", "additionalProperties": True},
                        "json_body": {},
                        "text_body": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["prepare", "execute"],
                            "description": "prepare validates the payment plan; execute sends the paid retry.",
                        },
                        "purpose": {"type": "string"},
                        "user_intent": {
                            "type": "boolean",
                            "description": "Must be true for prepare mode.",
                        },
                        "approval_token": {
                            "type": "string",
                            "description": "Required for execute mode and must be issued against the exact x402 payment summary.",
                        },
                    },
                    "required": ["url", "mode", "purpose"],
                    "additionalProperties": False,
                },
                read_only=False,
                requires_explicit_user_intent=True,
                risk_level="high",
            ),
        ]

    def _require_execute_approval(
        self,
        *,
        approval_token: Any,
        tool_name: str,
        summary: dict[str, Any],
        action_label: str,
        backend: AgentWalletBackend | None = None,
    ) -> None:
        active_backend = backend or self.backend
        if not isinstance(approval_token, str) or not approval_token.strip():
            raise WalletBackendError(
                f"{action_label} execution requires a host-issued approval_token."
            )
        verify_approval_token(
            approval_token.strip(),
            tool_name=tool_name,
            network=str(getattr(active_backend, "network", "unknown")),
            summary=summary,
            require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
        )
        # Enforce single-use: reject replayed approval tokens.
        from agent_wallet.nonce_registry import require_single_use

        require_single_use(approval_token.strip())

    def _build_confirmation_summary(
        self,
        *,
        action_label: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        asset_type = str(payload.get("asset_type") or "").strip().lower()
        if asset_type == "swap":
            swap_quote_binding = {
                "swap_provider": payload.get("swap_provider"),
                "estimated_output_amount_ui": payload.get("estimated_output_amount_ui"),
                "minimum_output_amount_ui": payload.get("minimum_output_amount_ui"),
                "price_impact_pct": payload.get("price_impact_pct"),
                "fee_summary": payload.get("fee_summary"),
                "route_plan": payload.get("route_plan"),
            }
            quote_fingerprint = hashlib.sha256(
                json.dumps(
                    swap_quote_binding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            summary: dict[str, Any] = {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "swap_provider": payload.get("swap_provider"),
                "estimated_output_amount_ui": payload.get("estimated_output_amount_ui"),
                "minimum_output_amount_ui": payload.get("minimum_output_amount_ui"),
                "price_impact_pct": payload.get("price_impact_pct"),
                "quote_fingerprint": quote_fingerprint,
            }
            for key in (
                "owner",
                "input_mint",
                "output_mint",
                "input_amount_ui",
                "input_amount_raw",
                "slippage_bps",
            ):
                value = payload.get(key)
                if value is not None:
                    summary[key] = value
            return summary

        if asset_type == "solana-lifi-cross-chain-swap":
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "swap_provider": payload.get("swap_provider"),
                "source_chain": payload.get("source_chain"),
                "source_chain_id": payload.get("source_chain_id"),
                "destination_chain": payload.get("destination_chain"),
                "destination_chain_id": payload.get("destination_chain_id"),
                "owner": payload.get("owner"),
                "input_token": payload.get("input_token"),
                "input_mint": payload.get("input_mint"),
                "output_token": payload.get("output_token"),
                "destination_address": payload.get("destination_address"),
                "input_amount_raw": payload.get("input_amount_raw"),
                "input_amount_ui": payload.get("input_amount_ui"),
                "estimated_output_amount_raw": payload.get("estimated_output_amount_raw"),
                "minimum_output_amount_raw": payload.get("minimum_output_amount_raw"),
                "slippage": payload.get("slippage"),
                "quote_type": payload.get("quote_type"),
                "quote_id": payload.get("quote_id"),
                "transaction_id": payload.get("transaction_id"),
                "tool": payload.get("tool"),
                "transaction_data_hash": payload.get("transaction_data_hash"),
            }

        if asset_type == "solana-private-swap":
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "swap_provider": payload.get("source") or "houdini",
                "owner": payload.get("owner"),
                "destination_address": payload.get("destination_address"),
                "input_token_id": payload.get("input_token_id"),
                "output_token_id": payload.get("output_token_id"),
                "input_token_symbol": payload.get("input_token_symbol"),
                "output_token_symbol": payload.get("output_token_symbol"),
                "input_token_address": payload.get("input_token_address"),
                "output_token_address": payload.get("output_token_address"),
                "input_amount_ui": payload.get("input_amount_ui"),
                "estimated_output_amount_ui": payload.get("estimated_output_amount_ui"),
                "private_duration_minutes": payload.get("private_duration_minutes"),
                "quote_id": payload.get("quote_id"),
                "anonymous": payload.get("anonymous"),
                "use_xmr": payload.get("use_xmr"),
            }

        if asset_type == "evm-lifi-cross-chain-swap":
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "swap_provider": payload.get("swap_provider"),
                "source_chain": payload.get("source_chain"),
                "destination_chain": payload.get("destination_chain"),
                "token_in": payload.get("token_in"),
                "output_token": payload.get("output_token"),
                "destination_address": payload.get("destination_address"),
                "input_amount_raw": payload.get("input_amount_raw"),
                "estimated_output_amount_raw": payload.get("estimated_output_amount_raw"),
                "minimum_output_amount_raw": payload.get("minimum_output_amount_raw"),
                "slippage_bps": payload.get("slippage_bps"),
                "slippage": payload.get("slippage"),
                "gas_drop": payload.get("gas_drop"),
                "quote_type": payload.get("quote_type"),
                "quote_id": payload.get("quote_id"),
                "tool": payload.get("tool"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "estimated_swap_fee_wei": payload.get("estimated_swap_fee_wei"),
                "estimated_approval_fee_wei": payload.get("estimated_approval_fee_wei"),
                "router": payload.get("router"),
            }

        if asset_type == "evm-swap":
            output_amount_raw = (
                payload.get("estimated_output_amount_raw")
                if payload.get("estimated_output_amount_raw") is not None
                else payload.get("output_amount_raw")
            )
            provided_fingerprint = payload.get("quote_fingerprint")
            evm_swap_binding = {
                "swap_provider": payload.get("swap_provider"),
                "token_in": payload.get("token_in"),
                "token_out": payload.get("token_out"),
                "input_amount_raw": payload.get("input_amount_raw"),
                "output_amount_raw": output_amount_raw,
                "minimum_output_amount_raw": payload.get("minimum_output_amount_raw"),
                "slippage_bps": payload.get("slippage_bps"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "router": payload.get("router"),
                "swap_transaction": payload.get("swap_transaction"),
                "quote_fingerprint": provided_fingerprint,
            }
            evm_swap_fingerprint = (
                str(provided_fingerprint).strip()
                if isinstance(provided_fingerprint, str) and str(provided_fingerprint).strip()
                else hashlib.sha256(
                    json.dumps(
                        evm_swap_binding,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            )
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "swap_provider": payload.get("swap_provider"),
                "token_in": payload.get("token_in"),
                "token_out": payload.get("token_out"),
                "input_amount_raw": payload.get("input_amount_raw"),
                "output_amount_raw": output_amount_raw,
                "minimum_output_amount_raw": payload.get("minimum_output_amount_raw"),
                "slippage_bps": payload.get("slippage_bps"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "estimated_swap_fee_wei": payload.get("estimated_swap_fee_wei"),
                "estimated_approval_fee_wei": payload.get("estimated_approval_fee_wei"),
                "quote_fingerprint": provided_fingerprint,
                "router": payload.get("router"),
                "swap_transaction": payload.get("swap_transaction"),
                "evm_swap_fingerprint": evm_swap_fingerprint,
            }

        if asset_type == "evm-aave-v3":
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "protocol": payload.get("protocol"),
                "aave_operation": payload.get("operation"),
                "token_address": payload.get("token_address"),
                "amount_raw": payload.get("amount_raw"),
                "amount_ui": payload.get("amount_ui"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "estimated_operation_fee_wei": payload.get("estimated_operation_fee_wei"),
                "estimated_approval_fee_wei": payload.get("estimated_approval_fee_wei"),
                "quote_fingerprint": payload.get("quote_fingerprint"),
                "allowance": payload.get("allowance"),
            }

        if asset_type == "evm-lido-staking":
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "protocol": payload.get("protocol"),
                "lido_operation": payload.get("operation"),
                "amount_raw": payload.get("amount_raw"),
                "amount_ui": payload.get("amount_ui"),
                "expected_output_amount_raw": payload.get("expected_output_amount_raw"),
                "expected_output_amount_ui": payload.get("expected_output_amount_ui"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "estimated_operation_fee_wei": payload.get("estimated_operation_fee_wei"),
                "estimated_approval_fee_wei": payload.get("estimated_approval_fee_wei"),
                "quote_fingerprint": payload.get("quote_fingerprint"),
                "allowance": payload.get("allowance"),
            }

        if asset_type == "evm-lido-withdrawal-queue":
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "protocol": payload.get("protocol"),
                "lido_withdrawal_operation": payload.get("operation"),
                "amount_raw": payload.get("amount_raw"),
                "amount_ui": payload.get("amount_ui"),
                "request_id": payload.get("request_id"),
                "queued_steth_amount_raw": payload.get("queued_steth_amount_raw"),
                "queued_steth_amount_ui": payload.get("queued_steth_amount_ui"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "estimated_operation_fee_wei": payload.get("estimated_operation_fee_wei"),
                "estimated_approval_fee_wei": payload.get("estimated_approval_fee_wei"),
                "quote_fingerprint": payload.get("quote_fingerprint"),
                "allowance": payload.get("allowance"),
            }

        if asset_type == "bags-token-launch":
            launch_binding = {
                "token_name": payload.get("token_name"),
                "token_symbol": payload.get("token_symbol"),
                "description": payload.get("description"),
                "image_url": payload.get("image_url"),
                "website": payload.get("website"),
                "twitter": payload.get("twitter"),
                "telegram": payload.get("telegram"),
                "discord": payload.get("discord"),
                "base_mint": payload.get("base_mint"),
                "claimers": payload.get("claimers"),
                "basis_points": payload.get("basis_points"),
                "initial_buy_lamports": payload.get("initial_buy_lamports"),
                "bags_config_type": payload.get("bags_config_type"),
            }
            launch_fingerprint = hashlib.sha256(
                json.dumps(
                    launch_binding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "owner": payload.get("owner"),
                "wallet": payload.get("wallet"),
                "token_name": payload.get("token_name"),
                "token_symbol": payload.get("token_symbol"),
                "base_mint": payload.get("base_mint"),
                "claimers_count": payload.get("claimers_count"),
                "total_basis_points": payload.get("total_basis_points"),
                "initial_buy_sol": payload.get("initial_buy_sol"),
                "initial_buy_lamports": payload.get("initial_buy_lamports"),
                "launch_fingerprint": launch_fingerprint,
            }

        if asset_type == "bags-fee-claim":
            claim_binding = {
                "token_mint": payload.get("token_mint"),
                "claimable_positions": payload.get("claimable_positions"),
                "claimable_position_count": payload.get("claimable_position_count"),
            }
            claim_fingerprint = hashlib.sha256(
                json.dumps(
                    claim_binding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "owner": payload.get("owner"),
                "fee_claimer": payload.get("fee_claimer"),
                "token_mint": payload.get("token_mint"),
                "claimable_position_count": payload.get("claimable_position_count"),
                "claim_fingerprint": claim_fingerprint,
            }

        if asset_type in {"flash-trade-open-position", "flash-trade-close-position"}:
            flash_binding = {
                "pool_name": payload.get("pool_name"),
                "market_symbol": payload.get("market_symbol"),
                "collateral_symbol": payload.get("collateral_symbol"),
                "collateral_amount_raw": payload.get("collateral_amount_raw"),
                "leverage": payload.get("leverage"),
                "side": payload.get("side"),
                "estimated_size_usd": payload.get("estimated_size_usd"),
                "estimated_entry_price": payload.get("estimated_entry_price"),
                "estimated_liquidation_price": payload.get("estimated_liquidation_price"),
                "position_size_usd": payload.get("position_size_usd"),
                "close_amount_raw": payload.get("close_amount_raw"),
            }
            flash_fingerprint = hashlib.sha256(
                json.dumps(
                    flash_binding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "owner": payload.get("owner"),
                "pool_name": payload.get("pool_name"),
                "market_symbol": payload.get("market_symbol"),
                "collateral_symbol": payload.get("collateral_symbol"),
                "collateral_amount_raw": payload.get("collateral_amount_raw"),
                "leverage": payload.get("leverage"),
                "side": payload.get("side"),
                "estimated_size_usd": payload.get("estimated_size_usd"),
                "estimated_entry_price": payload.get("estimated_entry_price"),
                "estimated_liquidation_price": payload.get("estimated_liquidation_price"),
                "position_size_usd": payload.get("position_size_usd"),
                "close_amount_raw": payload.get("close_amount_raw"),
                "flash_preview_fingerprint": flash_fingerprint,
            }

        if asset_type == "btc-transfer":
            btc_binding = {
                "recipient": payload.get("recipient"),
                "amount_sats": payload.get("amount_sats"),
                "fee_rate": payload.get("fee_rate"),
                "confirmation_target": payload.get("confirmation_target"),
                "estimated_fee_sats": payload.get("estimated_fee_sats"),
            }
            btc_fingerprint = hashlib.sha256(
                json.dumps(
                    btc_binding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "recipient": payload.get("recipient"),
                "amount_sats": payload.get("amount_sats"),
                "estimated_fee_sats": payload.get("estimated_fee_sats"),
                "fee_rate": payload.get("fee_rate"),
                "confirmation_target": payload.get("confirmation_target"),
                "btc_transfer_fingerprint": btc_fingerprint,
            }

        if asset_type == "x402-request":
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "request_url": payload.get("request_url"),
                "method": payload.get("method"),
                "request_fingerprint": payload.get("request_fingerprint"),
                "body_hash": payload.get("body_hash"),
                "x402_network": payload.get("x402_network"),
                "x402_scheme": payload.get("x402_scheme"),
                "x402_asset": payload.get("x402_asset"),
                "x402_amount": payload.get("x402_amount"),
                "x402_amount_display": payload.get("x402_amount_display"),
                "x402_pay_to": payload.get("x402_pay_to"),
            }

        if asset_type == "evm-native-transfer":
            evm_binding = {
                "recipient": payload.get("recipient"),
                "amount_wei": payload.get("amount_wei"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
            }
            evm_fingerprint = hashlib.sha256(
                json.dumps(
                    evm_binding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "recipient": payload.get("recipient"),
                "amount_wei": payload.get("amount_wei"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "evm_transfer_fingerprint": evm_fingerprint,
            }

        if asset_type == "evm-token-transfer":
            evm_token_binding = {
                "recipient": payload.get("recipient"),
                "token_address": payload.get("token_address"),
                "amount_raw": payload.get("amount_raw"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
            }
            evm_token_fingerprint = hashlib.sha256(
                json.dumps(
                    evm_token_binding,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
                "wallet": payload.get("wallet"),
                "from_address": payload.get("from_address"),
                "recipient": payload.get("recipient"),
                "token_address": payload.get("token_address"),
                "amount_raw": payload.get("amount_raw"),
                "estimated_fee_wei": payload.get("estimated_fee_wei"),
                "evm_token_transfer_fingerprint": evm_token_fingerprint,
            }

        summary: dict[str, Any] = {
            "operation": action_label,
            "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
        }
        for key in (
            "owner",
            "authority",
            "address",
            "market",
            "reserve",
            "amount_native",
            "amount_ui",
            "input_amount_ui",
            "estimated_output_amount_ui",
            "amount_raw",
            "mint",
            "asset",
            "input_mint",
            "output_mint",
            "from_address",
            "to_address",
            "recipient",
            "vote_account",
            "stake_account",
            "stake_account_address",
            "wallet",
            "fee_claimer",
            "token_mint",
            "token_name",
            "token_symbol",
            "base_mint",
            "claimable_position_count",
            "claimers_count",
            "total_basis_points",
            "initial_buy_sol",
            "initial_buy_lamports",
            "amount_sats",
            "estimated_fee_sats",
            "fee_rate",
            "confirmation_target",
            "amount_wei",
            "estimated_fee_wei",
            "token_address",
            "amount_raw",
            "token_in",
            "token_out",
            "input_amount_raw",
            "estimated_output_amount_raw",
            "output_amount_raw",
            "swap_provider",
        ):
            value = payload.get(key)
            if value is not None:
                summary[key] = value
        return summary

    def _build_prepare_plan(
        self,
        *,
        preview_payload: dict[str, Any],
        action_label: str,
    ) -> dict[str, Any]:
        plan = dict(preview_payload)
        plan["mode"] = "prepare"
        plan["prepared"] = False
        plan["signed"] = False
        plan["broadcasted"] = False
        plan["confirmed"] = False
        plan["execution_plan_only"] = True
        plan["prepare_note"] = (
            "Signed transaction bytes are intentionally not returned by prepare mode. "
            "Use this as an execution plan and perform final signing or broadcast only through execute or a host-controlled path."
        )
        for key in (
            "transaction_base64",
            "transaction_encoding",
            "transaction_format",
            "signature",
            "last_valid_block_height",
            "latest_blockhash",
            "request_id",
            "verification",
        ):
            plan.pop(key, None)
        return plan

    def _annotate_sensitive_payload(
        self,
        payload: dict[str, Any],
        *,
        action_label: str,
        mode: str,
    ) -> dict[str, Any]:
        annotated = dict(payload)
        network = str(annotated.get("network") or getattr(self.backend, "network", "unknown")).strip().lower()
        is_mainnet = self._is_mainnet_network(network)
        annotated["network"] = network
        annotated["is_mainnet"] = is_mainnet
        annotated["confirmation_summary"] = self._build_confirmation_summary(
            action_label=action_label,
            payload=annotated,
        )
        annotated["confirmation_requirements"] = {
            "prepare_requires_user_intent": mode == "prepare",
            "execute_requires_approval_token": True,
            "execute_requires_mainnet_confirmed_in_token": is_mainnet,
        }
        if mode == "preview":
            annotated["approval_hint"] = {
                "host_must_issue_token_for": annotated["confirmation_summary"],
                "tool_name": None,
            }
        if is_mainnet and mode in {"preview", "prepare", "execute"}:
            annotated["mainnet_warning"] = (
                "Mainnet operation. Confirm the network, asset, amount, and destination, validator, or stake account "
                "before execute. Execute requires a host-issued approval token with mainnet confirmation."
            )
        return annotated

    def list_tools(self) -> list[AgentToolSpec]:
        """Return wallet tools suitable for agent registration."""
        capabilities = self.backend.get_capabilities()
        if capabilities.chain == "evm":
            tools = [
                AgentToolSpec(
                    name="get_wallet_capabilities",
                    description="Describe the connected wallet backend, chain, and safety limits.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_wallet_address",
                    description="Return the configured wallet address for the connected backend.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_wallet_balance",
                    description=(
                        "Get the EVM wallet overview: native asset, discovered ERC-20 balances, "
                        "per-asset USD values, assets, balance_usd, and total_value_usd when available. "
                        "Prices come from aggregator APIs, not RPC."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "address": {
                                "type": "string",
                                "description": "Optional wallet address override.",
                            },
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_lifi_supported_chains",
                    description="List the LI.FI chains currently allowed for OpenClaw cross-chain routing.",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_lifi_quote",
                    description="Get a read-only LI.FI cross-chain quote for Ethereum/Base/Solana routes. Execution is not enabled by this tool.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "from_chain": {"type": "string", "description": "Source chain: ethereum, base, solana, or the LI.FI chain id."},
                            "to_chain": {"type": "string", "description": "Destination chain: ethereum, base, solana, or the LI.FI chain id."},
                            "from_token": {"type": "string", "description": "Source token address. Use native/eth/sol for native tokens."},
                            "to_token": {"type": "string", "description": "Destination token address. Use native/eth/sol for native tokens."},
                            "amount_in_raw": {
                                "type": "string",
                                "description": "Input amount in token base units as a base-10 integer string.",
                            },
                            "from_address": {
                                "type": "string",
                                "description": "Optional source wallet address. Defaults to the active wallet when the source chain matches it.",
                            },
                            "to_address": {
                                "type": "string",
                                "description": "Optional destination wallet address. Defaults to the active wallet when the destination chain matches it.",
                            },
                            "slippage": {
                                "type": "number",
                                "description": "Optional decimal fraction, for example 0.01 for 1%.",
                            },
                            "allow_bridges": {"type": "array", "items": {"type": "string"}},
                            "deny_bridges": {"type": "array", "items": {"type": "string"}},
                            "prefer_bridges": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["from_chain", "to_chain", "from_token", "to_token", "amount_in_raw"],
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_lifi_transfer_status",
                    description="Get LI.FI cross-chain transfer status using a source/destination transaction hash or LI.FI step id.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "tx_hash": {"type": "string"},
                            "bridge": {"type": "string"},
                            "from_chain": {"type": "string"},
                            "to_chain": {"type": "string"},
                        },
                        "required": ["tx_hash"],
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_evm_network",
                    description="Show the effective EVM network context, available networks, and swap-supported networks.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="set_evm_network",
                    description=(
                        "Select the active EVM network for subsequent wallet tool calls in this "
                        "runtime session. Use this to switch between ethereum and base instead "
                        "of editing code or plugin configuration."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "EVM network to make active for subsequent calls.",
                            },
                        },
                        "required": ["network"],
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_evm_token_balance",
                    description="Get the ERC-20 token balance for the configured EVM wallet account.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "token_address": {
                                "type": "string",
                                "description": "ERC-20 token contract address.",
                            },
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "required": ["token_address"],
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_evm_token_metadata",
                    description="Get ERC-20 token metadata for a contract address on the active EVM network.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "token_address": {
                                "type": "string",
                                "description": "ERC-20 token contract address.",
                            },
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "required": ["token_address"],
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_evm_fee_rates",
                    description="Get current EVM fee-rate suggestions for the active network.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_evm_transaction_receipt",
                    description="Get the transaction receipt for a broadcast EVM transaction hash.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "tx_hash": {
                                "type": "string",
                                "description": "0x-prefixed EVM transaction hash.",
                            },
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "required": ["tx_hash"],
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="transfer_evm_native",
                    description=(
                        "Preview, prepare, or execute a native EVM transfer using an amount in wei. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "recipient": {"type": "string"},
                            "amount_wei": {
                                "type": "string",
                                "description": "Transfer amount in wei as a base-10 integer string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                            },
                            "purpose": {"type": "string"},
                            "user_intent": {"type": "boolean"},
                            "approval_token": {"type": "string"},
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "required": ["recipient", "amount_wei", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                ),
                AgentToolSpec(
                    name="transfer_evm_token",
                    description=(
                        "Preview, prepare, or execute an ERC-20 transfer using a raw base-unit amount. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "token_address": {"type": "string"},
                            "recipient": {"type": "string"},
                            "amount_raw": {
                                "type": "string",
                                "description": "Transfer amount in token base units as a base-10 integer string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                            },
                            "purpose": {"type": "string"},
                            "user_intent": {"type": "boolean"},
                            "approval_token": {"type": "string"},
                            "network": {
                                "type": "string",
                                "enum": ["ethereum", "base"],
                                "description": "Optional EVM network override for this request.",
                            },
                        },
                        "required": ["token_address", "recipient", "amount_raw", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                ),
            ]

            if self._supports_evm_velora():
                tools.insert(
                    6,
                    AgentToolSpec(
                        name="get_evm_aave_account",
                        description="Get read-only Aave V3 account data for the configured EVM wallet on supported mainnet networks.",
                        input_schema={
                            "type": "object",
                            "properties": {
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum", "base"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    7,
                    AgentToolSpec(
                        name="get_evm_aave_reserves",
                        description="Get the read-only Aave V3 reserve catalog for the configured EVM network, including reserve flags, pricing, and liquidity metadata.",
                        input_schema={
                            "type": "object",
                            "properties": {
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum", "base"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    8,
                    AgentToolSpec(
                        name="get_evm_aave_positions",
                        description="Get read-only Aave V3 per-reserve positions for the configured EVM wallet, including supplied and borrowed balances on supported mainnet networks.",
                        input_schema={
                            "type": "object",
                            "properties": {
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum", "base"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    9,
                    AgentToolSpec(
                        name="manage_evm_aave_position",
                        description=(
                            "Preview, prepare, or execute a narrow Aave V3 lending operation on supported EVM mainnet networks. "
                            "Supported operations are supply, withdraw, borrow, and repay. Prepare returns an execution plan only, "
                            "and execute requires a host-issued approval token bound to the previewed operation."
                        ),
                        input_schema={
                            "type": "object",
                            "properties": {
                                "operation": {
                                    "type": "string",
                                    "enum": ["supply", "withdraw", "borrow", "repay"],
                                },
                                "token_address": {
                                    "type": "string",
                                    "description": "Underlying ERC-20 reserve token address.",
                                },
                                "amount_raw": {
                                    "type": "string",
                                    "description": "Amount in token base units as a base-10 integer string.",
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["preview", "prepare", "execute"],
                                },
                                "purpose": {"type": "string"},
                                "user_intent": {"type": "boolean"},
                                "approval_token": {"type": "string"},
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum", "base"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "required": ["operation", "token_address", "amount_raw", "mode", "purpose"],
                            "additionalProperties": False,
                        },
                        read_only=False,
                        requires_explicit_user_intent=True,
                        risk_level="high",
                    ),
                )
                tools.insert(
                    10,
                    AgentToolSpec(
                        name="get_evm_lido_overview",
                        description="Get the read-only Lido staking overview for the configured EVM wallet on supported networks, including contract addresses and sample wrap rates.",
                        input_schema={
                            "type": "object",
                            "properties": {
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    11,
                    AgentToolSpec(
                        name="get_evm_lido_positions",
                        description="Get read-only Lido positions for the configured EVM wallet, including stETH, wstETH, and stETH-equivalent balances.",
                        input_schema={
                            "type": "object",
                            "properties": {
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    12,
                    AgentToolSpec(
                        name="manage_evm_lido_position",
                        description=(
                            "Preview, prepare, or execute a narrow Lido staking operation on Ethereum mainnet. "
                            "Supported operations are stake_eth_for_wsteth, wrap_steth, and unwrap_wsteth. "
                            "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                        ),
                        input_schema={
                            "type": "object",
                            "properties": {
                                "operation": {
                                    "type": "string",
                                    "enum": ["stake_eth_for_wsteth", "wrap_steth", "unwrap_wsteth"],
                                },
                                "amount_raw": {
                                    "type": "string",
                                    "description": "Amount in base units as a base-10 integer string.",
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["preview", "prepare", "execute"],
                                },
                                "purpose": {"type": "string"},
                                "user_intent": {"type": "boolean"},
                                "approval_token": {"type": "string"},
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "required": ["operation", "amount_raw", "mode", "purpose"],
                            "additionalProperties": False,
                        },
                        read_only=False,
                        requires_explicit_user_intent=True,
                        risk_level="high",
                    ),
                )
                tools.insert(
                    13,
                    AgentToolSpec(
                        name="get_evm_lido_withdrawal_requests",
                        description="Get read-only Lido withdrawal queue requests for the configured EVM wallet, including finalized and claimable request statuses.",
                        input_schema={
                            "type": "object",
                            "properties": {
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    14,
                    AgentToolSpec(
                        name="manage_evm_lido_withdrawal",
                        description=(
                            "Preview, prepare, or execute a narrow Lido withdrawal queue operation on Ethereum mainnet. "
                            "Supported operations are request_withdrawal_steth, request_withdrawal_wsteth, and claim_withdrawal. "
                            "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                        ),
                        input_schema={
                            "type": "object",
                            "properties": {
                                "operation": {
                                    "type": "string",
                                    "enum": [
                                        "request_withdrawal_steth",
                                        "request_withdrawal_wsteth",
                                        "claim_withdrawal",
                                    ],
                                },
                                "amount_raw": {
                                    "type": "string",
                                    "description": "Amount in base units as a base-10 integer string. Required for request operations.",
                                },
                                "request_id": {
                                    "type": "string",
                                    "description": "Withdrawal request id as a base-10 integer string. Required for claim_withdrawal.",
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["preview", "prepare", "execute"],
                                },
                                "purpose": {"type": "string"},
                                "user_intent": {"type": "boolean"},
                                "approval_token": {"type": "string"},
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "required": ["operation", "mode", "purpose"],
                            "additionalProperties": False,
                        },
                        read_only=False,
                        requires_explicit_user_intent=True,
                        risk_level="high",
                    ),
                )
                tools.insert(
                    8,
                    AgentToolSpec(
                        name="get_evm_swap_quote",
                        description=(
                            "Get a read-only Velora quote for an ERC-20 to ERC-20 swap on supported EVM mainnet networks. "
                            "This does not approve or execute a swap."
                        ),
                        input_schema={
                            "type": "object",
                            "properties": {
                                "token_in": {
                                    "type": "string",
                                    "description": "ERC-20 contract address for the input token.",
                                },
                                "token_out": {
                                    "type": "string",
                                    "description": "ERC-20 contract address for the output token.",
                                },
                                "amount_in_raw": {
                                    "type": "string",
                                    "description": "Input amount in token base units as a base-10 integer string.",
                                },
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum", "base"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "required": ["token_in", "token_out", "amount_in_raw"],
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    9,
                    AgentToolSpec(
                        name="swap_evm_tokens",
                        description=(
                            "Preview, prepare, or execute an ERC-20 to ERC-20 swap through Velora on supported EVM mainnet networks. "
                            "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                        ),
                        input_schema={
                            "type": "object",
                            "properties": {
                                "token_in": {"type": "string"},
                                "token_out": {"type": "string"},
                                "amount_in_raw": {
                                    "type": "string",
                                    "description": "Input amount in token base units as a base-10 integer string.",
                                },
                                "mode": {
                                    "type": "string",
                                    "enum": ["preview", "prepare", "execute"],
                                },
                                "purpose": {"type": "string"},
                                "user_intent": {"type": "boolean"},
                                "approval_token": {"type": "string"},
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum", "base"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "required": ["token_in", "token_out", "amount_in_raw", "mode", "purpose"],
                            "additionalProperties": False,
                        },
                        read_only=False,
                        requires_explicit_user_intent=True,
                        risk_level="high",
                    ),
                )
                tools.insert(
                    10,
                    AgentToolSpec(
                        name="swap_evm_lifi_cross_chain_tokens",
                        description=(
                            "Preview, prepare, or execute an EVM-origin cross-chain swap through LI.FI. "
                            "This currently supports ethereum/base as the source network and ethereum/base/solana as the destination chain. "
                            "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                        ),
                        input_schema={
                            "type": "object",
                            "properties": {
                                "token_in": {
                                    "type": "string",
                                    "description": "Source EVM token contract address, native, eth, or the zero address for native ETH.",
                                },
                                "destination_chain": {
                                    "type": "string",
                                    "enum": [
                                        "ethereum",
                                        "base",
                                        "solana",
                                        "1",
                                        "8453",
                                        "1151111081099710",
                                    ],
                                },
                                "output_token": {
                                    "type": "string",
                                    "description": "Destination token identifier, for example the Solana USDC mint.",
                                },
                                "destination_address": {
                                    "type": "string",
                                    "description": "Destination wallet address on the target chain.",
                                },
                                "amount_in_raw": {
                                    "type": "string",
                                    "description": "Input amount in token base units as a base-10 integer string.",
                                },
                                "slippage": {
                                    "type": "number",
                                    "description": "Optional decimal fraction, for example 0.01 for 1%.",
                                },
                                "allow_bridges": {"type": "array", "items": {"type": "string"}},
                                "deny_bridges": {"type": "array", "items": {"type": "string"}},
                                "prefer_bridges": {"type": "array", "items": {"type": "string"}},
                                "mode": {
                                    "type": "string",
                                    "enum": ["preview", "prepare", "execute"],
                                },
                                "purpose": {"type": "string"},
                                "user_intent": {"type": "boolean"},
                                "approval_token": {"type": "string"},
                                "network": {
                                    "type": "string",
                                    "enum": ["ethereum", "base"],
                                    "description": "Optional EVM network override for this request.",
                                },
                            },
                            "required": [
                                "token_in",
                                "destination_chain",
                                "output_token",
                                "destination_address",
                                "amount_in_raw",
                                "mode",
                                "purpose",
                            ],
                            "additionalProperties": False,
                        },
                        read_only=False,
                        requires_explicit_user_intent=True,
                        risk_level="high",
                    ),
                )

            return tools

        if capabilities.chain == "bitcoin":
            return [
                AgentToolSpec(
                    name="get_wallet_capabilities",
                    description="Describe the connected wallet backend, chain, and safety limits.",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_wallet_address",
                    description="Return the configured wallet address for the connected backend.",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_wallet_balance",
                    description="Get the native token balance for the configured wallet address.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "address": {
                                "type": "string",
                                "description": "Optional wallet address override.",
                            }
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_btc_transfer_history",
                    description="Get BTC transfer history for the configured wallet account.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["incoming", "outgoing", "all"],
                                "description": "Optional transfer direction filter.",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of transfers to return. Defaults to 10.",
                            },
                            "skip": {
                                "type": "integer",
                                "description": "Optional offset for paginated history queries.",
                            },
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_btc_fee_rates",
                    description="Get current BTC fee-rate suggestions from the connected wallet service.",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="get_btc_max_spendable",
                    description="Estimate the maximum BTC amount spendable after fees for the configured wallet account.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "fee_rate": {
                                "type": "integer",
                                "description": "Optional fee rate in sats/vB to price the estimate.",
                            }
                        },
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                ),
                AgentToolSpec(
                    name="transfer_btc",
                    description=(
                        "Preview, prepare, or execute a BTC transfer in satoshis. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "recipient": {"type": "string"},
                            "amount_sats": {
                                "type": "integer",
                                "description": "Transfer amount in satoshis.",
                            },
                            "fee_rate": {
                                "type": "integer",
                                "description": "Optional fee rate in sats/vB.",
                            },
                            "confirmation_target": {
                                "type": "integer",
                                "description": "Optional target confirmation blocks for fee estimation.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                            },
                            "purpose": {"type": "string"},
                            "user_intent": {"type": "boolean"},
                            "approval_token": {"type": "string"},
                        },
                        "required": ["recipient", "amount_sats", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                ),
            ]
        tools = [
            AgentToolSpec(
                name="get_wallet_capabilities",
                description="Describe the connected wallet backend, chain, and safety limits.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_wallet_address",
                description="Return the configured wallet address for the connected backend.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_wallet_balance",
                description=(
                    "Get the wallet overview for the configured Solana address: native SOL, "
                    "non-zero SPL token accounts, per-asset USD values when available, and total_value_usd. "
                    "Prices come from Jupiter, not Solana RPC."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Optional wallet address override. If omitted, use the configured wallet address.",
                        }
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_lifi_supported_chains",
                description="List the LI.FI chains currently allowed for OpenClaw cross-chain routing.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_lifi_quote",
                description="Get a read-only LI.FI cross-chain quote for Ethereum/Base/Solana routes. Execution is not enabled by this tool.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "from_chain": {"type": "string", "description": "Source chain: ethereum, base, solana, or the LI.FI chain id."},
                        "to_chain": {"type": "string", "description": "Destination chain: ethereum, base, solana, or the LI.FI chain id."},
                        "from_token": {"type": "string", "description": "Source token address. Use native/eth/sol for native tokens."},
                        "to_token": {"type": "string", "description": "Destination token address. Use native/eth/sol for native tokens."},
                        "amount_in_raw": {
                            "type": "string",
                            "description": "Input amount in token base units as a base-10 integer string.",
                        },
                        "from_address": {
                            "type": "string",
                            "description": "Optional source wallet address. Defaults to the active wallet when the source chain matches it.",
                        },
                        "to_address": {
                            "type": "string",
                            "description": "Optional destination wallet address. Defaults to the active wallet when the destination chain matches it.",
                        },
                        "slippage": {
                            "type": "number",
                            "description": "Optional decimal fraction, for example 0.01 for 1%.",
                        },
                        "allow_bridges": {"type": "array", "items": {"type": "string"}},
                        "deny_bridges": {"type": "array", "items": {"type": "string"}},
                        "prefer_bridges": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["from_chain", "to_chain", "from_token", "to_token", "amount_in_raw"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_lifi_transfer_status",
                description="Get LI.FI cross-chain transfer status using a source/destination transaction hash or LI.FI step id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "tx_hash": {"type": "string"},
                        "bridge": {"type": "string"},
                        "from_chain": {"type": "string"},
                        "to_chain": {"type": "string"},
                    },
                    "required": ["tx_hash"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_wallet_portfolio",
                description=(
                    "Get the Solana wallet portfolio. This is the detailed equivalent of get_wallet_balance "
                    "and includes native SOL, non-zero SPL token accounts, USD pricing when available, and total_value_usd."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Optional wallet address override. If omitted, use the configured wallet address.",
                        }
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_solana_token_prices",
                description="Get current token prices for one or more Solana mint addresses via Jupiter.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "mints": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of Solana token mint addresses.",
                        }
                    },
                    "required": ["mints"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_bags_claimable_positions",
                description="Get claimable Bags fee-share positions for a Solana wallet on mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "wallet": {
                            "type": "string",
                            "description": "Optional wallet address override. If omitted, use the configured wallet address.",
                        }
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_bags_fee_analytics",
                description="Get Bags fee analytics for a launched token, with optional claim event history.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "token_mint": {
                            "type": "string",
                            "description": "Launched token mint address.",
                        },
                        "include_claim_events": {
                            "type": "boolean",
                            "description": "If true, also fetch claim event history.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["offset", "time"],
                            "description": "Claim event pagination mode when include_claim_events is true.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional event page size.",
                        },
                        "offset": {
                            "type": "integer",
                            "description": "Optional event offset when mode=offset.",
                        },
                        "from_ts": {
                            "type": "integer",
                            "description": "Optional unix timestamp start when mode=time.",
                        },
                        "to_ts": {
                            "type": "integer",
                            "description": "Optional unix timestamp end when mode=time.",
                        },
                    },
                    "required": ["token_mint"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_solana_staking_validators",
                description="List native Solana staking validators by vote account, commission, and activated stake.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of validators to return. Defaults to 20.",
                        },
                        "include_delinquent": {
                            "type": "boolean",
                            "description": "If true, include delinquent validators after current ones.",
                        },
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_solana_stake_account",
                description="Inspect a native Solana stake account and its activation status.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "stake_account": {
                            "type": "string",
                            "description": "Stake account address to inspect.",
                        }
                    },
                    "required": ["stake_account"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_jupiter_portfolio_platforms",
                description="List the Jupiter Portfolio platforms available for filtering position queries.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_jupiter_portfolio",
                description=(
                    "Get Jupiter Portfolio positions for a Solana wallet address on mainnet."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Optional Solana wallet address override. If omitted, use the configured wallet.",
                        },
                        "platforms": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of Jupiter platform ids to filter positions.",
                        },
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_jupiter_staked_jup",
                description="Get Jupiter staked JUP information for a Solana wallet address on mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Optional Solana wallet address override. If omitted, use the configured wallet.",
                        }
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_jupiter_earn_tokens",
                description="List Jupiter Earn vault tokens currently supported on Solana mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_jupiter_earn_positions",
                description="Get Jupiter Earn positions for one or more Solana wallet addresses on mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "users": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of Solana wallet addresses. If omitted, use the configured wallet address.",
                        }
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_jupiter_earn_earnings",
                description="Get Jupiter Earn earnings for a wallet and one or more position addresses on mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "user": {
                            "type": "string",
                            "description": "Optional Solana wallet address override. If omitted, use the configured wallet.",
                        },
                        "positions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of Jupiter Earn position addresses.",
                        },
                    },
                    "required": ["positions"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_flash_trade_markets",
                description="List Flash Trade perpetual markets currently available on Solana mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pool_name": {
                            "type": "string",
                            "description": "Optional Flash pool identifier such as Crypto.1.",
                        }
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_flash_trade_positions",
                description="Get Flash Trade perpetual positions for a Solana wallet on mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {
                            "type": "string",
                            "description": "Optional Solana wallet address override. If omitted, use the configured wallet.",
                        },
                        "pool_name": {
                            "type": "string",
                            "description": "Optional Flash pool identifier such as Crypto.1.",
                        },
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="flash_trade_open_position",
                description=(
                    "Preview, prepare, or execute a Flash Trade perpetual open on Solana mainnet using a supported Flash collateral."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "pool_name": {
                            "type": "string",
                            "description": "Flash pool identifier such as Crypto.1.",
                        },
                        "market_symbol": {
                            "type": "string",
                            "description": "Flash market symbol such as SOL or BTC.",
                        },
                        "collateral_symbol": {
                            "type": "string",
                            "description": "Flash collateral symbol, for example SOL for SOL longs or USDC for SOL shorts.",
                        },
                        "collateral_amount_raw": {
                            "type": "string",
                            "description": "Collateral amount in raw token units.",
                        },
                        "leverage": {
                            "type": "string",
                            "description": "Requested leverage as a decimal string such as 5 or 7.5.",
                        },
                        "side": {
                            "type": "string",
                            "enum": ["long", "short"],
                            "description": "Position direction.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["preview", "prepare", "execute"],
                            "description": "preview returns trade details; prepare returns an execution plan; execute broadcasts after host approval.",
                        },
                        "purpose": {
                            "type": "string",
                            "description": "Short explanation of why the position should be opened.",
                        },
                        "user_intent": {
                            "type": "boolean",
                            "description": "Must be true for prepare mode.",
                        },
                        "approval_token": {
                            "type": "string",
                            "description": "Host-issued approval token required for execute mode.",
                        },
                    },
                    "required": [
                        "pool_name",
                        "market_symbol",
                        "collateral_symbol",
                        "collateral_amount_raw",
                        "leverage",
                        "side",
                        "mode",
                        "purpose",
                    ],
                    "additionalProperties": False,
                },
                read_only=False,
                requires_explicit_user_intent=True,
                risk_level="high",
            ),
            AgentToolSpec(
                name="flash_trade_close_position",
                description=(
                    "Preview, prepare, or execute a Flash Trade perpetual close on Solana mainnet."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "pool_name": {
                            "type": "string",
                            "description": "Flash pool identifier such as Crypto.1.",
                        },
                        "market_symbol": {
                            "type": "string",
                            "description": "Flash market symbol such as SOL or BTC.",
                        },
                        "side": {
                            "type": "string",
                            "enum": ["long", "short"],
                            "description": "Position direction to close.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["preview", "prepare", "execute"],
                            "description": "preview returns close details; prepare returns an execution plan; execute broadcasts after host approval.",
                        },
                        "purpose": {
                            "type": "string",
                            "description": "Short explanation of why the position should be closed.",
                        },
                        "user_intent": {
                            "type": "boolean",
                            "description": "Must be true for prepare mode.",
                        },
                        "approval_token": {
                            "type": "string",
                            "description": "Host-issued approval token required for execute mode.",
                        },
                    },
                    "required": [
                        "pool_name",
                        "market_symbol",
                        "side",
                        "mode",
                        "purpose",
                    ],
                    "additionalProperties": False,
                },
                read_only=False,
                requires_explicit_user_intent=True,
                risk_level="high",
            ),
            AgentToolSpec(
                name="get_kamino_lend_markets",
                description="List Kamino lending markets currently available on Solana mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_kamino_lend_market_reserves",
                description="Get reserve metrics for one Kamino lending market on Solana mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "market": {
                            "type": "string",
                            "description": "Kamino market address.",
                        }
                    },
                    "required": ["market"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_kamino_lend_user_obligations",
                description="Get Kamino obligations for a wallet in a specific Kamino market on Solana mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "market": {
                            "type": "string",
                            "description": "Kamino market address.",
                        },
                        "user": {
                            "type": "string",
                            "description": "Optional Solana wallet address override. If omitted, use the configured wallet.",
                        },
                    },
                    "required": ["market"],
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
            AgentToolSpec(
                name="get_kamino_lend_user_rewards",
                description="Get Kamino rewards summary for a Solana wallet on mainnet.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "user": {
                            "type": "string",
                            "description": "Optional Solana wallet address override. If omitted, use the configured wallet.",
                        },
                    },
                    "additionalProperties": False,
                },
                read_only=True,
                risk_level="low",
            ),
        ]

        if capabilities.can_sign_message:
            tools.append(
                AgentToolSpec(
                    name="sign_wallet_message",
                    description=(
                        "Sign an arbitrary message with the connected wallet. "
                        "Only use after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Exact message to sign.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the signature is needed.",
                            },
                            "user_confirmed": {
                                "type": "boolean",
                                "description": "Must be true if the user explicitly approved the signature request.",
                            },
                        },
                        "required": ["message", "purpose", "user_confirmed"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="medium",
                )
            )

        if capabilities.chain == "solana":
            tools.append(
                AgentToolSpec(
                    name="transfer_sol",
                    description=(
                        "Preview or execute a native SOL transfer. "
                        "Use preview first, then execute only after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "recipient": {
                                "type": "string",
                                "description": "Destination Solana wallet address.",
                            },
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to transfer.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a transfer summary, prepare returns an execution plan without signed transaction bytes, execute attempts to send.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the transfer is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["recipient", "amount", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="stake_sol_native",
                    description=(
                        "Preview, prepare, or execute native SOL staking to a validator vote account "
                        "through the Solana Stake Program."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "vote_account": {
                                "type": "string",
                                "description": "Validator vote account address.",
                            },
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to stake, excluding rent reserve.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a staking summary, prepare returns an execution plan without signed transaction bytes, execute attempts to send.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the staking action is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["vote_account", "amount", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="transfer_spl_token",
                    description=(
                        "Preview or execute an SPL token transfer by mint address. "
                        "Use preview first, then execute only after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "recipient": {
                                "type": "string",
                                "description": "Destination Solana wallet address.",
                            },
                            "mint": {
                                "type": "string",
                                "description": "SPL token mint address.",
                            },
                            "amount": {
                                "type": "number",
                                "description": "Token amount in UI units.",
                            },
                            "decimals": {
                                "type": "integer",
                                "description": "Optional token decimals override. If omitted, fetch from chain.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a transfer summary, prepare returns an execution plan without signed transaction bytes, execute attempts to send.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the transfer is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["recipient", "mint", "amount", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="swap_solana_tokens",
                    description=(
                        "Preview or execute a Solana token swap through Jupiter routing. "
                        "Use preview first, then execute only after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "input_mint": {
                                "type": "string",
                                "description": "Input token mint address. Use native SOL mint for SOL swaps.",
                            },
                            "output_mint": {
                                "type": "string",
                                "description": "Output token mint address. Use native SOL mint for SOL swaps.",
                            },
                            "amount": {
                                "type": "number",
                                "description": "Input token amount in UI units.",
                            },
                            "slippage_bps": {
                                "type": "integer",
                                "description": "Optional slippage tolerance in basis points. Defaults to 50.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a quote, prepare returns an execution plan without signed transaction bytes, execute attempts to swap.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the swap is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["input_mint", "output_mint", "amount", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="swap_solana_privately",
                    description=(
                        "Preview or create a Solana private payout through Houdini's anonymous routing. "
                        "The initial implementation supports same-token private payouts only, such as SOL->SOL or USDC->USDC. "
                        "Use preview first, then execute after explicit approval. "
                        "The first execute creates the Houdini order and returns the deposit address; use continue_solana_private_swap to submit the funding transfer."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "input_token": {
                                "type": "string",
                                "description": "Source Solana token identifier. Symbol, name, mint address, or Houdini token id.",
                            },
                            "output_token": {
                                "type": "string",
                                "description": "Destination Solana token identifier. For the initial implementation, this must resolve to the same token as input_token.",
                            },
                            "destination_address": {
                                "type": "string",
                                "description": "Destination Solana wallet address that should receive the privately routed payout.",
                            },
                            "amount": {
                                "type": "number",
                                "description": "Input token amount in UI units.",
                            },
                            "use_xmr": {
                                "type": "boolean",
                                "description": "Optional. Force Houdini's XMR privacy hop when available.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "execute"],
                            },
                            "purpose": {"type": "string"},
                            "user_intent": {"type": "boolean"},
                            "approval_token": {"type": "string"},
                        },
                        "required": [
                            "input_token",
                            "output_token",
                            "destination_address",
                            "amount",
                            "mode",
                            "purpose",
                        ],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="continue_solana_private_swap",
                    description=(
                        "Continue a previously created Houdini Solana private payout and submit the funding transfer "
                        "to the saved deposit address. Use this only after swap_solana_privately execute has returned "
                        "a pending order with deposit address details."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "houdini_id": {
                                "type": "string",
                                "description": "Optional Houdini order id for the pending private payout. If omitted, the host may use the latest cached pending order.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Approval token issued from the original private swap preview.",
                            },
                        },
                        "required": ["approval_token"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="get_solana_private_swap_status",
                    description=(
                        "Check Houdini status for a Solana private payout created by swap_solana_privately. "
                        "Use houdini_id from the execute result. multi_id is still accepted for legacy multi-order flows."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "multi_id": {"type": "string"},
                            "houdini_id": {"type": "string"},
                        },
                        "anyOf": [{"required": ["multi_id"]}, {"required": ["houdini_id"]}],
                        "additionalProperties": False,
                    },
                    read_only=True,
                    risk_level="low",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="claim_bags_fees",
                    description=(
                        "Preview, prepare, or execute a Bags fee-share claim for the connected wallet on mainnet. "
                        "Use preview first, then execute only after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "token_mint": {
                                "type": "string",
                                "description": "Launched token mint address whose fees should be claimed.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns claimable positions, prepare returns an execution plan without signed transaction bytes, execute attempts to claim fees.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the fee claim is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["token_mint", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="swap_solana_lifi_cross_chain_tokens",
                    description=(
                        "Preview, prepare, or execute a Solana-origin cross-chain swap through LI.FI. "
                        "This currently supports Solana as the source chain and ethereum/base as the destination chain. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "input_token": {
                                "type": "string",
                                "description": "Source Solana token mint, native, sol, or 11111111111111111111111111111111 for native SOL.",
                            },
                            "destination_chain": {
                                "type": "string",
                                "enum": ["ethereum", "base", "1", "8453"],
                            },
                            "output_token": {
                                "type": "string",
                                "description": "Destination EVM token contract address, native, eth, or the zero address for native ETH.",
                            },
                            "destination_address": {
                                "type": "string",
                                "description": "Destination EVM wallet address on the target chain.",
                            },
                            "amount_in_raw": {
                                "type": "string",
                                "description": "Input amount in token base units as a base-10 integer string.",
                            },
                            "slippage": {
                                "type": "number",
                                "description": "Optional decimal fraction, for example 0.01 for 1%.",
                            },
                            "allow_bridges": {"type": "array", "items": {"type": "string"}},
                            "deny_bridges": {"type": "array", "items": {"type": "string"}},
                            "prefer_bridges": {"type": "array", "items": {"type": "string"}},
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                            },
                            "purpose": {"type": "string"},
                            "user_intent": {"type": "boolean"},
                            "approval_token": {"type": "string"},
                        },
                        "required": [
                            "input_token",
                            "destination_chain",
                            "output_token",
                            "destination_address",
                            "amount_in_raw",
                            "mode",
                            "purpose",
                        ],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="launch_bags_token",
                    description=(
                        "Preview, prepare, or execute a Bags token launch with fee-share config on mainnet. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Token name."},
                            "symbol": {"type": "string", "description": "Token ticker symbol."},
                            "description": {"type": "string", "description": "Token description."},
                            "image_url": {
                                "type": "string",
                                "description": "Optional hosted token image URL.",
                            },
                            "website": {"type": "string", "description": "Optional project website URL."},
                            "twitter": {"type": "string", "description": "Optional project Twitter/X handle or URL."},
                            "telegram": {"type": "string", "description": "Optional Telegram URL or handle."},
                            "discord": {"type": "string", "description": "Optional Discord URL."},
                            "base_mint": {
                                "type": "string",
                                "description": "Base mint used for Bags fee share configuration.",
                            },
                            "claimers": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Fee-share claimer wallet addresses.",
                            },
                            "basis_points": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Fee-share split in basis points. Must sum to 10000.",
                            },
                            "initial_buy_sol": {
                                "type": "number",
                                "description": "Initial buy amount in SOL. Use 0 for no initial buy.",
                            },
                            "bags_config_type": {
                                "type": "integer",
                                "description": "Optional Bags fee-share config type override.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a launch summary, prepare returns an execution plan without signed transaction bytes, execute attempts to sign and broadcast the launch transaction.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the token is being launched.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": [
                            "name",
                            "symbol",
                            "description",
                            "base_mint",
                            "claimers",
                            "basis_points",
                            "initial_buy_sol",
                            "mode",
                            "purpose",
                        ],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="jupiter_earn_deposit",
                    description=(
                        "Preview, prepare, or execute a Jupiter Earn deposit using a raw base-unit amount. "
                        "Use preview first, then execute only after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "asset": {
                                "type": "string",
                                "description": "Solana mint address for the Earn asset.",
                            },
                            "amount_raw": {
                                "type": "string",
                                "description": "Deposit amount in raw base units as an integer string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to submit the Earn deposit transaction.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the Earn deposit is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["asset", "amount_raw", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="jupiter_earn_withdraw",
                    description=(
                        "Preview, prepare, or execute a Jupiter Earn withdraw using a raw base-unit amount. "
                        "Use preview first, then execute only after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "asset": {
                                "type": "string",
                                "description": "Solana mint address for the Earn asset.",
                            },
                            "amount_raw": {
                                "type": "string",
                                "description": "Withdraw amount in raw base units as an integer string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to submit the Earn withdraw transaction.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the Earn withdraw is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["asset", "amount_raw", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="kamino_lend_deposit",
                    description=(
                        "Preview, prepare, or execute a Kamino lending deposit using a decimal token amount. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "market": {"type": "string", "description": "Kamino market address."},
                            "reserve": {"type": "string", "description": "Kamino reserve address."},
                            "amount_ui": {
                                "type": "string",
                                "description": "Decimal token amount to deposit, as a string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to submit the Kamino deposit transaction.",
                            },
                            "purpose": {"type": "string", "description": "Short explanation of why the deposit is being made."},
                            "user_intent": {"type": "boolean", "description": "Must be true for prepare mode."},
                            "approval_token": {"type": "string", "description": "Host-issued approval token required for execute mode."},
                        },
                        "required": ["market", "reserve", "amount_ui", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="kamino_lend_withdraw",
                    description=(
                        "Preview, prepare, or execute a Kamino lending withdraw using a decimal token amount. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "market": {"type": "string", "description": "Kamino market address."},
                            "reserve": {"type": "string", "description": "Kamino reserve address."},
                            "amount_ui": {
                                "type": "string",
                                "description": "Decimal token amount to withdraw, as a string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to submit the Kamino withdraw transaction.",
                            },
                            "purpose": {"type": "string", "description": "Short explanation of why the withdraw is being made."},
                            "user_intent": {"type": "boolean", "description": "Must be true for prepare mode."},
                            "approval_token": {"type": "string", "description": "Host-issued approval token required for execute mode."},
                        },
                        "required": ["market", "reserve", "amount_ui", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="kamino_lend_borrow",
                    description=(
                        "Preview, prepare, or execute a Kamino lending borrow using a decimal token amount. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "market": {"type": "string", "description": "Kamino market address."},
                            "reserve": {"type": "string", "description": "Kamino reserve address."},
                            "amount_ui": {
                                "type": "string",
                                "description": "Decimal token amount to borrow, as a string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to submit the Kamino borrow transaction.",
                            },
                            "purpose": {"type": "string", "description": "Short explanation of why the borrow is being made."},
                            "user_intent": {"type": "boolean", "description": "Must be true for prepare mode."},
                            "approval_token": {"type": "string", "description": "Host-issued approval token required for execute mode."},
                        },
                        "required": ["market", "reserve", "amount_ui", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="kamino_lend_repay",
                    description=(
                        "Preview, prepare, or execute a Kamino lending repay using a decimal token amount. "
                        "Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "market": {"type": "string", "description": "Kamino market address."},
                            "reserve": {"type": "string", "description": "Kamino reserve address."},
                            "amount_ui": {
                                "type": "string",
                                "description": "Decimal token amount to repay, as a string.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to submit the Kamino repay transaction.",
                            },
                            "purpose": {"type": "string", "description": "Short explanation of why the repay is being made."},
                            "user_intent": {"type": "boolean", "description": "Must be true for prepare mode."},
                            "approval_token": {"type": "string", "description": "Host-issued approval token required for execute mode."},
                        },
                        "required": ["market", "reserve", "amount_ui", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="close_empty_token_accounts",
                    description=(
                        "Preview or execute closing zero-balance SPL token accounts owned by the wallet. "
                        "Use preview first, then execute only after explicit user approval."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of empty token accounts to close in one transaction. Defaults to 8.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "execute"],
                                "description": "preview lists closeable accounts, execute attempts to close them.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the close operation is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Reserved for parity with other sensitive actions.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="medium",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="deactivate_solana_stake",
                    description=(
                        "Preview, prepare, or execute deactivation for a native Solana stake account."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "stake_account": {
                                "type": "string",
                                "description": "Stake account address to deactivate.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to send.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the deactivation is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["stake_account", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="withdraw_solana_stake",
                    description=(
                        "Preview, prepare, or execute withdrawal from a native Solana stake account."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "stake_account": {
                                "type": "string",
                                "description": "Stake account address to withdraw from.",
                            },
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to withdraw.",
                            },
                            "recipient": {
                                "type": "string",
                                "description": "Optional destination wallet address. Defaults to the connected wallet.",
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["preview", "prepare", "execute"],
                                "description": "preview returns a summary, prepare returns an execution plan without signed transaction bytes, execute attempts to send.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the withdraw is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "approval_token": {
                                "type": "string",
                                "description": "Host-issued approval token required for execute mode.",
                            },
                        },
                        "required": ["stake_account", "amount", "mode", "purpose"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="high",
                )
            )

            tools.append(
                AgentToolSpec(
                    name="request_devnet_airdrop",
                    description=(
                        "Request SOL from the Solana faucet on devnet or testnet. "
                        "Only available outside mainnet."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "number",
                                "description": "Amount of SOL to request from faucet.",
                            }
                        },
                        "required": ["amount"],
                        "additionalProperties": False,
                    },
                    read_only=False,
                    requires_explicit_user_intent=True,
                    risk_level="low",
                )
            )

        tools.extend(self._x402_tool_specs())
        return [tool for tool in tools if tool.name not in TEMPORARILY_DISABLED_TOOLS]

    def get_runtime_instructions(self) -> str:
        """Return the instruction block to inject into the agent runtime."""
        return WALLET_RUNTIME_INSTRUCTIONS

    async def invoke(self, tool_name: str, arguments: dict[str, Any] | None = None) -> AgentToolResult:
        """Dispatch an agent-facing tool call to the wallet backend."""
        args = arguments or {}
        try:
            active_backend = self._resolve_backend_for_args(args)
            if tool_name in TEMPORARILY_DISABLED_TOOLS:
                raise WalletBackendError(
                    f"{tool_name} is temporarily disabled. The implementation remains in the repo but this tool is currently turned off."
                )

            if tool_name == "x402_search_services":
                query = args.get("query")
                discovery_provider = args.get("discovery_provider", "auto")
                network = args.get("network")
                asset = args.get("asset")
                scheme = args.get("scheme")
                max_usd_price = args.get("max_usd_price")
                limit = args.get("limit", 10)
                for field_name, value in (
                    ("query", query),
                    ("discovery_provider", discovery_provider),
                    ("network", network),
                    ("asset", asset),
                    ("scheme", scheme),
                    ("max_usd_price", max_usd_price),
                ):
                    if value is not None and not isinstance(value, str):
                        raise WalletBackendError(f"{field_name} must be a string when provided.")
                if not isinstance(limit, int) or limit <= 0:
                    raise WalletBackendError("limit must be a positive integer.")
                data = await x402.search_services(
                    query=query,
                    discovery_provider=discovery_provider,
                    network=network,
                    asset=asset,
                    scheme=scheme,
                    max_usd_price=max_usd_price,
                    limit=limit,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "x402_get_service_details":
                reference = args.get("reference")
                discovery_provider = args.get("discovery_provider", "auto")
                if not isinstance(reference, str) or not reference.strip():
                    raise WalletBackendError("reference is required.")
                if discovery_provider is not None and not isinstance(discovery_provider, str):
                    raise WalletBackendError("discovery_provider must be a string when provided.")
                data = await x402.get_service_details(
                    reference=reference.strip(),
                    discovery_provider=discovery_provider,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "x402_preview_request":
                url = args.get("url")
                method = args.get("method", "GET")
                headers = args.get("headers")
                query = args.get("query")
                json_body = args.get("json_body")
                text_body = args.get("text_body")
                if not isinstance(url, str) or not url.strip():
                    raise WalletBackendError("url is required.")
                if method is not None and not isinstance(method, str):
                    raise WalletBackendError("method must be a string when provided.")
                if headers is not None and not isinstance(headers, dict):
                    raise WalletBackendError("headers must be an object when provided.")
                if query is not None and not isinstance(query, dict):
                    raise WalletBackendError("query must be an object when provided.")
                if text_body is not None and not isinstance(text_body, str):
                    raise WalletBackendError("text_body must be a string when provided.")
                data = await x402.preview_request(
                    backend=active_backend,
                    url=url.strip(),
                    method=method,
                    headers=headers,
                    query=query,
                    json_body=json_body,
                    text_body=text_body,
                )
                if data.get("payment_required"):
                    data = self._annotate_sensitive_payload(
                        data,
                        action_label="x402 paid request",
                        mode="preview",
                    )
                    approval_hint = dict(data.get("approval_hint") or {})
                    approval_hint["tool_name"] = "x402_pay_request"
                    data["approval_hint"] = approval_hint
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "x402_pay_request":
                url = args.get("url")
                method = args.get("method", "GET")
                headers = args.get("headers")
                query = args.get("query")
                json_body = args.get("json_body")
                text_body = args.get("text_body")
                mode = str(args.get("mode") or "").strip().lower()
                purpose = args.get("purpose")
                user_intent = args.get("user_intent")
                approval_token = args.get("approval_token")
                if not isinstance(url, str) or not url.strip():
                    raise WalletBackendError("url is required.")
                if method is not None and not isinstance(method, str):
                    raise WalletBackendError("method must be a string when provided.")
                if headers is not None and not isinstance(headers, dict):
                    raise WalletBackendError("headers must be an object when provided.")
                if query is not None and not isinstance(query, dict):
                    raise WalletBackendError("query must be an object when provided.")
                if text_body is not None and not isinstance(text_body, str):
                    raise WalletBackendError("text_body must be a string when provided.")
                if mode not in {"prepare", "execute"}:
                    raise WalletBackendError("mode must be 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")
                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    data = await x402.prepare_request(
                        backend=active_backend,
                        url=url.strip(),
                        method=method,
                        headers=headers,
                        query=query,
                        json_body=json_body,
                        text_body=text_body,
                    )
                    data["purpose"] = purpose.strip()
                    data = self._annotate_sensitive_payload(
                        data,
                        action_label="x402 paid request",
                        mode="prepare",
                    )
                    return AgentToolResult(tool=tool_name, ok=True, data=data)
                preview = await x402.prepare_request(
                    backend=active_backend,
                    url=url.strip(),
                    method=method,
                    headers=headers,
                    query=query,
                    json_body=json_body,
                    text_body=text_body,
                )
                preview["purpose"] = purpose.strip()
                preview = self._annotate_sensitive_payload(
                    preview,
                    action_label="x402 paid request",
                    mode="execute",
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=preview["confirmation_summary"],
                    action_label="x402 paid request",
                    backend=active_backend,
                )
                data = await x402.execute_request(
                    backend=active_backend,
                    url=url.strip(),
                    method=method,
                    headers=headers,
                    query=query,
                    json_body=json_body,
                    text_body=text_body,
                )
                data["purpose"] = purpose.strip()
                data = self._annotate_sensitive_payload(
                    data,
                    action_label="x402 paid request",
                    mode="execute",
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_wallet_capabilities":
                data = active_backend.get_capabilities().to_dict()
                data["network"] = str(getattr(active_backend, "network", "unknown"))
                data["address"] = await active_backend.get_address()
                data["is_mainnet"] = self._is_mainnet_for_backend(active_backend)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_wallet_address":
                address = await active_backend.get_address()
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data={
                        "address": address,
                        "configured": bool(address),
                        "network": str(getattr(active_backend, "network", "unknown")),
                        "is_mainnet": self._is_mainnet_for_backend(active_backend),
                    },
                )

            if tool_name == "get_wallet_balance":
                address = args.get("address")
                if address is not None and not isinstance(address, str):
                    raise WalletBackendError("address must be a string when provided.")
                data = await active_backend.get_balance(address=address)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_lifi_supported_chains":
                data = await active_backend.get_lifi_supported_chains()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_lifi_quote":
                from_chain = args.get("from_chain")
                to_chain = args.get("to_chain")
                from_token = args.get("from_token")
                to_token = args.get("to_token")
                amount_in_raw = args.get("amount_in_raw")
                from_address = args.get("from_address")
                to_address = args.get("to_address")
                slippage = self._normalize_lifi_slippage(args.get("slippage"))
                allow_bridges = self._normalize_optional_string_list(args.get("allow_bridges"), field_name="allow_bridges")
                deny_bridges = self._normalize_optional_string_list(args.get("deny_bridges"), field_name="deny_bridges")
                prefer_bridges = self._normalize_optional_string_list(args.get("prefer_bridges"), field_name="prefer_bridges")
                if not isinstance(from_chain, str) or not from_chain.strip():
                    raise WalletBackendError("from_chain is required.")
                if not isinstance(to_chain, str) or not to_chain.strip():
                    raise WalletBackendError("to_chain is required.")
                if not isinstance(from_token, str) or not from_token.strip():
                    raise WalletBackendError("from_token is required.")
                if not isinstance(to_token, str) or not to_token.strip():
                    raise WalletBackendError("to_token is required.")
                if not isinstance(amount_in_raw, str) or not amount_in_raw.strip().isdigit():
                    raise WalletBackendError("amount_in_raw must be a positive integer string.")
                if int(amount_in_raw.strip()) <= 0:
                    raise WalletBackendError("amount_in_raw must be greater than zero.")
                if from_address is not None and not isinstance(from_address, str):
                    raise WalletBackendError("from_address must be a string when provided.")
                if to_address is not None and not isinstance(to_address, str):
                    raise WalletBackendError("to_address must be a string when provided.")
                data = await active_backend.get_lifi_quote(
                    from_chain=from_chain.strip(),
                    to_chain=to_chain.strip(),
                    from_token=from_token.strip(),
                    to_token=to_token.strip(),
                    amount_in_raw=amount_in_raw.strip(),
                    from_address=from_address.strip() if isinstance(from_address, str) and from_address.strip() else None,
                    to_address=to_address.strip() if isinstance(to_address, str) and to_address.strip() else None,
                    slippage=slippage,
                    allow_bridges=allow_bridges,
                    deny_bridges=deny_bridges,
                    prefer_bridges=prefer_bridges,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_lifi_transfer_status":
                tx_hash = args.get("tx_hash")
                bridge = args.get("bridge")
                from_chain = args.get("from_chain")
                to_chain = args.get("to_chain")
                if not isinstance(tx_hash, str) or not tx_hash.strip():
                    raise WalletBackendError("tx_hash is required.")
                if bridge is not None and not isinstance(bridge, str):
                    raise WalletBackendError("bridge must be a string when provided.")
                if from_chain is not None and not isinstance(from_chain, str):
                    raise WalletBackendError("from_chain must be a string when provided.")
                if to_chain is not None and not isinstance(to_chain, str):
                    raise WalletBackendError("to_chain must be a string when provided.")
                data = await active_backend.get_lifi_transfer_status(
                    tx_hash=tx_hash.strip(),
                    bridge=bridge.strip() if isinstance(bridge, str) and bridge.strip() else None,
                    from_chain=from_chain.strip() if isinstance(from_chain, str) and from_chain.strip() else None,
                    to_chain=to_chain.strip() if isinstance(to_chain, str) and to_chain.strip() else None,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_btc_transfer_history":
                direction = args.get("direction", "all")
                limit = args.get("limit", 10)
                skip = args.get("skip", 0)
                if not isinstance(direction, str) or direction not in {"incoming", "outgoing", "all"}:
                    raise WalletBackendError("direction must be 'incoming', 'outgoing', or 'all'.")
                if not isinstance(limit, int) or limit < 0:
                    raise WalletBackendError("limit must be a non-negative integer.")
                if not isinstance(skip, int) or skip < 0:
                    raise WalletBackendError("skip must be a non-negative integer.")
                data = await self.backend.get_btc_transfer_history(
                    direction=direction,
                    limit=limit,
                    skip=skip,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_btc_fee_rates":
                data = await self.backend.get_btc_fee_rates()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_btc_max_spendable":
                fee_rate = args.get("fee_rate")
                if fee_rate is not None and (not isinstance(fee_rate, int) or fee_rate <= 0):
                    raise WalletBackendError("fee_rate must be a positive integer when provided.")
                data = await self.backend.get_btc_max_spendable(fee_rate=fee_rate)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_network":
                data = await active_backend.get_evm_network_info()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "set_evm_network":
                requested_network = args.get("network")
                network = self._normalize_evm_tool_network(requested_network)
                self.backend = self.backend.with_network(network)
                data = await self.backend.get_evm_network_info()
                data["selected_network"] = network
                data["session_active_network"] = str(getattr(self.backend, "network", "unknown"))
                data["network_switch_persistent_for_runtime_session"] = True
                data["usage"] = (
                    "Subsequent EVM tool calls in this runtime session use this network by "
                    "default. You can still override a single call with its network parameter."
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_token_balance":
                token_address = args.get("token_address")
                if not isinstance(token_address, str) or not token_address.strip():
                    raise WalletBackendError("token_address is required.")
                data = await active_backend.get_evm_token_balance(token_address.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_token_metadata":
                token_address = args.get("token_address")
                if not isinstance(token_address, str) or not token_address.strip():
                    raise WalletBackendError("token_address is required.")
                data = await active_backend.get_evm_token_metadata(token_address.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_fee_rates":
                data = await active_backend.get_evm_fee_rates()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_transaction_receipt":
                tx_hash = args.get("tx_hash")
                if not isinstance(tx_hash, str) or not tx_hash.strip():
                    raise WalletBackendError("tx_hash is required.")
                data = await active_backend.get_evm_transaction_receipt(tx_hash.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_aave_account":
                data = await active_backend.get_evm_aave_account()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_aave_reserves":
                data = await active_backend.get_evm_aave_reserves()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_aave_positions":
                data = await active_backend.get_evm_aave_positions()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "manage_evm_aave_position":
                operation = args.get("operation")
                token_address = args.get("token_address")
                amount_raw = args.get("amount_raw")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if operation not in {"supply", "withdraw", "borrow", "repay"}:
                    raise WalletBackendError("operation must be one of: supply, withdraw, borrow, repay.")
                if not isinstance(token_address, str) or not token_address.strip():
                    raise WalletBackendError("token_address is required.")
                if not isinstance(amount_raw, str) or not amount_raw.strip().isdigit():
                    raise WalletBackendError("amount_raw must be a positive integer string.")
                if int(amount_raw.strip()) <= 0:
                    raise WalletBackendError("amount_raw must be greater than zero.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "operation": str(operation),
                    "token_address": token_address.strip(),
                    "amount_raw": amount_raw.strip(),
                }

                if mode == "preview":
                    preview = await active_backend.preview_evm_aave_operation(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="EVM Aave V3 operation",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await active_backend.preview_evm_aave_operation(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="EVM Aave V3 operation",
                            ),
                            action_label="EVM Aave V3 operation",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(active_backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "EVM Aave V3 operation",
                    "network": str(getattr(active_backend, "network", "unknown")),
                    "aave_operation": str(operation),
                    "token_address": token_address.strip(),
                    "amount_raw": amount_raw.strip(),
                }
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="EVM Aave V3 operation",
                    backend=active_backend,
                )
                result = await active_backend.send_evm_aave_operation(
                    **preview_kwargs,
                    expected_quote_fingerprint=(
                        str(approval_summary_copy.get("quote_fingerprint")).strip()
                        if approval_summary_copy.get("quote_fingerprint") is not None
                        else None
                    ),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="EVM Aave V3 operation",
                        mode="execute",
                    ),
                )

            if tool_name == "get_evm_lido_overview":
                data = await active_backend.get_evm_lido_overview()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_lido_positions":
                data = await active_backend.get_evm_lido_positions()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "manage_evm_lido_position":
                operation = args.get("operation")
                amount_raw = args.get("amount_raw")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if operation not in {"stake_eth_for_wsteth", "wrap_steth", "unwrap_wsteth"}:
                    raise WalletBackendError(
                        "operation must be one of: stake_eth_for_wsteth, wrap_steth, unwrap_wsteth."
                    )
                if not isinstance(amount_raw, str) or not amount_raw.strip().isdigit():
                    raise WalletBackendError("amount_raw must be a positive integer string.")
                if int(amount_raw.strip()) <= 0:
                    raise WalletBackendError("amount_raw must be greater than zero.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "operation": str(operation),
                    "amount_raw": amount_raw.strip(),
                }

                if mode == "preview":
                    preview = await active_backend.preview_evm_lido_operation(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="EVM Lido operation",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await active_backend.preview_evm_lido_operation(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="EVM Lido operation",
                            ),
                            action_label="EVM Lido operation",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(active_backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "EVM Lido operation",
                    "network": str(getattr(active_backend, "network", "unknown")),
                    "lido_operation": str(operation),
                    "amount_raw": amount_raw.strip(),
                }
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="EVM Lido operation",
                    backend=active_backend,
                )
                result = await active_backend.send_evm_lido_operation(
                    **preview_kwargs,
                    expected_quote_fingerprint=(
                        str(approval_summary_copy.get("quote_fingerprint")).strip()
                        if approval_summary_copy.get("quote_fingerprint") is not None
                        else None
                    ),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="EVM Lido operation",
                        mode="execute",
                    ),
                )

            if tool_name == "get_evm_lido_withdrawal_requests":
                data = await active_backend.get_evm_lido_withdrawal_requests()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "manage_evm_lido_withdrawal":
                operation = args.get("operation")
                amount_raw = args.get("amount_raw")
                request_id = args.get("request_id")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if operation not in {
                    "request_withdrawal_steth",
                    "request_withdrawal_wsteth",
                    "claim_withdrawal",
                }:
                    raise WalletBackendError(
                        "operation must be one of: request_withdrawal_steth, request_withdrawal_wsteth, claim_withdrawal."
                    )
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")
                if operation == "claim_withdrawal":
                    if not isinstance(request_id, str) or not request_id.strip().isdigit():
                        raise WalletBackendError("request_id must be a positive integer string.")
                    if int(request_id.strip()) <= 0:
                        raise WalletBackendError("request_id must be greater than zero.")
                else:
                    if not isinstance(amount_raw, str) or not amount_raw.strip().isdigit():
                        raise WalletBackendError("amount_raw must be a positive integer string.")
                    if int(amount_raw.strip()) <= 0:
                        raise WalletBackendError("amount_raw must be greater than zero.")

                preview_kwargs = {
                    "operation": str(operation),
                    **(
                        {"amount_raw": amount_raw.strip()}
                        if isinstance(amount_raw, str) and amount_raw.strip()
                        else {}
                    ),
                    **(
                        {"request_id": request_id.strip()}
                        if isinstance(request_id, str) and request_id.strip()
                        else {}
                    ),
                }

                if mode == "preview":
                    preview = await active_backend.preview_evm_lido_withdrawal(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="EVM Lido withdrawal",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await active_backend.preview_evm_lido_withdrawal(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="EVM Lido withdrawal",
                            ),
                            action_label="EVM Lido withdrawal",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(active_backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "EVM Lido withdrawal",
                    "network": str(getattr(active_backend, "network", "unknown")),
                    "lido_withdrawal_operation": str(operation),
                }
                if operation == "claim_withdrawal":
                    expected_summary["request_id"] = request_id.strip()
                else:
                    expected_summary["amount_raw"] = amount_raw.strip()
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="EVM Lido withdrawal",
                    backend=active_backend,
                )
                result = await active_backend.send_evm_lido_withdrawal(
                    **preview_kwargs,
                    expected_quote_fingerprint=(
                        str(approval_summary_copy.get("quote_fingerprint")).strip()
                        if approval_summary_copy.get("quote_fingerprint") is not None
                        else None
                    ),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="EVM Lido withdrawal",
                        mode="execute",
                    ),
                )

            if tool_name == "get_evm_swap_quote":
                token_in = args.get("token_in")
                token_out = args.get("token_out")
                amount_in_raw = args.get("amount_in_raw")
                if not isinstance(token_in, str) or not token_in.strip():
                    raise WalletBackendError("token_in is required.")
                if not isinstance(token_out, str) or not token_out.strip():
                    raise WalletBackendError("token_out is required.")
                if not isinstance(amount_in_raw, str) or not amount_in_raw.strip().isdigit():
                    raise WalletBackendError("amount_in_raw must be a positive integer string.")
                if int(amount_in_raw.strip()) <= 0:
                    raise WalletBackendError("amount_in_raw must be greater than zero.")
                data = await active_backend.get_evm_swap_quote(
                    token_in=token_in.strip(),
                    token_out=token_out.strip(),
                    amount_in_raw=amount_in_raw.strip(),
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "swap_evm_tokens":
                token_in = args.get("token_in")
                token_out = args.get("token_out")
                amount_in_raw = args.get("amount_in_raw")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(token_in, str) or not token_in.strip():
                    raise WalletBackendError("token_in is required.")
                if not isinstance(token_out, str) or not token_out.strip():
                    raise WalletBackendError("token_out is required.")
                if not isinstance(amount_in_raw, str) or not amount_in_raw.strip().isdigit():
                    raise WalletBackendError("amount_in_raw must be a positive integer string.")
                if int(amount_in_raw.strip()) <= 0:
                    raise WalletBackendError("amount_in_raw must be greater than zero.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "token_in": token_in.strip(),
                    "token_out": token_out.strip(),
                    "amount_in_raw": amount_in_raw.strip(),
                }

                if mode == "preview":
                    preview = await active_backend.preview_evm_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="EVM swap",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await active_backend.preview_evm_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="EVM swap",
                            ),
                            action_label="EVM swap",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(active_backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "EVM swap",
                    "network": str(getattr(active_backend, "network", "unknown")),
                    "token_in": token_in.strip(),
                    "token_out": token_out.strip(),
                    "input_amount_raw": amount_in_raw.strip(),
                }
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="EVM swap",
                    backend=active_backend,
                )
                bound_quote_fingerprint = approval_summary_copy.get("quote_fingerprint")
                bound_minimum_output_amount_raw = approval_summary_copy.get("minimum_output_amount_raw")
                if isinstance(bound_quote_fingerprint, str) and bound_quote_fingerprint.strip():
                    result = await active_backend.send_evm_swap(
                        **preview_kwargs,
                        expected_quote_fingerprint=bound_quote_fingerprint.strip(),
                        minimum_output_amount_raw=(
                            str(bound_minimum_output_amount_raw).strip()
                            if bound_minimum_output_amount_raw is not None
                            else None
                        ),
                    )
                else:
                    result = await active_backend.send_evm_swap(
                        **preview_kwargs,
                        minimum_output_amount_raw=(
                            str(bound_minimum_output_amount_raw).strip()
                            if bound_minimum_output_amount_raw is not None
                            else None
                        ),
                    )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="EVM swap",
                        mode="execute",
                    ),
                )

            if tool_name == "swap_evm_lifi_cross_chain_tokens":
                token_in = args.get("token_in")
                destination_chain = args.get("destination_chain")
                output_token = args.get("output_token")
                destination_address = args.get("destination_address")
                amount_in_raw = args.get("amount_in_raw")
                slippage = self._normalize_lifi_slippage(args.get("slippage"))
                allow_bridges = self._normalize_optional_string_list(args.get("allow_bridges"), field_name="allow_bridges")
                deny_bridges = self._normalize_optional_string_list(args.get("deny_bridges"), field_name="deny_bridges")
                prefer_bridges = self._normalize_optional_string_list(args.get("prefer_bridges"), field_name="prefer_bridges")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(token_in, str) or not token_in.strip():
                    raise WalletBackendError("token_in is required.")
                if not isinstance(destination_chain, str) or not destination_chain.strip():
                    raise WalletBackendError("destination_chain is required.")
                if not isinstance(output_token, str) or not output_token.strip():
                    raise WalletBackendError("output_token is required.")
                if not isinstance(destination_address, str) or not destination_address.strip():
                    raise WalletBackendError("destination_address is required.")
                if not isinstance(amount_in_raw, str) or not amount_in_raw.strip().isdigit():
                    raise WalletBackendError("amount_in_raw must be a positive integer string.")
                if int(amount_in_raw.strip()) <= 0:
                    raise WalletBackendError("amount_in_raw must be greater than zero.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "token_in": token_in.strip(),
                    "destination_chain": destination_chain.strip(),
                    "output_token": output_token.strip(),
                    "destination_address": destination_address.strip(),
                    "amount_in_raw": amount_in_raw.strip(),
                    "slippage": slippage,
                    "allow_bridges": allow_bridges,
                    "deny_bridges": deny_bridges,
                    "prefer_bridges": prefer_bridges,
                }

                if mode == "preview":
                    preview = await active_backend.preview_evm_lifi_cross_chain_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="EVM LI.FI cross-chain swap",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await active_backend.preview_evm_lifi_cross_chain_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="EVM LI.FI cross-chain swap",
                            ),
                            action_label="EVM LI.FI cross-chain swap",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(active_backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                source_chain_id = self._canonicalize_lifi_chain_identifier(
                    getattr(active_backend, "network", "unknown")
                )
                destination_chain_id = self._canonicalize_lifi_chain_identifier(destination_chain)
                expected_summary = {
                    "operation": "EVM LI.FI cross-chain swap",
                    "network": str(getattr(active_backend, "network", "unknown")),
                    "source_chain": source_chain_id,
                    "destination_chain": destination_chain_id,
                    "token_in": self._canonicalize_lifi_token_identifier(
                        token_in,
                        chain_id=source_chain_id,
                    ),
                    "output_token": self._canonicalize_lifi_token_identifier(
                        output_token,
                        chain_id=destination_chain_id,
                    ),
                    "destination_address": destination_address.strip(),
                    "input_amount_raw": amount_in_raw.strip(),
                }
                for key, expected_value in expected_summary.items():
                    actual_value = approval_summary.get(key)
                    if key in {"source_chain", "destination_chain"}:
                        actual_value = self._canonicalize_lifi_chain_identifier(actual_value)
                    if key == "token_in":
                        actual_value = self._canonicalize_lifi_token_identifier(
                            actual_value,
                            chain_id=source_chain_id,
                        )
                    if key == "output_token":
                        actual_value = self._canonicalize_lifi_token_identifier(
                            actual_value,
                            chain_id=destination_chain_id,
                        )
                    if actual_value != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="EVM LI.FI cross-chain swap",
                    backend=active_backend,
                )
                result = await active_backend.send_evm_lifi_cross_chain_swap(
                    token_in=str(approval_summary_copy.get("token_in") or token_in).strip(),
                    destination_chain=str(
                        approval_summary_copy.get("destination_chain") or destination_chain
                    ).strip(),
                    output_token=str(approval_summary_copy.get("output_token") or output_token).strip(),
                    destination_address=str(
                        approval_summary_copy.get("destination_address") or destination_address
                    ).strip(),
                    amount_in_raw=str(approval_summary_copy.get("input_amount_raw") or amount_in_raw).strip(),
                    slippage=approval_summary_copy.get("slippage", slippage),
                    allow_bridges=allow_bridges,
                    deny_bridges=deny_bridges,
                    prefer_bridges=prefer_bridges,
                    minimum_output_amount_raw=(
                        str(approval_summary_copy.get("minimum_output_amount_raw")).strip()
                        if approval_summary_copy.get("minimum_output_amount_raw") is not None
                        else None
                    ),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="EVM LI.FI cross-chain swap",
                        mode="execute",
                    ),
                )

            if tool_name == "get_wallet_portfolio":
                address = args.get("address")
                if address is not None and not isinstance(address, str):
                    raise WalletBackendError("address must be a string when provided.")
                data = await self.backend.get_portfolio(address=address)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_solana_token_prices":
                mints = args.get("mints")
                if not isinstance(mints, list) or not mints:
                    raise WalletBackendError("mints must be a non-empty array of strings.")
                if not all(isinstance(item, str) for item in mints):
                    raise WalletBackendError("Each mint must be a string.")
                data = await self.backend.get_token_prices(mints=mints)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_bags_claimable_positions":
                wallet = args.get("wallet")
                if wallet is not None and not isinstance(wallet, str):
                    raise WalletBackendError("wallet must be a string when provided.")
                data = await self.backend.get_bags_claimable_positions(wallet=wallet)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_bags_fee_analytics":
                token_mint = args.get("token_mint")
                include_claim_events = args.get("include_claim_events", False)
                mode = args.get("mode", "offset")
                limit = args.get("limit")
                offset = args.get("offset")
                from_ts = args.get("from_ts")
                to_ts = args.get("to_ts")
                if not isinstance(token_mint, str) or not token_mint.strip():
                    raise WalletBackendError("token_mint is required.")
                if not isinstance(include_claim_events, bool):
                    raise WalletBackendError("include_claim_events must be a boolean.")
                if not isinstance(mode, str) or mode not in {"offset", "time"}:
                    raise WalletBackendError("mode must be 'offset' or 'time'.")
                for field_name, value in (
                    ("limit", limit),
                    ("offset", offset),
                    ("from_ts", from_ts),
                    ("to_ts", to_ts),
                ):
                    if value is not None and not isinstance(value, int):
                        raise WalletBackendError(f"{field_name} must be an integer when provided.")
                data = await self.backend.get_bags_fee_analytics(
                    token_mint=token_mint.strip(),
                    include_claim_events=include_claim_events,
                    mode=mode,
                    limit=limit,
                    offset=offset,
                    from_ts=from_ts,
                    to_ts=to_ts,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_solana_staking_validators":
                limit = args.get("limit", 20)
                include_delinquent = args.get("include_delinquent", False)
                if not isinstance(limit, int) or limit <= 0:
                    raise WalletBackendError("limit must be a positive integer.")
                if not isinstance(include_delinquent, bool):
                    raise WalletBackendError("include_delinquent must be a boolean.")
                data = await self.backend.get_staking_validators(
                    limit=limit,
                    include_delinquent=include_delinquent,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_solana_stake_account":
                stake_account = args.get("stake_account")
                if not isinstance(stake_account, str) or not stake_account.strip():
                    raise WalletBackendError("stake_account is required.")
                data = await self.backend.get_stake_account(stake_account.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_jupiter_portfolio_platforms":
                data = await self.backend.get_jupiter_portfolio_platforms()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_jupiter_portfolio":
                address = args.get("address")
                platforms = args.get("platforms")
                if address is not None and not isinstance(address, str):
                    raise WalletBackendError("address must be a string when provided.")
                if platforms is not None:
                    if not isinstance(platforms, list) or not all(
                        isinstance(item, str) for item in platforms
                    ):
                        raise WalletBackendError("platforms must be an array of strings.")
                data = await self.backend.get_jupiter_portfolio(
                    address=address,
                    platforms=platforms,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_jupiter_staked_jup":
                address = args.get("address")
                if address is not None and not isinstance(address, str):
                    raise WalletBackendError("address must be a string when provided.")
                data = await self.backend.get_jupiter_staked_jup(address=address)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_jupiter_earn_tokens":
                data = await self.backend.get_jupiter_earn_tokens()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_jupiter_earn_positions":
                users = args.get("users")
                if users is not None:
                    if not isinstance(users, list) or not all(isinstance(item, str) for item in users):
                        raise WalletBackendError("users must be an array of strings.")
                data = await self.backend.get_jupiter_earn_positions(users=users)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_jupiter_earn_earnings":
                user = args.get("user")
                positions = args.get("positions")
                if user is not None and not isinstance(user, str):
                    raise WalletBackendError("user must be a string when provided.")
                if not isinstance(positions, list) or not positions:
                    raise WalletBackendError("positions must be a non-empty array of strings.")
                if not all(isinstance(item, str) for item in positions):
                    raise WalletBackendError("Each position must be a string.")
                data = await self.backend.get_jupiter_earn_earnings(
                    user=user,
                    positions=positions,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_flash_trade_markets":
                pool_name = args.get("pool_name")
                if pool_name is not None and not isinstance(pool_name, str):
                    raise WalletBackendError("pool_name must be a string when provided.")
                data = await active_backend.get_flash_trade_markets(pool_name=pool_name)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_flash_trade_positions":
                owner = args.get("owner")
                pool_name = args.get("pool_name")
                if owner is not None and not isinstance(owner, str):
                    raise WalletBackendError("owner must be a string when provided.")
                if pool_name is not None and not isinstance(pool_name, str):
                    raise WalletBackendError("pool_name must be a string when provided.")
                data = await active_backend.get_flash_trade_positions(
                    owner=owner,
                    pool_name=pool_name,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "flash_trade_open_position":
                pool_name = args.get("pool_name")
                market_symbol = args.get("market_symbol")
                collateral_symbol = args.get("collateral_symbol")
                collateral_amount_raw = args.get("collateral_amount_raw")
                leverage = args.get("leverage")
                side = args.get("side")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(pool_name, str) or not pool_name.strip():
                    raise WalletBackendError("pool_name is required.")
                if not isinstance(market_symbol, str) or not market_symbol.strip():
                    raise WalletBackendError("market_symbol is required.")
                if not isinstance(collateral_symbol, str) or not collateral_symbol.strip():
                    raise WalletBackendError("collateral_symbol is required.")
                if not isinstance(collateral_amount_raw, str) or not collateral_amount_raw.strip():
                    raise WalletBackendError("collateral_amount_raw is required.")
                if not isinstance(leverage, str) or not leverage.strip():
                    raise WalletBackendError("leverage is required.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await active_backend.preview_flash_trade_open_position(
                        pool_name=pool_name.strip(),
                        market_symbol=market_symbol.strip(),
                        collateral_symbol=collateral_symbol.strip(),
                        collateral_amount_raw=collateral_amount_raw.strip(),
                        leverage=leverage.strip(),
                        side=side,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Flash Trade open position",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    prepared = await active_backend.prepare_flash_trade_open_position(
                        pool_name=pool_name.strip(),
                        market_symbol=market_symbol.strip(),
                        collateral_symbol=collateral_symbol.strip(),
                        collateral_amount_raw=collateral_amount_raw.strip(),
                        leverage=leverage.strip(),
                        side=side,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=prepared,
                                action_label="Flash Trade open position",
                            ),
                            action_label="Flash Trade open position",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(active_backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "Flash Trade open position",
                    "pool_name": pool_name.strip(),
                    "market_symbol": market_symbol.strip(),
                    "collateral_symbol": collateral_symbol.strip(),
                    "collateral_amount_raw": collateral_amount_raw.strip(),
                    "leverage": leverage.strip(),
                    "side": side,
                }
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                approved_preview = args.get("_approved_preview")
                execute_preview = None
                if isinstance(approval_summary_copy.get("_preview_digest"), str):
                    if not isinstance(approved_preview, dict):
                        raise WalletBackendError(
                            "Approved Flash Trade preview payload is required for execute mode. Generate a new preview and approval before execute."
                        )
                    if preview_payload_digest(approved_preview) != approval_summary_copy["_preview_digest"]:
                        raise WalletBackendError(
                            "approved preview payload does not match the approval token. Generate a new preview and approval before execute."
                        )
                    execute_preview = dict(approved_preview)
                else:
                    execute_preview = await active_backend.preview_flash_trade_open_position(
                        pool_name=pool_name.strip(),
                        market_symbol=market_symbol.strip(),
                        collateral_symbol=collateral_symbol.strip(),
                        collateral_amount_raw=collateral_amount_raw.strip(),
                        leverage=leverage.strip(),
                        side=side,
                    )

                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="Flash Trade open position",
                    backend=active_backend,
                )
                result = await active_backend.execute_flash_trade_open_position(
                    pool_name=pool_name.strip(),
                    market_symbol=market_symbol.strip(),
                    collateral_symbol=collateral_symbol.strip(),
                    collateral_amount_raw=collateral_amount_raw.strip(),
                    leverage=leverage.strip(),
                    side=side,
                    approved_preview=execute_preview,
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Flash Trade open position",
                        mode="execute",
                    ),
                )

            if tool_name == "flash_trade_close_position":
                pool_name = args.get("pool_name")
                market_symbol = args.get("market_symbol")
                side = args.get("side")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(pool_name, str) or not pool_name.strip():
                    raise WalletBackendError("pool_name is required.")
                if not isinstance(market_symbol, str) or not market_symbol.strip():
                    raise WalletBackendError("market_symbol is required.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await active_backend.preview_flash_trade_close_position(
                        pool_name=pool_name.strip(),
                        market_symbol=market_symbol.strip(),
                        side=side,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Flash Trade close position",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    prepared = await active_backend.prepare_flash_trade_close_position(
                        pool_name=pool_name.strip(),
                        market_symbol=market_symbol.strip(),
                        side=side,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=prepared,
                                action_label="Flash Trade close position",
                            ),
                            action_label="Flash Trade close position",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(active_backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(active_backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "Flash Trade close position",
                    "pool_name": pool_name.strip(),
                    "market_symbol": market_symbol.strip(),
                    "side": side,
                }
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                approved_preview = args.get("_approved_preview")
                execute_preview = None
                if isinstance(approval_summary_copy.get("_preview_digest"), str):
                    if not isinstance(approved_preview, dict):
                        raise WalletBackendError(
                            "Approved Flash Trade preview payload is required for execute mode. Generate a new preview and approval before execute."
                        )
                    if preview_payload_digest(approved_preview) != approval_summary_copy["_preview_digest"]:
                        raise WalletBackendError(
                            "approved preview payload does not match the approval token. Generate a new preview and approval before execute."
                        )
                    execute_preview = dict(approved_preview)
                else:
                    execute_preview = await active_backend.preview_flash_trade_close_position(
                        pool_name=pool_name.strip(),
                        market_symbol=market_symbol.strip(),
                        side=side,
                    )

                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="Flash Trade close position",
                    backend=active_backend,
                )
                result = await active_backend.execute_flash_trade_close_position(
                    pool_name=pool_name.strip(),
                    market_symbol=market_symbol.strip(),
                    side=side,
                    approved_preview=execute_preview,
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Flash Trade close position",
                        mode="execute",
                    ),
                )

            if tool_name == "get_kamino_lend_markets":
                data = await self.backend.get_kamino_lend_markets()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_kamino_lend_market_reserves":
                market = args.get("market")
                if not isinstance(market, str) or not market.strip():
                    raise WalletBackendError("market is required.")
                data = await self.backend.get_kamino_lend_market_reserves(market=market.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_kamino_lend_user_obligations":
                market = args.get("market")
                user = args.get("user")
                if not isinstance(market, str) or not market.strip():
                    raise WalletBackendError("market is required.")
                if user is not None and not isinstance(user, str):
                    raise WalletBackendError("user must be a string when provided.")
                data = await self.backend.get_kamino_lend_user_obligations(
                    market=market.strip(),
                    user=user,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_kamino_lend_user_rewards":
                user = args.get("user")
                if user is not None and not isinstance(user, str):
                    raise WalletBackendError("user must be a string when provided.")
                data = await self.backend.get_kamino_lend_user_rewards(user=user)
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "sign_wallet_message":
                user_confirmed = args.get("user_confirmed")
                if user_confirmed is not True:
                    raise WalletBackendError(
                        "Message signing requires explicit user confirmation."
                    )
                message = args.get("message")
                purpose = args.get("purpose")
                if not isinstance(message, str) or not message.strip():
                    raise WalletBackendError("message is required.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")
                signature = await self.backend.sign_message(message.strip())
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data={
                        "signature": signature,
                        "purpose": purpose.strip(),
                        "message": message.strip(),
                        "sign_only": self.backend.get_capabilities().sign_only,
                    },
                )

            if tool_name == "transfer_sol":
                recipient = args.get("recipient")
                amount = args.get("amount")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(recipient, str) or not recipient.strip():
                    raise WalletBackendError("recipient is required.")
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise WalletBackendError("amount must be a positive number.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_native_transfer(
                        recipient=recipient.strip(),
                        amount_native=float(amount),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="SOL transfer",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_native_transfer(
                        recipient=recipient.strip(),
                        amount_native=float(amount),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="SOL transfer",
                            ),
                            action_label="SOL transfer",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_native_transfer(
                    recipient=recipient.strip(),
                    amount_native=float(amount),
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="SOL transfer",
                        payload=execute_preview,
                    ),
                    action_label="SOL transfer",
                )

                result = await self.backend.send_native_transfer(
                    recipient=recipient.strip(),
                    amount_native=float(amount),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="SOL transfer",
                        mode="execute",
                    ),
                )

            if tool_name == "transfer_btc":
                recipient = args.get("recipient")
                amount_sats = args.get("amount_sats")
                fee_rate = args.get("fee_rate")
                confirmation_target = args.get("confirmation_target")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(recipient, str) or not recipient.strip():
                    raise WalletBackendError("recipient is required.")
                if not isinstance(amount_sats, int) or amount_sats <= 0:
                    raise WalletBackendError("amount_sats must be a positive integer.")
                if fee_rate is not None and (not isinstance(fee_rate, int) or fee_rate <= 0):
                    raise WalletBackendError("fee_rate must be a positive integer when provided.")
                if confirmation_target is not None and (
                    not isinstance(confirmation_target, int) or confirmation_target <= 0
                ):
                    raise WalletBackendError(
                        "confirmation_target must be a positive integer when provided."
                    )
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "recipient": recipient.strip(),
                    "amount_sats": amount_sats,
                    "fee_rate": fee_rate,
                    "confirmation_target": confirmation_target,
                }

                if mode == "preview":
                    preview = await self.backend.preview_btc_transfer(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="BTC transfer",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_btc_transfer(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="BTC transfer",
                            ),
                            action_label="BTC transfer",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_btc_transfer(**preview_kwargs)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="BTC transfer",
                        payload=execute_preview,
                    ),
                    action_label="BTC transfer",
                )
                result = await self.backend.send_btc_transfer(**preview_kwargs)
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="BTC transfer",
                        mode="execute",
                    ),
                )

            if tool_name == "transfer_evm_native":
                recipient = args.get("recipient")
                amount_wei = args.get("amount_wei")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(recipient, str) or not recipient.strip():
                    raise WalletBackendError("recipient is required.")
                if not isinstance(amount_wei, str) or not amount_wei.strip().isdigit():
                    raise WalletBackendError("amount_wei must be a positive integer string.")
                if int(amount_wei.strip()) <= 0:
                    raise WalletBackendError("amount_wei must be greater than zero.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "recipient": recipient.strip(),
                    "amount_wei": amount_wei.strip(),
                }

                if mode == "preview":
                    preview = await active_backend.preview_evm_native_transfer(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="EVM native transfer",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await active_backend.preview_evm_native_transfer(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="EVM native transfer",
                            ),
                            action_label="EVM native transfer",
                            mode="prepare",
                        ),
                    )

                execute_preview = await active_backend.preview_evm_native_transfer(**preview_kwargs)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="EVM native transfer",
                        payload=execute_preview,
                    ),
                    action_label="EVM native transfer",
                    backend=active_backend,
                )
                result = await active_backend.send_evm_native_transfer(**preview_kwargs)
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="EVM native transfer",
                        mode="execute",
                    ),
                )

            if tool_name == "transfer_evm_token":
                token_address = args.get("token_address")
                recipient = args.get("recipient")
                amount_raw = args.get("amount_raw")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(token_address, str) or not token_address.strip():
                    raise WalletBackendError("token_address is required.")
                if not isinstance(recipient, str) or not recipient.strip():
                    raise WalletBackendError("recipient is required.")
                if not isinstance(amount_raw, str) or not amount_raw.strip().isdigit():
                    raise WalletBackendError("amount_raw must be a positive integer string.")
                if int(amount_raw.strip()) <= 0:
                    raise WalletBackendError("amount_raw must be greater than zero.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "token_address": token_address.strip(),
                    "recipient": recipient.strip(),
                    "amount_raw": amount_raw.strip(),
                }

                if mode == "preview":
                    preview = await active_backend.preview_evm_token_transfer(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="EVM token transfer",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await active_backend.preview_evm_token_transfer(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="EVM token transfer",
                            ),
                            action_label="EVM token transfer",
                            mode="prepare",
                        ),
                    )

                execute_preview = await active_backend.preview_evm_token_transfer(**preview_kwargs)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="EVM token transfer",
                        payload=execute_preview,
                    ),
                    action_label="EVM token transfer",
                    backend=active_backend,
                )
                result = await active_backend.send_evm_token_transfer(**preview_kwargs)
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="EVM token transfer",
                        mode="execute",
                    ),
                )

            if tool_name in {
                "kamino_lend_deposit",
                "kamino_lend_withdraw",
                "kamino_lend_borrow",
                "kamino_lend_repay",
            }:
                market = args.get("market")
                reserve = args.get("reserve")
                amount_ui = args.get("amount_ui")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(market, str) or not market.strip():
                    raise WalletBackendError("market is required.")
                if not isinstance(reserve, str) or not reserve.strip():
                    raise WalletBackendError("reserve is required.")
                if not isinstance(amount_ui, str) or not amount_ui.strip():
                    raise WalletBackendError("amount_ui is required.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                action_label_map = {
                    "kamino_lend_deposit": "Kamino deposit",
                    "kamino_lend_withdraw": "Kamino withdraw",
                    "kamino_lend_borrow": "Kamino borrow",
                    "kamino_lend_repay": "Kamino repay",
                }
                preview_method_map = {
                    "kamino_lend_deposit": self.backend.preview_kamino_lend_deposit,
                    "kamino_lend_withdraw": self.backend.preview_kamino_lend_withdraw,
                    "kamino_lend_borrow": self.backend.preview_kamino_lend_borrow,
                    "kamino_lend_repay": self.backend.preview_kamino_lend_repay,
                }
                execute_method_map = {
                    "kamino_lend_deposit": self.backend.execute_kamino_lend_deposit,
                    "kamino_lend_withdraw": self.backend.execute_kamino_lend_withdraw,
                    "kamino_lend_borrow": self.backend.execute_kamino_lend_borrow,
                    "kamino_lend_repay": self.backend.execute_kamino_lend_repay,
                }
                action_label = action_label_map[tool_name]
                preview_method = preview_method_map[tool_name]
                execute_method = execute_method_map[tool_name]

                if mode == "preview":
                    preview = await preview_method(
                        market=market.strip(),
                        reserve=reserve.strip(),
                        amount_ui=amount_ui.strip(),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label=action_label,
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await preview_method(
                        market=market.strip(),
                        reserve=reserve.strip(),
                        amount_ui=amount_ui.strip(),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label=action_label,
                            ),
                            action_label=action_label,
                            mode="prepare",
                        ),
                    )

                execute_preview = await preview_method(
                    market=market.strip(),
                    reserve=reserve.strip(),
                    amount_ui=amount_ui.strip(),
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label=action_label,
                        payload=execute_preview,
                    ),
                    action_label=action_label,
                )
                result = await execute_method(
                    market=market.strip(),
                    reserve=reserve.strip(),
                    amount_ui=amount_ui.strip(),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label=action_label,
                        mode="execute",
                    ),
                )

            if tool_name == "stake_sol_native":
                vote_account = args.get("vote_account")
                amount = args.get("amount")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(vote_account, str) or not vote_account.strip():
                    raise WalletBackendError("vote_account is required.")
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise WalletBackendError("amount must be a positive number.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_native_stake(
                        vote_account=vote_account.strip(),
                        amount_native=float(amount),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Native staking",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_native_stake(
                        vote_account=vote_account.strip(),
                        amount_native=float(amount),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Native staking",
                            ),
                            action_label="Native staking",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_native_stake(
                    vote_account=vote_account.strip(),
                    amount_native=float(amount),
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Native staking",
                        payload=execute_preview,
                    ),
                    action_label="Native staking",
                )
                result = await self.backend.execute_native_stake(
                    vote_account=vote_account.strip(),
                    amount_native=float(amount),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Native staking",
                        mode="execute",
                    ),
                )

            if tool_name == "request_devnet_airdrop":
                amount = args.get("amount")
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise WalletBackendError("amount must be a positive number.")
                result = await self.backend.request_testnet_airdrop(float(amount))
                return AgentToolResult(tool=tool_name, ok=True, data=result)

            if tool_name == "transfer_spl_token":
                recipient = args.get("recipient")
                mint = args.get("mint")
                amount = args.get("amount")
                decimals = args.get("decimals")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(recipient, str) or not recipient.strip():
                    raise WalletBackendError("recipient is required.")
                if not isinstance(mint, str) or not mint.strip():
                    raise WalletBackendError("mint is required.")
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise WalletBackendError("amount must be a positive number.")
                if decimals is not None and not isinstance(decimals, int):
                    raise WalletBackendError("decimals must be an integer when provided.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_spl_transfer(
                        recipient=recipient.strip(),
                        mint=mint.strip(),
                        amount_ui=float(amount),
                        decimals=decimals,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="SPL token transfer",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_spl_transfer(
                        recipient=recipient.strip(),
                        mint=mint.strip(),
                        amount_ui=float(amount),
                        decimals=decimals,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="SPL token transfer",
                            ),
                            action_label="SPL token transfer",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_spl_transfer(
                    recipient=recipient.strip(),
                    mint=mint.strip(),
                    amount_ui=float(amount),
                    decimals=decimals,
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="SPL token transfer",
                        payload=execute_preview,
                    ),
                    action_label="SPL token transfer",
                )

                result = await self.backend.send_spl_transfer(
                    recipient=recipient.strip(),
                    mint=mint.strip(),
                    amount_ui=float(amount),
                    decimals=decimals,
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="SPL token transfer",
                        mode="execute",
                    ),
                )

            if tool_name == "swap_solana_tokens":
                input_mint = args.get("input_mint")
                output_mint = args.get("output_mint")
                amount = args.get("amount")
                slippage_bps = args.get("slippage_bps", 50)
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(input_mint, str) or not input_mint.strip():
                    raise WalletBackendError("input_mint is required.")
                if not isinstance(output_mint, str) or not output_mint.strip():
                    raise WalletBackendError("output_mint is required.")
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise WalletBackendError("amount must be a positive number.")
                if not isinstance(slippage_bps, int) or slippage_bps <= 0:
                    raise WalletBackendError("slippage_bps must be a positive integer.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_swap(
                        input_mint=input_mint.strip(),
                        output_mint=output_mint.strip(),
                        amount_ui=float(amount),
                        slippage_bps=slippage_bps,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Swap",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_swap(
                        input_mint=input_mint.strip(),
                        output_mint=output_mint.strip(),
                        amount_ui=float(amount),
                        slippage_bps=slippage_bps,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Swap",
                            ),
                            action_label="Swap",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(self.backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(self.backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "Swap",
                    "network": str(getattr(self.backend, "network", "unknown")),
                    "input_mint": input_mint.strip(),
                    "output_mint": output_mint.strip(),
                    "slippage_bps": slippage_bps,
                }
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )
                try:
                    approved_amount = float(approval_summary.get("input_amount_ui"))
                except (TypeError, ValueError):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                if approved_amount != float(amount):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )

                approval_summary_copy = dict(approval_summary)
                approved_preview = args.get("_approved_preview")
                if isinstance(approval_summary_copy.get("_preview_digest"), str):
                    if not isinstance(approved_preview, dict):
                        raise WalletBackendError(
                            "Approved swap preview payload is required for execute mode. Generate a new preview and approval before execute."
                        )
                    if preview_payload_digest(approved_preview) != approval_summary_copy["_preview_digest"]:
                        raise WalletBackendError(
                            "approved preview payload does not match the approval token. Generate a new preview and approval before execute."
                        )
                    execute_preview = dict(approved_preview)
                else:
                    execute_preview = await self.backend.preview_swap(
                        input_mint=input_mint.strip(),
                        output_mint=output_mint.strip(),
                        amount_ui=float(amount),
                        slippage_bps=slippage_bps,
                    )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="Swap",
                )

                result = await self.backend.execute_swap_from_preview(execute_preview)
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Swap",
                        mode="execute",
                    ),
                )

            if tool_name == "swap_solana_privately":
                input_token = args.get("input_token")
                output_token = args.get("output_token")
                destination_address = args.get("destination_address")
                amount = args.get("amount")
                use_xmr = args.get("use_xmr", False)
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(input_token, str) or not input_token.strip():
                    raise WalletBackendError("input_token is required.")
                if not isinstance(output_token, str) or not output_token.strip():
                    raise WalletBackendError("output_token is required.")
                if not isinstance(destination_address, str) or not destination_address.strip():
                    raise WalletBackendError("destination_address is required.")
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise WalletBackendError("amount must be a positive number.")
                if not isinstance(use_xmr, bool):
                    raise WalletBackendError("use_xmr must be a boolean when provided.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "input_token": input_token.strip(),
                    "output_token": output_token.strip(),
                    "destination_address": destination_address.strip(),
                    "amount_ui": float(amount),
                    "use_xmr": use_xmr,
                }

                if mode == "preview":
                    preview = await self.backend.preview_solana_private_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Solana private swap",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_solana_private_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Solana private swap",
                            ),
                            action_label="Solana private swap",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(self.backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(self.backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "Solana private swap",
                    "network": str(getattr(self.backend, "network", "unknown")),
                    "destination_address": destination_address.strip(),
                    "use_xmr": use_xmr,
                }
                for key, expected_value in expected_summary.items():
                    if approval_summary.get(key) != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )
                try:
                    approved_amount = float(approval_summary.get("input_amount_ui"))
                except (TypeError, ValueError):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                if approved_amount != float(amount):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )

                approval_summary_copy = dict(approval_summary)
                approved_preview = args.get("_approved_preview")
                resume_private_swap_order = args.get("_resume_private_swap_order")
                if resume_private_swap_order is not None and not isinstance(resume_private_swap_order, dict):
                    raise WalletBackendError("_resume_private_swap_order must be an object when provided.")
                execute_preview = None
                if isinstance(approval_summary_copy.get("_preview_digest"), str):
                    if not isinstance(approved_preview, dict):
                        raise WalletBackendError(
                            "Approved private swap preview payload is required for execute mode. Generate a new preview and approval before execute."
                        )
                    if preview_payload_digest(approved_preview) != approval_summary_copy["_preview_digest"]:
                        raise WalletBackendError(
                            "approved preview payload does not match the approval token. Generate a new preview and approval before execute."
                        )
                    execute_preview = dict(approved_preview)

                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="Solana private swap",
                )

                result = await self.backend.execute_solana_private_swap(
                    **preview_kwargs,
                    approved_preview=execute_preview,
                    existing_order=resume_private_swap_order,
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Solana private swap",
                        mode="execute",
                    ),
                )

            if tool_name == "continue_solana_private_swap":
                approval_token = args.get("approval_token")
                approved_preview = args.get("_approved_preview")
                resume_private_swap_order = args.get("_resume_private_swap_order")
                if not isinstance(approved_preview, dict):
                    raise WalletBackendError(
                        "Approved private swap preview payload is required. Create the private swap order first."
                    )
                if not isinstance(resume_private_swap_order, dict) or not resume_private_swap_order:
                    raise WalletBackendError(
                        "A pending Houdini private swap order is required. Create the private swap order first."
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name="swap_solana_privately",
                    network=str(getattr(self.backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet_for_backend(self.backend),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested private swap. Generate a new approval from the preview first."
                    )

                approval_summary_copy = dict(approval_summary)
                if isinstance(approval_summary_copy.get("_preview_digest"), str):
                    if preview_payload_digest(approved_preview) != approval_summary_copy["_preview_digest"]:
                        raise WalletBackendError(
                            "approved preview payload does not match the approval token. Generate a new preview and approval before continue."
                        )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name="swap_solana_privately",
                    summary=approval_summary_copy,
                    action_label="Solana private swap",
                )

                result = await self.backend.continue_solana_private_swap(
                    approved_preview=approved_preview,
                    existing_order=resume_private_swap_order,
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Solana private swap funding",
                        mode="execute",
                    ),
                )

            if tool_name == "get_solana_private_swap_status":
                multi_id = args.get("multi_id")
                houdini_id = args.get("houdini_id")
                if multi_id is not None and not isinstance(multi_id, str):
                    raise WalletBackendError("multi_id must be a string when provided.")
                if houdini_id is not None and not isinstance(houdini_id, str):
                    raise WalletBackendError("houdini_id must be a string when provided.")
                normalized_multi_id = multi_id.strip() if isinstance(multi_id, str) and multi_id.strip() else None
                normalized_houdini_id = (
                    houdini_id.strip() if isinstance(houdini_id, str) and houdini_id.strip() else None
                )
                if normalized_multi_id is None and normalized_houdini_id is None:
                    raise WalletBackendError("multi_id or houdini_id is required.")
                data = await self.backend.get_solana_private_swap_status(
                    multi_id=normalized_multi_id,
                    houdini_id=normalized_houdini_id,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "swap_solana_lifi_cross_chain_tokens":
                input_token = args.get("input_token")
                destination_chain = args.get("destination_chain")
                output_token = args.get("output_token")
                destination_address = args.get("destination_address")
                amount_in_raw = args.get("amount_in_raw")
                slippage = self._normalize_lifi_slippage(args.get("slippage"))
                allow_bridges = self._normalize_optional_string_list(args.get("allow_bridges"), field_name="allow_bridges")
                deny_bridges = self._normalize_optional_string_list(args.get("deny_bridges"), field_name="deny_bridges")
                prefer_bridges = self._normalize_optional_string_list(args.get("prefer_bridges"), field_name="prefer_bridges")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(input_token, str) or not input_token.strip():
                    raise WalletBackendError("input_token is required.")
                if not isinstance(destination_chain, str) or not destination_chain.strip():
                    raise WalletBackendError("destination_chain is required.")
                if not isinstance(output_token, str) or not output_token.strip():
                    raise WalletBackendError("output_token is required.")
                if not isinstance(destination_address, str) or not destination_address.strip():
                    raise WalletBackendError("destination_address is required.")
                if not isinstance(amount_in_raw, str) or not amount_in_raw.strip().isdigit():
                    raise WalletBackendError("amount_in_raw must be a positive integer string.")
                if int(amount_in_raw.strip()) <= 0:
                    raise WalletBackendError("amount_in_raw must be greater than zero.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "input_token": input_token.strip(),
                    "destination_chain": destination_chain.strip(),
                    "output_token": output_token.strip(),
                    "destination_address": destination_address.strip(),
                    "amount_in_raw": amount_in_raw.strip(),
                    "slippage": slippage,
                    "allow_bridges": allow_bridges,
                    "deny_bridges": deny_bridges,
                    "prefer_bridges": prefer_bridges,
                }

                if mode == "preview":
                    preview = await self.backend.preview_solana_lifi_cross_chain_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Solana LI.FI cross-chain swap",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_solana_lifi_cross_chain_swap(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Solana LI.FI cross-chain swap",
                            ),
                            action_label="Solana LI.FI cross-chain swap",
                            mode="prepare",
                        ),
                    )

                approval_payload = inspect_approval_token(
                    approval_token,
                    tool_name=tool_name,
                    network=str(getattr(self.backend, "network", "unknown")),
                    require_mainnet_confirmation=self._is_mainnet(),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                destination_chain_id = self._canonicalize_lifi_chain_identifier(destination_chain)
                expected_summary = {
                    "operation": "Solana LI.FI cross-chain swap",
                    "network": str(getattr(self.backend, "network", "unknown")),
                    "source_chain": "solana",
                    "destination_chain": destination_chain_id,
                    "input_token": self._canonicalize_lifi_token_identifier(
                        input_token,
                        chain_id="1151111081099710",
                    ),
                    "output_token": self._canonicalize_lifi_token_identifier(
                        output_token,
                        chain_id=destination_chain_id,
                    ),
                    "destination_address": destination_address.strip(),
                    "input_amount_raw": amount_in_raw.strip(),
                }
                for key, expected_value in expected_summary.items():
                    actual_value = approval_summary.get(key)
                    if key == "destination_chain":
                        actual_value = self._canonicalize_lifi_chain_identifier(actual_value)
                    if key == "input_token":
                        actual_value = self._canonicalize_lifi_token_identifier(
                            actual_value,
                            chain_id="1151111081099710",
                        )
                    if key == "output_token":
                        actual_value = self._canonicalize_lifi_token_identifier(
                            actual_value,
                            chain_id=destination_chain_id,
                        )
                    if actual_value != expected_value:
                        raise WalletBackendError(
                            "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                        )

                approval_summary_copy = dict(approval_summary)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=approval_summary_copy,
                    action_label="Solana LI.FI cross-chain swap",
                )
                result = await self.backend.execute_solana_lifi_cross_chain_swap(
                    input_token=str(approval_summary_copy.get("input_token") or input_token).strip(),
                    destination_chain=str(
                        approval_summary_copy.get("destination_chain_id")
                        or approval_summary_copy.get("destination_chain")
                        or destination_chain
                    ).strip(),
                    output_token=str(approval_summary_copy.get("output_token") or output_token).strip(),
                    destination_address=str(
                        approval_summary_copy.get("destination_address") or destination_address
                    ).strip(),
                    amount_in_raw=str(approval_summary_copy.get("input_amount_raw") or amount_in_raw).strip(),
                    slippage=approval_summary_copy.get("slippage", slippage),
                    allow_bridges=allow_bridges,
                    deny_bridges=deny_bridges,
                    prefer_bridges=prefer_bridges,
                    minimum_output_amount_raw=(
                        str(approval_summary_copy.get("minimum_output_amount_raw")).strip()
                        if approval_summary_copy.get("minimum_output_amount_raw") is not None
                        else None
                    ),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Solana LI.FI cross-chain swap",
                        mode="execute",
                    ),
                )

            if tool_name == "claim_bags_fees":
                token_mint = args.get("token_mint")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(token_mint, str) or not token_mint.strip():
                    raise WalletBackendError("token_mint is required.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_bags_fee_claim(token_mint.strip())
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Bags fee claim",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_bags_fee_claim(token_mint.strip())
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Bags fee claim",
                            ),
                            action_label="Bags fee claim",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_bags_fee_claim(token_mint.strip())
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Bags fee claim",
                        payload=execute_preview,
                    ),
                    action_label="Bags fee claim",
                )
                result = await self.backend.execute_bags_fee_claim_from_preview(execute_preview)
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Bags fee claim",
                        mode="execute",
                    ),
                )

            if tool_name == "launch_bags_token":
                name = args.get("name")
                symbol = args.get("symbol")
                description = args.get("description")
                image_url = args.get("image_url")
                website = args.get("website")
                twitter = args.get("twitter")
                telegram = args.get("telegram")
                discord = args.get("discord")
                base_mint = args.get("base_mint")
                claimers = args.get("claimers")
                basis_points = args.get("basis_points")
                initial_buy_sol = args.get("initial_buy_sol")
                bags_config_type = args.get("bags_config_type")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                for field_name, value in (
                    ("name", name),
                    ("symbol", symbol),
                    ("description", description),
                    ("base_mint", base_mint),
                ):
                    if not isinstance(value, str) or not value.strip():
                        raise WalletBackendError(f"{field_name} is required.")
                for field_name, value in (
                    ("image_url", image_url),
                    ("website", website),
                    ("twitter", twitter),
                    ("telegram", telegram),
                    ("discord", discord),
                ):
                    if value is not None and not isinstance(value, str):
                        raise WalletBackendError(f"{field_name} must be a string when provided.")
                if not isinstance(claimers, list) or not claimers or not all(
                    isinstance(item, str) for item in claimers
                ):
                    raise WalletBackendError("claimers must be a non-empty array of strings.")
                if not isinstance(basis_points, list) or not basis_points or not all(
                    isinstance(item, int) for item in basis_points
                ):
                    raise WalletBackendError("basis_points must be a non-empty array of integers.")
                if not isinstance(initial_buy_sol, (int, float)) or initial_buy_sol < 0:
                    raise WalletBackendError("initial_buy_sol must be a non-negative number.")
                if bags_config_type is not None and not isinstance(bags_config_type, int):
                    raise WalletBackendError("bags_config_type must be an integer when provided.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                preview_kwargs = {
                    "name": name.strip(),
                    "symbol": symbol.strip(),
                    "description": description.strip(),
                    "image_url": image_url.strip() if isinstance(image_url, str) and image_url.strip() else None,
                    "website": website.strip() if isinstance(website, str) and website.strip() else None,
                    "twitter": twitter.strip() if isinstance(twitter, str) and twitter.strip() else None,
                    "telegram": telegram.strip() if isinstance(telegram, str) and telegram.strip() else None,
                    "discord": discord.strip() if isinstance(discord, str) and discord.strip() else None,
                    "base_mint": base_mint.strip(),
                    "claimers": claimers,
                    "basis_points": basis_points,
                    "initial_buy_sol": float(initial_buy_sol),
                    "bags_config_type": bags_config_type,
                }

                if mode == "preview":
                    preview = await self.backend.preview_bags_token_launch(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Bags token launch",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_bags_token_launch(**preview_kwargs)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Bags token launch",
                            ),
                            action_label="Bags token launch",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_bags_token_launch(**preview_kwargs)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Bags token launch",
                        payload=execute_preview,
                    ),
                    action_label="Bags token launch",
                )
                result = await self.backend.execute_bags_token_launch_from_preview(execute_preview)
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Bags token launch",
                        mode="execute",
                    ),
                )

            if tool_name == "jupiter_earn_deposit":
                asset = args.get("asset")
                amount_raw = args.get("amount_raw")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(asset, str) or not asset.strip():
                    raise WalletBackendError("asset is required.")
                if not isinstance(amount_raw, str) or not amount_raw.strip():
                    raise WalletBackendError("amount_raw is required.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_jupiter_earn_deposit(
                        asset=asset.strip(),
                        amount_raw=amount_raw.strip(),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Jupiter Earn deposit",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_jupiter_earn_deposit(
                        asset=asset.strip(),
                        amount_raw=amount_raw.strip(),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Jupiter Earn deposit",
                            ),
                            action_label="Jupiter Earn deposit",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_jupiter_earn_deposit(
                    asset=asset.strip(),
                    amount_raw=amount_raw.strip(),
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Jupiter Earn deposit",
                        payload=execute_preview,
                    ),
                    action_label="Jupiter Earn deposit",
                )
                result = await self.backend.execute_jupiter_earn_deposit(
                    asset=asset.strip(),
                    amount_raw=amount_raw.strip(),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Jupiter Earn deposit",
                        mode="execute",
                    ),
                )

            if tool_name == "jupiter_earn_withdraw":
                asset = args.get("asset")
                amount_raw = args.get("amount_raw")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(asset, str) or not asset.strip():
                    raise WalletBackendError("asset is required.")
                if not isinstance(amount_raw, str) or not amount_raw.strip():
                    raise WalletBackendError("amount_raw is required.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_jupiter_earn_withdraw(
                        asset=asset.strip(),
                        amount_raw=amount_raw.strip(),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Jupiter Earn withdraw",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_jupiter_earn_withdraw(
                        asset=asset.strip(),
                        amount_raw=amount_raw.strip(),
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Jupiter Earn withdraw",
                            ),
                            action_label="Jupiter Earn withdraw",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_jupiter_earn_withdraw(
                    asset=asset.strip(),
                    amount_raw=amount_raw.strip(),
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Jupiter Earn withdraw",
                        payload=execute_preview,
                    ),
                    action_label="Jupiter Earn withdraw",
                )
                result = await self.backend.execute_jupiter_earn_withdraw(
                    asset=asset.strip(),
                    amount_raw=amount_raw.strip(),
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Jupiter Earn withdraw",
                        mode="execute",
                    ),
                )

            if tool_name == "close_empty_token_accounts":
                limit = args.get("limit", 8)
                mode = args.get("mode")
                purpose = args.get("purpose")
                approval_token = args.get("approval_token")

                if not isinstance(limit, int) or limit <= 0:
                    raise WalletBackendError("limit must be a positive integer.")
                if mode not in {"preview", "execute"}:
                    raise WalletBackendError("mode must be 'preview' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_close_empty_token_accounts(limit=limit)
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Close token accounts",
                            mode="preview",
                        ),
                    )

                execute_preview = await self.backend.preview_close_empty_token_accounts(limit=limit)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Close token accounts",
                        payload=execute_preview,
                    ),
                    action_label="Close token accounts",
                )

                result = await self.backend.close_empty_token_accounts(limit=limit)
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Close token accounts",
                        mode="execute",
                    ),
                )

            if tool_name == "deactivate_solana_stake":
                stake_account = args.get("stake_account")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(stake_account, str) or not stake_account.strip():
                    raise WalletBackendError("stake_account is required.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_deactivate_stake(stake_account.strip())
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Stake deactivation",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_deactivate_stake(stake_account.strip())
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Stake deactivation",
                            ),
                            action_label="Stake deactivation",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_deactivate_stake(stake_account.strip())
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Stake deactivation",
                        payload=execute_preview,
                    ),
                    action_label="Stake deactivation",
                )
                result = await self.backend.execute_deactivate_stake(stake_account.strip())
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Stake deactivation",
                        mode="execute",
                    ),
                )

            if tool_name == "withdraw_solana_stake":
                stake_account = args.get("stake_account")
                amount = args.get("amount")
                recipient = args.get("recipient")
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                approval_token = args.get("approval_token")

                if not isinstance(stake_account, str) or not stake_account.strip():
                    raise WalletBackendError("stake_account is required.")
                if not isinstance(amount, (int, float)) or amount <= 0:
                    raise WalletBackendError("amount must be a positive number.")
                if recipient is not None and not isinstance(recipient, str):
                    raise WalletBackendError("recipient must be a string when provided.")
                if mode not in {"preview", "prepare", "execute"}:
                    raise WalletBackendError("mode must be 'preview', 'prepare' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_withdraw_stake(
                        stake_account=stake_account.strip(),
                        amount_native=float(amount),
                        recipient=recipient.strip() if isinstance(recipient, str) else None,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            preview,
                            action_label="Stake withdraw",
                            mode="preview",
                        ),
                    )

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    preview = await self.backend.preview_withdraw_stake(
                        stake_account=stake_account.strip(),
                        amount_native=float(amount),
                        recipient=recipient.strip() if isinstance(recipient, str) else None,
                    )
                    return AgentToolResult(
                        tool=tool_name,
                        ok=True,
                        data=self._annotate_sensitive_payload(
                            self._build_prepare_plan(
                                preview_payload=preview,
                                action_label="Stake withdraw",
                            ),
                            action_label="Stake withdraw",
                            mode="prepare",
                        ),
                    )

                execute_preview = await self.backend.preview_withdraw_stake(
                    stake_account=stake_account.strip(),
                    amount_native=float(amount),
                    recipient=recipient.strip() if isinstance(recipient, str) else None,
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Stake withdraw",
                        payload=execute_preview,
                    ),
                    action_label="Stake withdraw",
                )
                result = await self.backend.execute_withdraw_stake(
                    stake_account=stake_account.strip(),
                    amount_native=float(amount),
                    recipient=recipient.strip() if isinstance(recipient, str) else None,
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Stake withdraw",
                        mode="execute",
                    ),
                )

            raise WalletBackendError(f"Unsupported wallet tool: {tool_name}")
        except Exception as exc:
            if isinstance(exc, WalletBackendError):
                return AgentToolResult(
                    tool=tool_name,
                    ok=False,
                    error=str(exc),
                    error_code=exc.code,
                    error_details=exc.details,
                )
            if isinstance(exc, ProviderError):
                return AgentToolResult(
                    tool=tool_name,
                    ok=False,
                    error=str(exc),
                    error_code=exc.provider,
                    error_details=exc.details,
                )
            return AgentToolResult(tool=tool_name, ok=False, error=str(exc))
