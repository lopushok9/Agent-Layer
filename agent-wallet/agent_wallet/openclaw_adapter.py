"""Thin OpenClaw-facing adapter for agent wallet backends."""

from __future__ import annotations

from typing import Any

from agent_wallet.approval import verify_approval_token
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

    def _is_mainnet(self) -> bool:
        return str(getattr(self.backend, "network", "")).strip().lower() == "mainnet"

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
            summary: dict[str, Any] = {
                "operation": action_label,
                "network": str(payload.get("network") or getattr(self.backend, "network", "unknown")),
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
        annotated["network"] = network
        annotated["confirmation_summary"] = self._build_confirmation_summary(
            action_label=action_label,
            payload=annotated,
        )
        annotated["confirmation_requirements"] = {
            "prepare_requires_user_intent": mode == "prepare",
            "execute_requires_approval_token": mode == "execute",
            "execute_requires_mainnet_confirmed_in_token": mode == "execute" and network == "mainnet",
        }
        if mode == "preview":
            annotated["approval_hint"] = {
                "host_must_issue_token_for": annotated["confirmation_summary"],
                "tool_name": None,
            }
        if network == "mainnet" and mode in {"preview", "prepare", "execute"}:
            annotated["mainnet_warning"] = (
                "Mainnet operation. Confirm the network, asset, amount, and destination, validator, or stake account "
                "before execute. Execute requires a host-issued approval token with mainnet confirmation."
            )
        return annotated

    def list_tools(self) -> list[AgentToolSpec]:
        """Return wallet tools suitable for agent registration."""
        capabilities = self.backend.get_capabilities()
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

                result = await self.backend.execute_swap(
                    input_mint=input_mint.strip(),
                    output_mint=output_mint.strip(),
                    amount_ui=float(amount),
                    slippage_bps=slippage_bps,
                )
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data=self._annotate_sensitive_payload(
                        result,
                        action_label="Swap",
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
            return AgentToolResult(tool=tool_name, ok=False, error=str(exc))
