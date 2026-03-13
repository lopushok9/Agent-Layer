"""Thin OpenClaw-facing adapter for agent wallet backends."""

from __future__ import annotations

from typing import Any

from agent_wallet.models import AgentToolResult, AgentToolSpec
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError


WALLET_RUNTIME_INSTRUCTIONS = """
Use wallet tools only when the user explicitly asks for wallet-related actions.
Treat any signing request as sensitive.
Before signing a message, make sure the user intent is explicit and the purpose is clear.
Never claim that funds were moved unless a transfer tool explicitly returns a confirmed transaction result.
If the wallet backend is sign-only, do not describe the action as broadcast on-chain.
If the backend supports signing but should not broadcast, prefer prepare mode instead of execute mode.
For transfers, prefer preview mode first. Only use execute mode after explicit user approval.
On mainnet, execute mode requires an additional mainnet confirmation step.
""".strip()


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

    def _require_execute_confirmation(
        self,
        *,
        user_confirmed: Any,
        mainnet_confirmed: Any,
        action_label: str,
    ) -> None:
        if user_confirmed is not True:
            raise WalletBackendError(
                f"{action_label} execution requires explicit user confirmation."
            )
        if self._is_mainnet() and mainnet_confirmed is not True:
            raise WalletBackendError(
                f"{action_label} execution on mainnet requires mainnet_confirmed=true."
            )

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
                                "description": "preview returns a transfer summary, prepare signs without broadcasting, execute attempts to send.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the transfer is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "user_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode.",
                            },
                            "mainnet_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode on mainnet.",
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
                                "description": "preview returns a transfer summary, prepare signs without broadcasting, execute attempts to send.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the transfer is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "user_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode.",
                            },
                            "mainnet_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode on mainnet.",
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
                                "description": "preview returns a quote, prepare signs without broadcasting, execute attempts to swap.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "Short explanation of why the swap is being made.",
                            },
                            "user_intent": {
                                "type": "boolean",
                                "description": "Must be true for prepare mode.",
                            },
                            "user_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode.",
                            },
                            "mainnet_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode on mainnet.",
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
                            "user_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode.",
                            },
                            "mainnet_confirmed": {
                                "type": "boolean",
                                "description": "Must be true for execute mode on mainnet.",
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

        return tools

    def get_runtime_instructions(self) -> str:
        """Return the instruction block to inject into the agent runtime."""
        return WALLET_RUNTIME_INSTRUCTIONS

    async def invoke(self, tool_name: str, arguments: dict[str, Any] | None = None) -> AgentToolResult:
        """Dispatch an agent-facing tool call to the wallet backend."""
        args = arguments or {}
        try:
            if tool_name == "get_wallet_capabilities":
                data = self.backend.get_capabilities().to_dict()
                return AgentToolResult(tool=tool_name, ok=True, data=data)

            if tool_name == "get_wallet_address":
                address = await self.backend.get_address()
                return AgentToolResult(
                    tool=tool_name,
                    ok=True,
                    data={"address": address, "configured": bool(address)},
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
                user_confirmed = args.get("user_confirmed", False)
                mainnet_confirmed = args.get("mainnet_confirmed", False)

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
                    return AgentToolResult(tool=tool_name, ok=True, data=preview)

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    prepared = await self.backend.prepare_native_transfer(
                        recipient=recipient.strip(),
                        amount_native=float(amount),
                    )
                    return AgentToolResult(tool=tool_name, ok=True, data=prepared)

                self._require_execute_confirmation(
                    user_confirmed=user_confirmed,
                    mainnet_confirmed=mainnet_confirmed,
                    action_label="SOL transfer",
                )

                result = await self.backend.send_native_transfer(
                    recipient=recipient.strip(),
                    amount_native=float(amount),
                )
                return AgentToolResult(tool=tool_name, ok=True, data=result)

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
                user_confirmed = args.get("user_confirmed", False)
                mainnet_confirmed = args.get("mainnet_confirmed", False)

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
                    return AgentToolResult(tool=tool_name, ok=True, data=preview)

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    prepared = await self.backend.prepare_spl_transfer(
                        recipient=recipient.strip(),
                        mint=mint.strip(),
                        amount_ui=float(amount),
                        decimals=decimals,
                    )
                    return AgentToolResult(tool=tool_name, ok=True, data=prepared)

                self._require_execute_confirmation(
                    user_confirmed=user_confirmed,
                    mainnet_confirmed=mainnet_confirmed,
                    action_label="SPL token transfer",
                )

                result = await self.backend.send_spl_transfer(
                    recipient=recipient.strip(),
                    mint=mint.strip(),
                    amount_ui=float(amount),
                    decimals=decimals,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=result)

            if tool_name == "swap_solana_tokens":
                input_mint = args.get("input_mint")
                output_mint = args.get("output_mint")
                amount = args.get("amount")
                slippage_bps = args.get("slippage_bps", 50)
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_intent = args.get("user_intent", False)
                user_confirmed = args.get("user_confirmed", False)
                mainnet_confirmed = args.get("mainnet_confirmed", False)

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
                    return AgentToolResult(tool=tool_name, ok=True, data=preview)

                if mode == "prepare":
                    self._require_prepare_intent(user_intent)
                    prepared = await self.backend.prepare_swap(
                        input_mint=input_mint.strip(),
                        output_mint=output_mint.strip(),
                        amount_ui=float(amount),
                        slippage_bps=slippage_bps,
                    )
                    return AgentToolResult(tool=tool_name, ok=True, data=prepared)

                self._require_execute_confirmation(
                    user_confirmed=user_confirmed,
                    mainnet_confirmed=mainnet_confirmed,
                    action_label="Swap",
                )

                result = await self.backend.execute_swap(
                    input_mint=input_mint.strip(),
                    output_mint=output_mint.strip(),
                    amount_ui=float(amount),
                    slippage_bps=slippage_bps,
                )
                return AgentToolResult(tool=tool_name, ok=True, data=result)

            if tool_name == "close_empty_token_accounts":
                limit = args.get("limit", 8)
                mode = args.get("mode")
                purpose = args.get("purpose")
                user_confirmed = args.get("user_confirmed", False)
                mainnet_confirmed = args.get("mainnet_confirmed", False)

                if not isinstance(limit, int) or limit <= 0:
                    raise WalletBackendError("limit must be a positive integer.")
                if mode not in {"preview", "execute"}:
                    raise WalletBackendError("mode must be 'preview' or 'execute'.")
                if not isinstance(purpose, str) or not purpose.strip():
                    raise WalletBackendError("purpose is required.")

                if mode == "preview":
                    preview = await self.backend.preview_close_empty_token_accounts(limit=limit)
                    return AgentToolResult(tool=tool_name, ok=True, data=preview)

                self._require_execute_confirmation(
                    user_confirmed=user_confirmed,
                    mainnet_confirmed=mainnet_confirmed,
                    action_label="Close token accounts",
                )

                result = await self.backend.close_empty_token_accounts(limit=limit)
                return AgentToolResult(tool=tool_name, ok=True, data=result)

            raise WalletBackendError(f"Unsupported wallet tool: {tool_name}")
        except Exception as exc:
            return AgentToolResult(tool=tool_name, ok=False, error=str(exc))
