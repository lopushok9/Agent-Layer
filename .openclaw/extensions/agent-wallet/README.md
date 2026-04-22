# Agent Wallet OpenClaw Extension

Workspace extension for the official OpenClaw agent.

This extension registers wallet tools through the official OpenClaw plugin API and forwards execution to the local Python `agent-wallet` backend.

It is designed so the OpenClaw agent sees a small operational wallet surface instead of raw key management.
In practice this means the agent works through explicit tools for:

- BTC balance, fee-rate, max-spendable, history, and transfer flows through the local `wdk-btc-wallet` backend
- EVM native balance, ERC-20 balance/metadata, fee-rate, receipt, Velora swap quote/execute, Aave V3 account/reserve/position flows, and transfer flows through the local `wdk-evm-wallet` backend
- wallet address, balances, and portfolio reads
- native SOL and SPL token transfers
- Jupiter swap and price lookup
- Jupiter Earn read/deposit/withdraw flows
- Kamino lending read/deposit/withdraw/borrow/repay flows
- native Solana staking, stake deactivation, and stake withdrawal

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
          "rpcUrls": [
            "https://your-primary-rpc.example",
            "https://api.devnet.solana.com"
          ],
          "signOnly": false,
          "encryptUserWallets": true,
          "migratePlaintextUserWallets": true,
          "refuseMainnetWalletRecreation": true,
          "packageRoot": "/absolute/path/to/agent-wallet",
          "pythonBin": "/absolute/path/to/python"
        }
      }
    }
  }
}
```

Recommended local installer entrypoint:

```bash
sh ./setup.sh
```

That installs the Python backend, Node dependencies for the local BTC/EVM runtimes, and patches the OpenClaw plugin config. Wallet creation, unlock, and local service start stay as separate host-side steps.

For self-hosted installs, prefer `SOLANA_RPC_URL` / `SOLANA_RPC_URLS` in local env and treat the plugin `rpcUrl` / `rpcUrls` fields as fallback only. If the local runtime exposes `ALCHEMY_API_KEY` or `HELIUS_API_KEY`, the wallet can derive the Solana RPC URL automatically for `mainnet` or `devnet`. Local env always takes precedence over `openclaw.json`.

Provide only `AGENT_WALLET_BOOT_KEY` to the runtime. Provision `master_key`, `approval_secret`, and any signer `private_key` into `sealed_keys.json`, not `openclaw.json`.

Important:

- For a local official OpenClaw install, `userId` should represent the wallet owner for that agent install.
- The public OpenClaw plugin docs do not document a per-request end-user identifier in `registerTool(...).execute(...)`, so dynamic multi-user wallet selection is intentionally kept in the Python/runtime layer, not inside the TypeScript plugin itself.
- Helper scripts in `agent-wallet/scripts/` are generic patch/finalize utilities and no longer assume a specific local username, path, or temporary master key.
- The OpenClaw plugin API in this repo exposes tool registration, not host password prompts, so BTC and EVM wallet create/unlock remain host-shell or CLI flows outside the agent tool surface.
- For a one-command local BTC onboarding path, use `agent-wallet/scripts/bootstrap_openclaw_btc.py`, which both sets up the BTC wallet binding and patches local OpenClaw config for `backend=wdk_btc_local`.
- The BTC flow now only supports local service URLs (`127.0.0.1` / `localhost` / `::1`).
- The local BTC service is protected with a bearer token loaded from `~/.openclaw/wdk-btc-wallet/local-auth-token`, not from plugin config JSON.
- When the BTC service URL is local, that bootstrap script can also auto-start `wdk-btc-wallet` before patching OpenClaw config.
- The EVM flow also only supports local service URLs (`127.0.0.1` / `localhost` / `::1`) and uses a bearer token loaded from `~/.openclaw/wdk-evm-wallet/local-auth-token`.
- The EVM tool surface is intentionally narrow: Velora swap quote/execute, Aave V3 account/reserve/position flows, native transfers, ERC-20 transfers, fee quotes, and receipt lookup only. No arbitrary calldata, standalone approvals, or generic contract execution are exposed to the agent.
- Velora swap and Aave V3 support are currently limited to `ethereum` and `base`. Test carefully because the upstream WDK protocol packages are still beta.
- EVM read and write tools now accept an optional per-call `network` override for `ethereum` or `base`, so the agent no longer needs host config edits just to switch between the two mainnet EVM paths.
- `get_wallet_balance` for EVM now returns an enriched portfolio-style payload: native balance, discovered ERC-20 balances, and USD values when token discovery and pricing are available.
- If the user needs to recover the mnemonic later, host-side reveal stays outside the agent tool surface via `agent-wallet/scripts/manage_openclaw_btc_wallet.py reveal-seed`.
- Optional Jupiter overrides are available via `jupiterBaseUrl`, `jupiterUltraBaseUrl`, `jupiterPriceBaseUrl`, `jupiterPortfolioBaseUrl`, `jupiterLendBaseUrl`, and `jupiterApiKey`.
- Optional Kamino overrides are available via `kaminoBaseUrl` and `kaminoProgramId`.
- Jupiter `Portfolio` implementation remains in the backend, but those agent-facing tools are temporarily disabled for now.
- Mainnet wallets are pinned by address. If a pinned mainnet wallet file disappears, the runtime refuses to silently create a replacement wallet.

## OpenClaw UX

The intended user-facing flow inside OpenClaw is:

1. Read first:
   use wallet address, balance, portfolio, validator list, or stake account inspection tools.
2. Preview next:
   transfers, swaps, Aave position changes, staking, stake deactivation, and stake withdrawals should start in `preview`.
3. Prepare only with intent:
   `prepare` is for explicit execution planning intent and returns no signed transaction bytes.
4. Execute only with approval:
   `execute` requires a host-issued `approval_token` bound to the exact previewed operation. On `mainnet`, that token must include explicit mainnet confirmation.
5. On mainnet, restate the network, asset, amount, and destination, validator, or stake account before execute.

For staking specifically, the normal agent flow should be:

1. `get_solana_staking_validators`
2. `stake_sol_native` in `preview`
3. `stake_sol_native` in `execute`
4. `get_solana_stake_account`
5. later, `deactivate_solana_stake` and `withdraw_solana_stake`

## Switching networks

The extension is already network-aware:

- `plugins.entries.agent-wallet.config.network` selects `mainnet`, `devnet`, or `testnet`
- each network uses a separate wallet file for the same `userId`
- switching networks does not merge balances across clusters

Recommended local switch helper:

```bash
python agent-wallet/scripts/switch_openclaw_wallet_network.py --network devnet
python agent-wallet/scripts/switch_openclaw_wallet_network.py --network mainnet
```

Use `--show-only` first if you want to inspect the target wallet path before changing the config.
