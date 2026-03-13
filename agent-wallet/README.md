# OpenClaw Agent Wallet

Reusable wallet backend for OpenClaw agents.

Current focus:

- simple local Solana support
- send-enabled local operation with optional sign-only mode
- minimal external API surface
- easy embedding into agent runtimes or MCP adapters

## OpenClaw integration

The package now includes a thin adapter for agent runtimes:

- `agent_wallet.openclaw_adapter.OpenClawWalletAdapter`
- `agent_wallet.plugin_bundle.build_openclaw_plugin_bundle`
- `agent_wallet.openclaw_runtime.onboard_openclaw_user_wallet`
- `agent_wallet.openclaw_cli` for the official OpenClaw TypeScript plugin bridge

It provides:

- tool specs for agent registration
- runtime instructions for safe wallet usage
- a single `invoke()` method for safe dispatch
- OpenClaw-style plugin manifest and skill bundle

Current safe tools:

- `get_wallet_capabilities`
- `get_wallet_address`
- `get_wallet_balance`
- `get_wallet_portfolio`
- `get_solana_token_prices`
- `sign_wallet_message`
- `transfer_sol`
- `transfer_spl_token`
- `swap_solana_tokens`
- `close_empty_token_accounts`
- `request_devnet_airdrop`

The signing tool requires explicit `user_confirmed=true`.
Transfer and swap tools support `preview`, `prepare`, and `execute` modes. The safe operational path is still preview-first. `prepare` signs a transaction without broadcasting it. `execute` works only when the backend has a signer and `sign_only=false`.

Policy defaults:

- read-only tools are always allowed
- `prepare` requires `user_intent=true`
- `execute` requires `user_confirmed=true`
- on Solana `mainnet`, `execute` also requires `mainnet_confirmed=true`

## Install

```bash
cd agent-wallet
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and choose one of two modes:

1. Read-only:
   set `SOLANA_AGENT_PUBLIC_KEY`

2. Signing:
   set `SOLANA_AGENT_PRIVATE_KEY` or `SOLANA_AGENT_KEYPAIR_PATH`

For OpenClaw install/runtime, the intended creation flow is:

1. OpenClaw plugin config sets `backend=solana_local`
2. Optional: set `network=devnet`
3. Optional: set `autoCreateWallet=true`
4. On first startup, if no keypair exists and auto-create is enabled, the plugin creates a local wallet file under `~/.openclaw/wallets/`

For multi-user OpenClaw integration, use `agent_wallet.user_wallets.create_wallet_backend_for_user(user_id)`.
That provisions a wallet per user under:
`~/.openclaw/users/<normalized-user-id>/wallets/solana-<network>-agent.json`

Per-user wallets are now encrypted at rest by default. Set:

- `AGENT_WALLET_MASTER_KEY` to a strong deployment secret
- `AGENT_WALLET_ENCRYPT_USER_WALLETS=true`
- `AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS=true`

If a legacy plaintext per-user wallet already exists, the helper will migrate it in place on the next successful load when a master key is available.

Operational helpers for the host runtime are also available in `agent_wallet.user_wallets`:

- `get_user_wallet_storage_info(...)`
- `export_user_wallet_backup(...)`
- `rotate_user_wallet_encryption(...)`

These are service-level helpers for OpenClaw runtime/admin flows and are intentionally not exposed as agent tools.

Recommended host-side runtime flow:

1. OpenClaw resolves the authenticated `user_id`
2. Host runtime calls `onboard_openclaw_user_wallet(user_id, ...)`
3. The helper provisions or loads the user wallet, builds the backend, adapter, and plugin bundle
4. Host runtime stores `session_metadata()` and registers `serializable_bundle()["tools"]`
5. Tool execution is delegated to `context.plugin_bundle["invoke"]`

This keeps wallet creation and custody in the host/runtime layer while the agent only sees the safe tool surface.

## Official OpenClaw plugin

For the official OpenClaw agent, the repository now includes a workspace extension at:

`.openclaw/extensions/agent-wallet`

That extension uses the documented OpenClaw plugin shape:

- `index.ts`
- `openclaw.plugin.json`
- `skills/wallet-operator/SKILL.md`

It forwards tool execution to the Python bridge CLI:

`python -m agent_wallet.openclaw_cli`

This keeps the official OpenClaw-facing layer in TypeScript while the actual wallet/security logic remains in the Python backend.

Public-safe helper scripts are available in `agent-wallet/scripts/`:

- `install_openclaw_local_config.py`
- `finalize_openclaw_local_wallet_config.py`

Both scripts now use CLI arguments and generic defaults instead of hardcoded local usernames, paths, or temporary master keys.

Recommended devnet setup:

```bash
AGENT_WALLET_BACKEND=solana_local
AGENT_WALLET_MASTER_KEY=change-this-in-production
SOLANA_NETWORK=devnet
SOLANA_AUTO_CREATE_WALLET=true
AGENT_WALLET_SIGN_ONLY=false
```

## Current scope

- Solana balance lookup
- capability discovery
- message signing
- local keypair signer

The package now supports:

- transfer preview
- Jupiter token price lookup
- native SOL transfer execution
- SPL token transfer preview and execution by mint address
- Jupiter-based swap preview and execution on mainnet
- zero-balance token account cleanup
- devnet/testnet faucet airdrop
