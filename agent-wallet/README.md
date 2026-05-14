# OpenClaw Agent Wallet

Reusable wallet backend for OpenClaw agents.

Current focus:

- simple local Solana support
- separate local BTC and EVM custody runtimes
- send-enabled local operation with optional sign-only mode
- minimal external API surface
- easy embedding into agent runtimes or MCP adapters

## OpenClaw integration

The package now includes a thin adapter for agent runtimes:

- `agent_wallet.openclaw_adapter.OpenClawWalletAdapter`
- `agent_wallet.plugin_bundle.build_openclaw_plugin_bundle`
- `agent_wallet.openclaw_runtime.onboard_openclaw_user_wallet`
- `agent_wallet.openclaw_cli` for the official OpenClaw TypeScript plugin bridge
- `hermes/plugins/agent_wallet` as an optional Hermes Agent bridge to the same CLI

It provides:

- tool specs for agent registration
- runtime instructions for safe wallet usage
- a single `invoke()` method for safe dispatch
- OpenClaw-style plugin manifest and skill bundle
- explicit network-aware results so the host and agent can see `devnet` vs `mainnet`

## Hermes integration

The optional Hermes plugin is intentionally a bridge, not a port of the OpenClaw plugin. It registers:

- `agent_wallet_tools` - read-only discovery for the underlying Python adapter tool specs.
- `agent_wallet_invoke` - a dispatcher that calls `python -m agent_wallet.openclaw_cli invoke`.
- `agent_wallet_approve` - a host approval-token issuer for exact execute operations.
- `agent_wallet_evm_status` - a read-only EVM runtime and binding inspector.
- `agent_wallet_evm_setup` - a host-side EVM bootstrap helper for Hermes.

Install it with:

```bash
npx @agentlayer.tech/wallet hermes install --yes
```

That command symlinks `hermes/plugins/agent_wallet` into `~/.hermes/plugins/agent_wallet`, enables the plugin with `hermes plugins enable agent-wallet`, and writes `AGENT_WALLET_PACKAGE_ROOT`, `AGENT_WALLET_PYTHON`, and `AGENT_WALLET_BOOT_KEY_FILE` into `~/.hermes/.env`. OpenClaw remains the canonical host integration and wallet safety policy remains in Python.

Hermes tool config must not contain wallet secrets. Use the existing sealed runtime path and host-issued approval tokens for execute flows. `AGENT_WALLET_BOOT_KEY_FILE` lets OpenClaw and Hermes reference one local boot-key file instead of duplicating the boot key across multiple env files.

For EVM on Hermes, the intended host flow is:

- call `agent_wallet_evm_status` to inspect `wdk-evm-wallet` health and current bindings
- call `agent_wallet_evm_setup` once to auto-start the local service when needed, create or unlock the local EVM wallet, and patch local OpenClaw config to `backend=wdk_evm_local`
- then use ordinary `agent_wallet_invoke` calls for EVM reads, transfers, swaps, and Aave flows

Current safe tools:

- `get_wallet_capabilities`
- `get_wallet_address`
- `get_wallet_balance`
- `get_evm_token_metadata`
- `get_btc_transfer_history`
- `get_btc_fee_rates`
- `get_btc_max_spendable`
- `transfer_btc`
- `get_evm_token_balance`
- `get_evm_fee_rates`
- `get_evm_transaction_receipt`
- `get_evm_swap_quote`
- `swap_evm_tokens`
- `get_evm_aave_account`
- `get_evm_aave_reserves`
- `get_evm_aave_positions`
- `manage_evm_aave_position`
- `get_lifi_supported_chains`
- `get_lifi_quote`
- `get_lifi_transfer_status`
- `transfer_evm_native`
- `transfer_evm_token`
- `swap_evm_lifi_cross_chain_tokens` - EVM-origin LI.FI routes from Ethereum/Base to Ethereum/Base/Solana when LI.FI returns a route.
- `swap_solana_lifi_cross_chain_tokens` - Solana-origin LI.FI routes from Solana to Ethereum/Base when LI.FI returns a route.
- `get_wallet_portfolio`
- `get_solana_token_prices`
- `get_solana_staking_validators`
- `get_solana_stake_account`
- `sign_wallet_message`
- `transfer_sol`
- `stake_sol_native`
- `transfer_spl_token`
- `swap_solana_tokens`
- `swap_solana_privately` - Houdini-backed private Solana payout flow for same-token `SOL->SOL` or `USDC->USDC` transfers to a destination wallet.
- `get_solana_private_swap_status`
- `get_jupiter_earn_tokens`
- `get_jupiter_earn_positions`
- `get_jupiter_earn_earnings`
- `get_kamino_lend_markets`
- `get_kamino_lend_market_reserves`
- `get_kamino_lend_user_obligations`
- `get_kamino_lend_user_rewards`
- `jupiter_earn_deposit`
- `jupiter_earn_withdraw`
- `kamino_lend_deposit`
- `kamino_lend_withdraw`
- `kamino_lend_borrow`
- `kamino_lend_repay`
- `close_empty_token_accounts`
- `deactivate_solana_stake`
- `withdraw_solana_stake`
- `request_devnet_airdrop`

Temporarily disabled but kept in the codebase for later re-enable:

- `get_jupiter_portfolio_platforms`
- `get_jupiter_portfolio`
- `get_jupiter_staked_jup`

The signing tool still requires explicit `user_confirmed=true`.
Transfer, native staking, swap, and Aave position-management tools support `preview`, `prepare`, and `execute` modes. The safe operational path is still preview-first. `prepare` now returns an execution plan only and never exposes signed transaction bytes to the agent. `execute` works only when the backend has a signer and `sign_only=false`.

Exception: `swap_solana_privately` is intentionally optimized for `preview -> execute`. Hosts should not insert a separate `prepare` step for Houdini private payouts because it adds no execution value and only burns additional provider quota.

Policy defaults:

- read-only tools are always allowed
- `prepare` requires `user_intent=true`
- `prepare` does not return signed transaction bytes
- `execute` requires a host-issued `approval_token` bound to the exact previewed operation
- on mainnet networks, that `approval_token` must include explicit mainnet confirmation
- on mainnet networks, preview and prepare responses include a `confirmation_summary` and `mainnet_warning` to force a clearer final confirmation step

## Install

```bash
cd agent-wallet
pip install -e .
```

If you want a simpler local setup flow, use the installer:

```bash
sh ../setup.sh
```

If you already use a local coding agent on the same machine, it can run this installer for you. You can simply ask the agent to install the wallet, and it can perform the file setup, Python setup, and OpenClaw config patching steps automatically.

By default it will:

- create `.env` from `.env.example` if missing
- create `.venv` and install `agent-wallet` into it
- install Node dependencies for `wdk-btc-wallet` and `wdk-evm-wallet`
- create a minimal `~/.openclaw/openclaw.json` if needed
- run `install_openclaw_local_config.py` automatically when the required secret env vars are already present
- otherwise return a JSON summary with `pending_env` and the exact next configure command

For a future `curl | bash` entrypoint, the repo now also includes a remote bootstrap wrapper at [`install-from-github.sh`](/Users/yuriytsygankov/Documents/openclaw_skill/install-from-github.sh). That script resolves the newest matching release bundle asset from GitHub Release metadata, downloads it, and then delegates to `setup.sh`.

For release assets, use the bundle builder:

```bash
python3 agent-wallet/scripts/build_release_bundle.py
```

That produces a release tarball with a broad runtime/backend slice of the repo while excluding the marketing site, docs site, local notes, and generated/dev artifacts.

The boundary stays the same: the operator must still provide the root secrets. The installer may be executed by an agent, but `AGENT_WALLET_BOOT_KEY`, `AGENT_WALLET_MASTER_KEY`, and `AGENT_WALLET_APPROVAL_SECRET` should be created or chosen by the user and then supplied to the runtime environment.

For a no-network or pre-existing Python setup, add:

```bash
python3 scripts/install_agent_wallet.py --skip-python-setup --skip-node-setup
```

## Configuration

Copy `.env.example` to `.env` and choose one of two modes:

1. Read-only:
   set `SOLANA_AGENT_PUBLIC_KEY`

2. Signing:
   set `SOLANA_AGENT_PRIVATE_KEY` or `SOLANA_AGENT_KEYPAIR_PATH`

For production `mainnet`, prefer a dedicated RPC instead of the public Solana endpoint. You can now configure either:

- `SOLANA_RPC_URL` for one primary endpoint
- `SOLANA_RPC_URLS` as a comma-separated ordered failover list
- or just `ALCHEMY_API_KEY` / `HELIUS_API_KEY`, which auto-derive a primary Solana RPC for `mainnet` or `devnet`

Production recommendation: treat RPC as deployment-owned config, not wallet logic. Runtime env wins over `openclaw.json` plugin config, so keep `Alchemy/Helius/QuickNode` endpoints in deployment secrets or service env and use plugin `rpcUrl` / `rpcUrls` only as local fallback.

For Houdini-backed private Solana payouts, also provide:

- `HOUDINI_API_KEY`
- `HOUDINI_API_SECRET`
- `HOUDINI_USER_IP`
- optional `HOUDINI_USER_AGENT`
- optional `HOUDINI_USER_TIMEZONE`

The current MVP intentionally keeps the scope narrow:

- supported private routes are same-token Solana payouts only
- `SOL -> SOL`
- `USDC -> USDC`
- execution binds to the approved Houdini `quoteId`, creates a single private exchange, and sends the exact Solana deposit locally from the wallet

This is a private payout flow expressed in Houdini's swap terminology. Cross-token private swaps can be added later without changing the OpenClaw/Hermes approval model.

For production, the cleaner setup is to place Houdini partner secrets on `provider-gateway` and let `agent-wallet` consume the narrow gateway endpoints through `PROVIDER_GATEWAY_URL` and optional `PROVIDER_GATEWAY_BEARER_TOKEN`. In that mode:

- the gateway owns `HOUDINI_API_KEY` / `HOUDINI_API_SECRET`
- the gateway derives the authoritative user IP from ingress
- `agent-wallet` still performs preview/prepare/execute, local transaction verification, signing, and broadcast
- direct Houdini env vars can be omitted from the wallet runtime

For OpenClaw onboarding, `agent-wallet` now ships with a hosted default provider gateway:

- `https://agent-layer-production.up.railway.app`

So users do not need to enter `PROVIDER_GATEWAY_URL` manually for the default Bags launch/fees flows or shared mainnet RPC path. You only need to set `PROVIDER_GATEWAY_URL` yourself if you want to override that hosted default with your own deployment.

That same provider gateway path can now also cover Jupiter Earn reads and transaction-building. Ordinary Jupiter swap routing remains direct.

For a self-hosted install where each operator brings their own RPC key, a minimal Solana setup can be just:

```bash
AGENT_WALLET_BOOT_KEY=...
ALCHEMY_API_KEY=...
# or
HELIUS_API_KEY=...
```

`AGENT_WALLET_BOOT_KEY` is the root local secret for the wallet runtime. It is not a wallet private key, not a Solana keypair, and not something provided by this repository or by OpenClaw. The operator must generate it locally and keep it safe.

What it is used for:

- unlocking `~/.openclaw/sealed_keys.json`
- decrypting the stored `master_key`, `approval_secret`, and optional signer `private_key`
- allowing the runtime to start without placing those secrets directly in plain environment variables

What it is not:

- not the on-chain wallet address
- not the Solana signing key
- not a key that should be committed to GitHub
- not something the agent should silently invent and hide from the operator

Recommended generation:

```bash
openssl rand -base64 32
```

Alternative:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Recommended handling:

- store it in a password manager or local secret store
- export it locally in shell env or deployment env
- keep a backup, because losing it means the existing `sealed_keys.json` bundle can no longer be decrypted

Example:

```bash
export AGENT_WALLET_BOOT_KEY='paste-generated-secret-here'
```

In that mode, `agent-wallet` will auto-resolve:

- `mainnet` -> `https://solana-mainnet.g.alchemy.com/v2/<ALCHEMY_API_KEY>`
- `devnet` -> `https://solana-devnet.g.alchemy.com/v2/<ALCHEMY_API_KEY>`
- `mainnet` -> `https://mainnet.helius-rpc.com/?api-key=<HELIUS_API_KEY>`
- `devnet` -> `https://devnet.helius-rpc.com/?api-key=<HELIUS_API_KEY>`

and still append the official Solana endpoint as fallback.

For OpenClaw self-hosting, this means users can keep their own Alchemy/Helius key locally in `.env` or shell env. Nothing needs to be proxied or hosted by us.

For OpenClaw install/runtime, the intended creation flow is:

1. OpenClaw plugin config sets `backend=solana_local`
2. Optional: set `network=devnet`
3. Optional: set `autoCreateWallet=true`
4. On first startup, if no keypair exists and auto-create is enabled, the plugin creates a local wallet file under `~/.openclaw/wallets/`

For multi-user OpenClaw integration, use `agent_wallet.user_wallets.create_wallet_backend_for_user(user_id)`.
That provisions a wallet per user under:
`~/.openclaw/users/<normalized-user-id>/wallets/solana-<network>-agent.json`

For the local BTC backend (`backend=wdk_btc_local`), the host-side lifecycle now follows the same pattern:

- the local `wdk-btc-wallet` service holds the encrypted seed vault
- the BTC service is localhost-only and no longer accepts remote service URLs through the OpenClaw BTC flow
- `agent-wallet` talks to it through a local bearer token loaded from `~/.openclaw/wdk-btc-wallet/local-auth-token`
- `agent-wallet` stores only a per-user BTC wallet binding under `~/.openclaw/users/<normalized-user-id>/wallets/btc-<network>-agent.json`
- you can manage that binding through `agent_wallet.openclaw_cli`:
  - `btc-wallet-create`
  - `btc-wallet-import`
  - `btc-wallet-get`
  - `btc-wallet-unlock`
  - `btc-wallet-lock`
- or more conveniently through `scripts/manage_openclaw_btc_wallet.py`

Example host-side BTC wallet creation:

```bash
printf '%s\n' 'your-local-btc-password' | \
python -m agent_wallet.openclaw_cli btc-wallet-create \
  --user-id alice@example.com \
  --password-stdin \
  --config-json '{"backend":"wdk_btc_local","network":"testnet","wdkBtcServiceUrl":"http://127.0.0.1:8080"}'
```

If you want a friendlier host-shell flow, use:

```bash
python scripts/manage_openclaw_btc_wallet.py setup \
  --user-id alice@example.com \
  --network testnet \
  --service-url http://127.0.0.1:8080
```

`setup` is the easiest host path:

- if no BTC wallet binding exists for that `user_id`, it creates one
- if the binding already exists, it unlocks the existing wallet
- it returns an `openclaw_config_hint` payload you can paste into plugin config if needed

If you want a true one-command OpenClaw bootstrap, use:

```bash
python agent-wallet/scripts/bootstrap_openclaw_btc.py \
  --user-id alice@example.com \
  --network testnet \
  --service-url http://127.0.0.1:8080
```

For BTC mainnet, use the same bootstrap with `--network mainnet`. The script normalizes that to `bitcoin` in plugin config automatically.

For the simplest host-side UX, use the shell wrapper instead:

```bash
sh agent-wallet/scripts/setup_btc_wallet.sh
```

That is the intended "agent/host installs, user only enters password" entrypoint:

- the script wraps the full BTC bootstrap
- it auto-starts the local `wdk-btc-wallet` service for localhost URLs if needed
- it asks for `user-id` and shows a small `mainnet / testnet / regtest` menu if you did not pass them as args or env
- it prompts for the BTC wallet password interactively unless you explicitly pass `--password-stdin`
- it prefers `/tmp/agent-wallet-venv/bin/python`, then `agent-wallet/.venv/bin/python`, and only then falls back to system `python3`
- it creates or unlocks the BTC wallet binding and patches local OpenClaw config in one pass
- it relies on the local auth token generated by `wdk-btc-wallet`; you do not need to paste that token into OpenClaw config

Useful optional env defaults:

```bash
export OPENCLAW_BTC_USER_ID=alice@example.com
export OPENCLAW_BTC_NETWORK=mainnet
export OPENCLAW_BTC_SERVICE_URL=http://127.0.0.1:8080
```

Then the wrapper can run with no arguments at all.

That script:

- runs BTC wallet `setup`
- checks `wdk-btc-wallet /health`
- auto-starts the local `wdk-btc-wallet` service if `--service-url` points to `127.0.0.1` or `localhost` and the service is not already running
- creates or updates `~/.openclaw/openclaw.json`
- configures `backend=wdk_btc_local`
- writes the local BTC service URL into plugin config
- keeps the local bearer token out of plugin config JSON

If your local `wdk-btc-wallet` repo lives somewhere else, pass:

```bash
--wdk-wallet-root /absolute/path/to/wdk-btc-wallet
```

To reveal the seed phrase later as the user/host:

```bash
sh agent-wallet/scripts/reveal_btc_seed.sh
```

That wrapper also prompts for `user-id` and network if you do not pass them explicitly.

This remains host-only. The agent does not get a seed-reveal tool.

After that, `onboard` and `invoke` can use the bound BTC wallet by `user_id` without manually passing `wdkBtcWalletId` every time.

For the local EVM backend (`backend=wdk_evm_local`), the lifecycle mirrors the BTC path:

- the local `wdk-evm-wallet` service holds the encrypted seed vault
- the EVM service is localhost-only and no longer accepts remote service URLs through the OpenClaw EVM flow
- `agent-wallet` talks to it through a local bearer token loaded from `~/.openclaw/wdk-evm-wallet/local-auth-token`
- `agent-wallet` stores only a per-user EVM wallet binding under `~/.openclaw/users/<normalized-user-id>/wallets/evm-<network>-agent.json`
- supported EVM networks are `ethereum`, `sepolia`, `base`, and `base-sepolia`
- OpenClaw-facing EVM tools accept an optional per-call `network` override for `ethereum` or `base`, so the agent can switch between the two mainnet EVM paths without editing host config
- EVM `get_wallet_balance` now returns an enriched portfolio-style payload with native balance, discovered ERC-20 balances, and USD values when token discovery and pricing are available
- if a requested EVM network binding is missing, `agent-wallet` auto-binds it from the same local wallet when there is exactly one reusable EVM wallet for that user or when `wdkEvmWalletId` is provided explicitly
- you can manage that binding through `agent_wallet.openclaw_cli`:
  - `evm-wallet-create`
  - `evm-wallet-import`
  - `evm-wallet-get`
  - `evm-wallet-unlock`
  - `evm-wallet-lock`

For a simpler host-side bootstrap, use:

```bash
sh agent-wallet/scripts/setup_evm_wallet.sh
```

That wrapper:

- prompts for `user-id` and EVM network when run interactively
- defaults to `http://127.0.0.1:8081`
- can auto-start `wdk-evm-wallet/run-local.sh` if the local service is not already healthy
- creates or unlocks the local EVM wallet binding
- also binds the paired EVM network by default: `ethereum <-> base`, `sepolia <-> base-sepolia`
- patches OpenClaw config to `backend=wdk_evm_local`

Example host-side EVM wallet creation:

```bash
printf '%s\n' 'your-local-evm-password' | \
python -m agent_wallet.openclaw_cli evm-wallet-create \
  --user-id alice@example.com \
  --password-stdin \
  --config-json '{"backend":"wdk_evm_local","network":"sepolia","wdkEvmServiceUrl":"http://127.0.0.1:8081"}'
```

After that, `onboard` and `invoke` can use the bound EVM wallet by `user_id` without manually passing `wdkEvmWalletId` every time.

Per-user wallets are now encrypted at rest in one hardened mode:

- runtime must have `AGENT_WALLET_BOOT_KEY`
- runtime secrets live only in `~/.openclaw/sealed_keys.json`
- per-user HKDF derivation is always on for `user_id + network`
- per-user wallet files are always encrypted
- `AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS=true` controls whether legacy plaintext/global-master wallets are auto-migrated on load

Do not store `masterKey`, `privateKey`, or approval secrets in plugin config JSON or direct runtime environment variables.
`AGENT_WALLET_MASTER_KEY`, `AGENT_WALLET_APPROVAL_SECRET`, and `SOLANA_AGENT_PRIVATE_KEY` are now provisioning-only inputs for installer/admin scripts and are rejected by the runtime.
Create or update that sealed file with:

```bash
AGENT_WALLET_BOOT_KEY=... \
AGENT_WALLET_MASTER_KEY=... \
AGENT_WALLET_APPROVAL_SECRET=... \
python scripts/install_openclaw_sealed_keys.py
```

Add `SOLANA_AGENT_PRIVATE_KEY=...` as well if you want the local signer secret to live in the sealed bundle instead of plain env.
If you already run `python scripts/install_openclaw_local_config.py` with `AGENT_WALLET_BOOT_KEY` and one or more of those secret env vars set, the installer now creates or updates `sealed_keys.json` automatically in the same pass.

If a legacy plaintext per-user wallet already exists, the helper will migrate it in place on the next successful load when a sealed master key is available.
Existing encrypted wallets created under the old global master-key mode are also migrated in place on the next successful load.

Mainnet hardening:

- per-user wallets now pin the expected wallet address in a sidecar file
- if a pinned `mainnet` wallet file disappears, the runtime refuses to silently create a replacement wallet
- this reduces the risk of a user unknowingly switching to a fresh address and losing access to funds at the original address

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

## Network switching

The wallet backend is already network-scoped:

- `devnet` and `mainnet` use different wallet files
- per-user wallets are stored as `solana-<network>-agent.json`
- switching networks does not mix balances or stake accounts across clusters

For a local OpenClaw install, use:

```bash
python agent-wallet/scripts/switch_openclaw_wallet_network.py --network devnet
python agent-wallet/scripts/switch_openclaw_wallet_network.py --network mainnet
```

Useful flags:

- `--show-only` shows which wallet path will be used without changing config
- `--sign-only` or `--no-sign-only` updates the execution mode together with the network
- `--rpc-url` updates the local fallback RPC endpoint for the selected network

## Jupiter coverage

Current Jupiter integration now includes:

- `Ultra Swap` as the default swap path, with legacy `Metis` fallback
- `Price API` token lookup
- `Earn` reads and deposit/withdraw transaction building

Operational notes:

- Jupiter `Earn` can use the hosted or self-hosted provider gateway for shared onboarding-friendly access.
- Ordinary Jupiter swap routing remains direct and does not go through the provider gateway.
- Jupiter `Portfolio` implementation remains in the backend, but the agent-facing tools are temporarily disabled.
- The Jupiter config fields and provider code are intentionally kept so these surfaces can be restored later without rebuilding the integration from scratch.

## Flash Trade coverage

Current Flash Trade integration is intentionally phase-scoped:

- read-only `markets` and `positions` hooks are now wired through the Solana backend and OpenClaw adapter
- the transport is provider-driven, so Flash can be added through `provider-gateway` without introducing a new wallet runtime

Operational notes:

- current agent-facing tools are `get_flash_trade_markets` and `get_flash_trade_positions`
- these reads are mainnet-only
- Flash perpetual opens/closes now follow the existing `preview -> prepare -> execute` approval model instead of a separate trading wallet flow
- Flash reads expect either hosted/self-hosted gateway routes on `PROVIDER_GATEWAY_URL` or a direct `FLASH_API_BASE_URL`
- Phase 2 now also adds `flash_trade_open_position` and `flash_trade_close_position` in `preview` / `prepare` / `execute`
- those preview/prepare/execute flows are produced by a local bridge command configured via `FLASH_SDK_BRIDGE_COMMAND`
- the bridge is expected to return machine JSON on stdout; `agent-wallet/tests/smoke_flash_sdk_bridge.py` documents the minimal contract shape
- a repo-owned Node bridge now lives at `agent-wallet/scripts/flash-sdk-bridge/bridge.mjs`
- install its pinned SDK dependencies with `cd agent-wallet/scripts/flash-sdk-bridge && npm install`
- `FLASH_SDK_BRIDGE_MODE=mock` provides deterministic smoke behavior without SDK dependencies
- `FLASH_SDK_BRIDGE_MODE=real` now produces real Flash SDK quotes for preview and real versioned transaction builds for prepare/execute
- the backend locally verifies the provider-built Flash transaction, applies only the wallet signature, and requires a host-issued approval token before broadcast; tool-level `prepare` still strips signed transaction bytes before returning to the agent
- current real-mode constraints are intentionally narrow: mainnet only, same-collateral `market_symbol == collateral_symbol`, and whole-number leverage strings for opens

## Native staking coverage

Current native Solana staking integration now includes:

- validator discovery via Solana `getVoteAccounts`
- stake account inspection with activation status
- native `stake SOL` flow via the Solana Stake Program
- native stake deactivation
- native stake withdraw

Operational notes:

- this path uses Solana RPC and the Stake Program directly, without third-party DeFi APIs
- stake creation allocates a new stake account controlled by the connected wallet as staker and withdrawer
- preview and prepare were live-checked on devnet against a real wallet context

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

If you want OpenClaw to install the plugin through ClawHub instead of a repo-local path, use:

```bash
openclaw plugins install clawhub:@agentlayertech/agent-wallet-plugin
```

That native plugin package is additive. Keep the existing runtime installer for the actual wallet backend:

```bash
npx @agentlayer.tech/wallet install --yes
```

The ClawHub plugin package auto-checks `~/.openclaw/agent-wallet-runtime/current/agent-wallet` before it falls back to a local workspace checkout.

Public-safe helper scripts are available in `agent-wallet/scripts/`:

- `install_openclaw_local_config.py`
- `finalize_openclaw_local_wallet_config.py`

Both scripts now use generic defaults instead of hardcoded local usernames or paths. Sensitive secrets must be supplied via protected environment variables, not config JSON or CLI arguments.
When `~/.openclaw/agent-wallet-runtime/current` exists, the config installer now prefers that trusted runtime path over a workspace checkout for the plugin manifest, package root, and Python bridge launcher.

Recommended devnet setup:

```bash
AGENT_WALLET_BACKEND=solana_local
AGENT_WALLET_BOOT_KEY=change-this-in-production
SOLANA_NETWORK=devnet
SOLANA_RPC_URLS=https://api.devnet.solana.com
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
- native SOL staking preview, preparation, and execution
- native stake deactivation and withdraw flows
- SPL token transfer preview and execution by mint address
- Jupiter-based swap preview and execution on mainnet
- compact swap `fee_summary` in preview/prepare/execute, including known network fees and route fee bps when Jupiter provides them
- zero-balance token account cleanup
- devnet/testnet faucet airdrop
