"""Thin OpenClaw-facing adapter for agent wallet backends."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent_wallet.approval import inspect_approval_token, verify_approval_token
from agent_wallet.models import AgentToolResult, AgentToolSpec
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError


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
""".strip()

# Keep the backend implementation in place, but hide these agent-facing tools for now.
TEMPORARILY_DISABLED_TOOLS = {
    "get_jupiter_portfolio_platforms",
    "get_jupiter_portfolio",
    "get_jupiter_staked_jup",
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
            return normalized in {"ethereum", "base"}
        return normalized == "mainnet"

    def _is_mainnet(self) -> bool:
        return self._is_mainnet_network(getattr(self.backend, "network", ""))

    def _supports_evm_velora(self) -> bool:
        return str(getattr(self.backend, "chain", "")).strip().lower() == "evm" and self._is_mainnet()

    def _require_prepare_intent(self, user_intent: Any) -> None:
        if user_intent is not True:
            raise WalletBackendError(
                "Prepare mode requires explicit user intent confirmation."
            )

    def _require_execute_approval(
        self,
        *,
        approval_token: Any,
        tool_name: str,
        summary: dict[str, Any],
        action_label: str,
    ) -> None:
        if not isinstance(approval_token, str) or not approval_token.strip():
            raise WalletBackendError(
                f"{action_label} execution requires a host-issued approval_token."
            )
        verify_approval_token(
            approval_token.strip(),
            tool_name=tool_name,
            network=str(getattr(self.backend, "network", "unknown")),
            summary=summary,
            require_mainnet_confirmation=self._is_mainnet(),
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
            "execute_requires_approval_token": mode == "execute",
            "execute_requires_mainnet_confirmed_in_token": mode == "execute" and is_mainnet,
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
                    name="get_evm_token_balance",
                    description="Get the raw ERC-20 token balance for the configured EVM wallet account.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "token_address": {
                                "type": "string",
                                "description": "ERC-20 token contract address.",
                            }
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
                            }
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
                        "properties": {},
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
                            }
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
                            },
                            "required": ["token_in", "token_out", "amount_in_raw"],
                            "additionalProperties": False,
                        },
                        read_only=True,
                        risk_level="low",
                    ),
                )
                tools.insert(
                    7,
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
                            },
                            "required": ["token_in", "token_out", "amount_in_raw", "mode", "purpose"],
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
                description="Get the native token balance for the configured wallet address.",
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
                name="get_wallet_portfolio",
                description=(
                    "Get the wallet portfolio including native balance and non-zero SPL token accounts."
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

        return [tool for tool in tools if tool.name not in TEMPORARILY_DISABLED_TOOLS]

    def get_runtime_instructions(self) -> str:
        """Return the instruction block to inject into the agent runtime."""
        return WALLET_RUNTIME_INSTRUCTIONS

    async def invoke(self, tool_name: str, arguments: dict[str, Any] | None = None) -> AgentToolResult:
        """Dispatch an agent-facing tool call to the wallet backend."""
        args = arguments or {}
        try:
            if tool_name in TEMPORARILY_DISABLED_TOOLS:
                raise WalletBackendError(
                    f"{tool_name} is temporarily disabled. The implementation remains in the repo but this tool is currently turned off."
                )

            if tool_name == "get_wallet_capabilities":
                data = self.backend.get_capabilities().to_dict()
                data["network"] = str(getattr(self.backend, "network", "unknown"))
                data["address"] = await self.backend.get_address()
                data["is_mainnet"] = self._is_mainnet()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_wallet_address":
                address = await self.backend.get_address()
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data={
                        "address": address,
                        "configured": bool(address),
                        "network": str(getattr(self.backend, "network", "unknown")),
                        "is_mainnet": self._is_mainnet(),
                    },
                )

            if tool_name == "get_wallet_balance":
                address = args.get("address")
                if address is not None and not isinstance(address, str):
                    raise WalletBackendError("address must be a string when provided.")
                data = await self.backend.get_balance(address=address)
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

            if tool_name == "get_evm_token_balance":
                token_address = args.get("token_address")
                if not isinstance(token_address, str) or not token_address.strip():
                    raise WalletBackendError("token_address is required.")
                data = await self.backend.get_evm_token_balance(token_address.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_token_metadata":
                token_address = args.get("token_address")
                if not isinstance(token_address, str) or not token_address.strip():
                    raise WalletBackendError("token_address is required.")
                data = await self.backend.get_evm_token_metadata(token_address.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_fee_rates":
                data = await self.backend.get_evm_fee_rates()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_evm_transaction_receipt":
                tx_hash = args.get("tx_hash")
                if not isinstance(tx_hash, str) or not tx_hash.strip():
                    raise WalletBackendError("tx_hash is required.")
                data = await self.backend.get_evm_transaction_receipt(tx_hash.strip())
                return AgentToolResult(tool=tool_name, ok=True, data=data)

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
                data = await self.backend.get_evm_swap_quote(
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
                    preview = await self.backend.preview_evm_swap(**preview_kwargs)
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
                    preview = await self.backend.preview_evm_swap(**preview_kwargs)
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
                    network=str(getattr(self.backend, "network", "unknown")),
                    require_mainnet_confirmation=getattr(self.backend, "is_mainnet", False),
                )
                approval_summary = approval_payload.get("binding", {}).get("summary")
                if not isinstance(approval_summary, dict):
                    raise WalletBackendError(
                        "approval_token does not match the requested operation. Generate a new approval after previewing the exact action."
                    )
                expected_summary = {
                    "operation": "EVM swap",
                    "network": str(getattr(self.backend, "network", "unknown")),
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
                )
                bound_quote_fingerprint = approval_summary_copy.get("quote_fingerprint")
                bound_minimum_output_amount_raw = approval_summary_copy.get("minimum_output_amount_raw")
                if isinstance(bound_quote_fingerprint, str) and bound_quote_fingerprint.strip():
                    result = await self.backend.send_evm_swap(
                        **preview_kwargs,
                        expected_quote_fingerprint=bound_quote_fingerprint.strip(),
                        minimum_output_amount_raw=(
                            str(bound_minimum_output_amount_raw).strip()
                            if bound_minimum_output_amount_raw is not None
                            else None
                        ),
                    )
                else:
                    result = await self.backend.send_evm_swap(
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
                    preview = await self.backend.preview_evm_native_transfer(**preview_kwargs)
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
                    preview = await self.backend.preview_evm_native_transfer(**preview_kwargs)
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

                execute_preview = await self.backend.preview_evm_native_transfer(**preview_kwargs)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="EVM native transfer",
                        payload=execute_preview,
                    ),
                    action_label="EVM native transfer",
                )
                result = await self.backend.send_evm_native_transfer(**preview_kwargs)
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
                    preview = await self.backend.preview_evm_token_transfer(**preview_kwargs)
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
                    preview = await self.backend.preview_evm_token_transfer(**preview_kwargs)
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

                execute_preview = await self.backend.preview_evm_token_transfer(**preview_kwargs)
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="EVM token transfer",
                        payload=execute_preview,
                    ),
                    action_label="EVM token transfer",
                )
                result = await self.backend.send_evm_token_transfer(**preview_kwargs)
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

                execute_preview = await self.backend.preview_swap(
                    input_mint=input_mint.strip(),
                    output_mint=output_mint.strip(),
                    amount_ui=float(amount),
                    slippage_bps=slippage_bps,
                )
                self._require_execute_approval(
                    approval_token=approval_token,
                    tool_name=tool_name,
                    summary=self._build_confirmation_summary(
                        action_label="Swap",
                        payload=execute_preview,
                    ),
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
            return AgentToolResult(tool=tool_name, ok=False, error=str(exc))
