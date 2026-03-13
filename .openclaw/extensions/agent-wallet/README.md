# Agent Wallet OpenClaw Extension

Workspace extension for the official OpenClaw agent.

This extension registers Solana wallet tools through the official OpenClaw plugin API and forwards execution to the local Python `agent-wallet` backend.

It is designed so the OpenClaw agent sees a small operational wallet surface instead of raw key management.
In practice this means the agent works through explicit tools for:

- wallet address, balances, and portfolio reads
- native SOL and SPL token transfers
- Jupiter swap and price lookup
- native Solana staking, stake deactivation, and stake withdrawal
- optional Jupiter Earn reads and write flows when API access is available

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
- Optional Jupiter overrides are available via `jupiterBaseUrl`, `jupiterUltraBaseUrl`, `jupiterPriceBaseUrl`, `jupiterPortfolioBaseUrl`, `jupiterLendBaseUrl`, and `jupiterApiKey`.
- Jupiter `Portfolio` and `Earn` features are treated as mainnet-only in the backend. `Earn` read/write endpoints require a valid `jupiterApiKey`.

## OpenClaw UX

The intended user-facing flow inside OpenClaw is:

1. Read first:
   use wallet address, balance, portfolio, validator list, or stake account inspection tools.
2. Preview next:
   transfers, swaps, staking, stake deactivation, and stake withdrawals should start in `preview`.
3. Prepare only with intent:
   `prepare` is for explicit signing intent without broadcast.
4. Execute only with approval:
   `execute` requires explicit confirmation, and `mainnet_confirmed=true` on mainnet.

For staking specifically, the normal agent flow should be:

1. `get_solana_staking_validators`
2. `stake_sol_native` in `preview`
3. `stake_sol_native` in `execute`
4. `get_solana_stake_account`
5. later, `deactivate_solana_stake` and `withdraw_solana_stake`
