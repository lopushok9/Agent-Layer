"""Tool schemas exposed to Hermes Agent."""

AGENT_WALLET_TOOLS = {
    "name": "agent_wallet_tools",
    "description": (
        "List AgentLayer wallet capabilities available through the Hermes bridge. "
        "Use this before agent_wallet_invoke when you need the exact underlying "
        "wallet tool names, JSON schemas, or safety levels. This is read-only and "
        "does not create, unlock, or modify wallets."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "backend": {
                "type": "string",
                "enum": ["all", "solana_local", "wdk_btc_local", "wdk_evm_local"],
                "description": "Optional backend filter. Defaults to all.",
            },
        },
        "additionalProperties": False,
    },
}

AGENT_WALLET_INVOKE = {
    "name": "agent_wallet_invoke",
    "description": (
        "Invoke one existing AgentLayer/OpenClaw wallet tool through the local "
        "Python wallet backend. Prefer read-only tools and preview modes first. "
        "Execute modes require a host-issued approval_token produced outside the "
        "agent conversation and bound to the exact previewed operation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Underlying wallet tool name, for example get_wallet_address or transfer_sol.",
            },
            "arguments": {
                "type": "object",
                "description": "JSON arguments for the underlying wallet tool.",
                "additionalProperties": True,
            },
            "backend": {
                "type": "string",
                "enum": ["solana_local", "wdk_btc_local", "wdk_evm_local"],
                "description": "Optional backend override for this invocation.",
            },
            "network": {
                "type": "string",
                "description": "Optional network override, such as devnet, mainnet, bitcoin, ethereum, or base.",
            },
            "user_id": {
                "type": "string",
                "description": "Optional local wallet owner id. Defaults to AGENT_WALLET_USER_ID, USER, or hermes-local-user.",
            },
            "config": {
                "type": "object",
                "description": (
                    "Optional non-secret wallet config overrides. Do not include privateKey, "
                    "masterKey, or approvalSecret."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["tool_name"],
        "additionalProperties": False,
    },
}
