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
        "Execute modes require an approval_token from agent_wallet_approve bound "
        "to the exact previewed operation after explicit user confirmation."
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

AGENT_WALLET_APPROVE = {
    "name": "agent_wallet_approve",
    "description": (
        "Issue a short-lived AgentLayer/OpenClaw approval_token for one exact "
        "wallet execute operation after the user explicitly confirms the previewed "
        "confirmation_summary. Use only after agent_wallet_invoke preview/prepare "
        "returns the exact confirmation_summary. Mainnet approvals require "
        "mainnet_confirmed=true."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Underlying wallet tool name that will be executed.",
            },
            "confirmation_summary": {
                "type": "object",
                "description": (
                    "Exact confirmation_summary from the preview or prepare result. "
                    "Do not edit or summarize it."
                ),
                "additionalProperties": True,
            },
            "user_confirmed": {
                "type": "boolean",
                "description": "Must be true only after the user explicitly approves this exact operation.",
            },
            "mainnet_confirmed": {
                "type": "boolean",
                "description": "Must be true for mainnet execute operations after explicit mainnet confirmation.",
            },
            "ttl_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "description": "Optional approval token lifetime in seconds.",
            },
            "backend": {
                "type": "string",
                "enum": ["solana_local", "wdk_btc_local", "wdk_evm_local"],
                "description": "Optional backend override matching the planned execute invocation.",
            },
            "network": {
                "type": "string",
                "description": "Optional network override matching the planned execute invocation.",
            },
            "user_id": {
                "type": "string",
                "description": "Optional local wallet owner id. Defaults to AGENT_WALLET_USER_ID, USER, or hermes-local-user.",
            },
            "config": {
                "type": "object",
                "description": (
                    "Optional non-secret wallet config overrides matching the planned execute invocation. "
                    "Do not include privateKey, masterKey, or approvalSecret."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["tool_name", "confirmation_summary", "user_confirmed"],
        "additionalProperties": False,
    },
}

AGENT_WALLET_EVM_STATUS = {
    "name": "agent_wallet_evm_status",
    "description": (
        "Inspect the local EVM wallet runtime used by AgentLayer/OpenClaw. "
        "Returns wdk-evm-wallet health, network info, and existing user wallet "
        "bindings without changing wallet state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "Optional local wallet owner id to inspect.",
            },
            "network": {
                "type": "string",
                "description": "Optional EVM network hint, such as ethereum, base, sepolia, or base-sepolia.",
            },
            "service_url": {
                "type": "string",
                "description": "Optional localhost override for the wdk-evm-wallet service.",
            },
        },
        "additionalProperties": False,
    },
}

AGENT_WALLET_EVM_SETUP = {
    "name": "agent_wallet_evm_setup",
    "description": (
        "Create or unlock the local EVM wallet binding used by AgentLayer/OpenClaw "
        "for Hermes. This can auto-start the localhost-only wdk-evm-wallet service, "
        "set up the selected network, and bind the same wallet to the paired EVM network "
        "such as ethereum/base."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "password": {
                "type": "string",
                "description": "Local EVM wallet password used to create or unlock the vault wallet.",
            },
            "user_id": {
                "type": "string",
                "description": "Optional local wallet owner id. Defaults to AGENT_WALLET_USER_ID, USER, or hermes-local-user.",
            },
            "network": {
                "type": "string",
                "description": "Selected EVM network, typically ethereum or base.",
            },
            "label": {
                "type": "string",
                "description": "Optional wallet label used when creating a new local EVM wallet.",
            },
            "service_url": {
                "type": "string",
                "description": "Optional localhost override for the wdk-evm-wallet service.",
            },
            "auto_start_service": {
                "type": "boolean",
                "description": "Whether to auto-start the local wdk-evm-wallet service when it is not healthy. Defaults to true.",
            },
            "bind_network_pair": {
                "type": "boolean",
                "description": "Whether to also bind the paired EVM network such as ethereum/base. Defaults to true.",
            },
        },
        "required": ["password"],
        "additionalProperties": False,
    },
}
