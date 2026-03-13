# Agent Wallet OpenClaw Extension

Workspace extension for the official OpenClaw agent.

This extension registers Solana wallet tools through the official OpenClaw plugin API and forwards execution to the local Python `agent-wallet` backend.

Expected local layout:

- this extension lives at `.openclaw/extensions/agent-wallet`
- the Python package lives at `agent-wallet/`

Recommended config:

```json
{
  "plugins": {
    "allow": ["agent-wallet"],
    "entries": {
      "agent-wallet": {
        "enabled": true,
        "config": {
          "userId": "openclaw-local-user",
          "backend": "solana_local",
          "network": "devnet",
          "signOnly": false,
          "masterKey": "change-this",
          "encryptUserWallets": true,
          "migratePlaintextUserWallets": true,
          "packageRoot": "/absolute/path/to/agent-wallet",
          "pythonBin": "/absolute/path/to/python"
        }
      }
    }
  }
}
```

Important:

- For a local official OpenClaw install, `userId` should represent the wallet owner for that agent install.
- The public OpenClaw plugin docs do not document a per-request end-user identifier in `registerTool(...).execute(...)`, so dynamic multi-user wallet selection is intentionally kept in the Python/runtime layer, not inside the TypeScript plugin itself.
- Helper scripts in `agent-wallet/scripts/` are generic patch/finalize utilities and no longer assume a specific local username, path, or temporary master key.
