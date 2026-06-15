![AgentLayer](logo+name.png)


[![npm version](https://img.shields.io/npm/v/%40agentlayer.tech%2Fwallet)](https://www.npmjs.com/package/@agentlayer.tech/wallet)
[![npm downloads](https://img.shields.io/npm/dm/%40agentlayer.tech%2Fwallet)](https://www.npmjs.com/package/@agentlayer.tech/wallet)
[![Node 24.x](https://img.shields.io/badge/node-24.x-339933?logo=node.js&logoColor=white)](https://nodejs.org/)
[![docs](https://img.shields.io/badge/docs-agent--layer.tech-blue)](https://docs.agent-layer.tech/)

For Openclaw:

```bash
npx @agentlayer.tech/wallet install --yes
```

For Codex:

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet codex install --yes
```

For Claude Code:

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet claude-code install --yes
```

Or install entirely from inside the Claude Code CLI, via the plugin marketplace
(no terminal/npx needed) — two commands, then restart:

```text
/plugin marketplace add lopushok9/Agent-Layer
/plugin install agent-wallet@agentlayer
```

For Hermes:

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet hermes install --yes
```


AgentLayer is a beta local-first wallet and finance stack for agents.

The repository includes:

- `agent-wallet/` - the main wallet backend for AgentLayer
- `.openclaw/` - the local AgentLayer bridge layer for the OpenClaw wallet integration
- `hermes/` - optional Hermes Agent plugin bridge for the same wallet backend
- `codex/` - optional Codex plugin bridge for the same wallet backend
- `wdk-btc-wallet/` - the local Bitcoin wallet service
- `wdk-evm-wallet/` - the local EVM wallet service
- `provider-gateway/` - shared provider access for Solana RPC, Bags, and related finance reads
- `mcp-server/` - the finance and crypto MCP layer

The goal is simple:

- keep wallet secrets local
- let agents use constrained wallet capabilities
- support real onchain flows without giving agents direct key ownership

## Beta

This project is in beta.

Do not treat it as a finished production wallet stack. Test every flow before relying on it.

## Quick install

System prerequisites:

- `python3`
- `node` `24.x`
- `npm`

Install the local runtime:

```bash
npx @agentlayer.tech/wallet install --yes
```

Install the native OpenClaw plugin from ClawHub:

```bash
openclaw plugins install clawhub:@agentlayertech/agent-wallet-plugin
```

The ClawHub package does not replace the npm installer. `npx @agentlayer.tech/wallet install --yes` installs the local runtime, Python backend, and helper services. ClawHub only installs the OpenClaw plugin surface that points at that runtime.

Or install the CLI globally:

```bash
npm install -g @agentlayer.tech/wallet
wallet install --yes
```

The CLI uses a versioned runtime layout:

```bash
~/.openclaw/agent-wallet-runtime/releases/<version>
~/.openclaw/agent-wallet-runtime/current
```

On first install, `--yes` generates local runtime secrets. The installer stores `master_key` and `approval_secret` in `~/.openclaw/sealed_keys.json`; only the boot key needed to unlock that sealed bundle is written to the runtime `.env`.

Useful npm CLI commands:

```bash
wallet status
wallet doctor
wallet hermes install --yes
wallet codex install --yes
wallet update --yes
wallet update --yes --dry-run
wallet rollback
```

`wallet update --yes` delegates to the latest published npm package and reuses shared Python and Node dependency snapshots when possible. Use `wallet update --yes --dry-run` to inspect the target version and dependency plan before switching `current`.

## Native OpenClaw plugin installs

Use ClawHub when you want the plugin installed through OpenClaw:

```bash
openclaw plugins install clawhub:@agentlayertech/agent-wallet-plugin
```

Recommended order:

1. Install or update the local runtime with `npx @agentlayer.tech/wallet install --yes`.
2. Install the plugin package from ClawHub with `openclaw plugins install clawhub:...`.
3. Restart the OpenClaw gateway and enable/configure the plugin entry in `openclaw.json`.

The `agent-wallet` ClawHub plugin checks the standard runtime path at:

```bash
~/.openclaw/agent-wallet-runtime/current/agent-wallet
```

If your runtime lives elsewhere, set `plugins.entries.agent-wallet.config.packageRoot` explicitly.

Install from a local clone:

```bash
sh ./setup.sh
```

## Updating

If your installed CLI is `0.1.22` or newer, use:

```bash
wallet update --yes --dry-run
wallet update --yes
```

If your installed CLI is older than `0.1.22`, or `wallet` is missing, use:

```bash
npx --yes @agentlayer.tech/wallet@latest update --yes --dry-run
npx --yes @agentlayer.tech/wallet@latest update --yes
```

After updating, verify the active runtime:

```bash
npx --yes @agentlayer.tech/wallet@latest status --verbose
```

This flow keeps wallet files and `sealed_keys.json` in place, upgrades the runtime under `~/.openclaw/agent-wallet-runtime/releases/<version>`, and reuses shared Python and Node dependency snapshots when possible.


## Wallet capabilities through external services

AgentLayer keeps keys, approvals, and signing local, but the wallet can still operate through a set of registered provider-backed tools. These tools are exposed through the OpenClaw wallet plugin as explicit service integrations rather than raw shell access, config editing, or backend switching.

### x402 paid APIs

The x402 bundle turns the wallet into a buyer for metered APIs and paid HTTP endpoints:

- `x402_search_services` - search x402-paid services through discovery providers such as CDP Bazaar and Agentic Market without spending funds.
- `x402_get_service_details` - resolve one discovered service or resource into a normalized detail payload before attempting payment.
- `x402_preview_request` - make an unpaid request, detect `402 Payment Required`, and summarize payment terms and supported payment options.
- `x402_pay_request` - prepare or execute the paid retry through the active wallet backend. The current flow executes the Solana exact-buyer path and keeps EVM as prepare-only.

This gives the wallet a direct bridge from service discovery to paid API consumption while preserving approval-token checks before execution.

### LI.FI cross-chain routing

The LI.FI bundle covers discovery, quote inspection, transfer tracking, and routed execution across Solana, Ethereum, and Base:

- `get_lifi_supported_chains` - list the chains currently allowed for LI.FI routing in the wallet surface.
- `get_lifi_quote` - fetch a read-only cross-chain quote before any execution planning.
- `get_lifi_transfer_status` - inspect a routed transfer by transaction hash or LI.FI step id.
- `swap_solana_lifi_cross_chain_tokens` - preview, prepare, or execute a Solana-origin cross-chain route into Ethereum or Base.
- `swap_evm_lifi_cross_chain_tokens` - preview, prepare, or execute an EVM-origin cross-chain route across Ethereum, Base, and Solana when LI.FI returns a route.

### Jupiter trading and yield

On Solana, Jupiter-backed tools cover market pricing, swaps, and Jupiter Earn vault flows:

- `get_solana_token_prices` - fetch current Solana token pricing through Jupiter.
- `swap_solana_tokens` - preview, prepare, or execute a Jupiter-routed Solana token swap.
- `get_jupiter_earn_tokens` - list Jupiter Earn vault assets currently supported on mainnet.
- `get_jupiter_earn_positions` - inspect wallet positions in Jupiter Earn vaults.
- `get_jupiter_earn_earnings` - fetch earnings for one or more Jupiter Earn positions.
- `jupiter_earn_deposit` - preview, prepare, or execute a Jupiter Earn deposit.
- `jupiter_earn_withdraw` - preview, prepare, or execute a Jupiter Earn withdrawal.

### Houdini private payouts

For privacy-preserving Solana payout flows, the wallet exposes a Houdini-backed bundle:

- `swap_solana_privately` - create a preview or approved private payout through Houdini routing. The current MVP supports same-token flows such as `SOL -> SOL` and `USDC -> USDC`.
- `continue_solana_private_swap` - continue a previously created Houdini order and submit the local funding transfer to the returned deposit address.
- `get_solana_private_swap_status` - check Houdini status for an existing private payout.
- `list_pending_solana_private_swaps` - list cached pending Houdini orders for the current OpenClaw session.

This flow is intentionally optimized for `preview -> execute` rather than adding a no-op prepare step.

### Kamino lending

Kamino integration gives the wallet a structured Solana lending surface:

- `get_kamino_lend_markets` - list Kamino lending markets available on Solana mainnet.
- `get_kamino_lend_market_reserves` - inspect reserve metrics for one Kamino market.
- `get_kamino_lend_user_obligations` - inspect the wallet's obligations inside a Kamino market.
- `get_kamino_lend_user_rewards` - fetch the wallet's Kamino rewards summary.
- `get_kamino_open_positions` - aggregate all open Kamino positions across markets with loan details, reserve APYs, and rewards.
- `kamino_lend_deposit` - preview, prepare, or execute a lending deposit.
- `kamino_lend_withdraw` - preview, prepare, or execute a lending withdrawal.
- `kamino_lend_borrow` - preview, prepare, or execute a borrow.
- `kamino_lend_repay` - preview, prepare, or execute a repay.

### Flash Trade perps

Flash Trade integration adds a managed perpetuals surface on Solana mainnet:

- `get_flash_trade_markets` - list currently available Flash Trade markets.
- `get_flash_trade_positions` - inspect the wallet's open Flash Trade positions.
- `flash_trade_open_position` - preview, prepare, or execute a perp position open.
- `flash_trade_close_position` - preview, prepare, or execute a perp position close.

### Bags launch

Bags-backed tools currently cover token launch:

- `launch_bags_token` - preview, prepare, or execute a Bags token launch with fee-share configuration.

### EVM DeFi integrations

The EVM wallet surface includes named DeFi integrations on `ethereum` and `base`, without exposing arbitrary calldata execution.

Velora swap routing:

- `get_evm_swap_quote` - fetch a read-only EVM swap quote.
- `swap_evm_tokens` - preview, prepare, or execute a routed EVM token swap.

Aave V3:

- `get_evm_aave_account` - inspect the wallet's Aave account state.
- `get_evm_aave_reserves` - fetch reserve data for supported Aave markets.
- `get_evm_aave_positions` - inspect the wallet's open Aave positions.
- `manage_evm_aave_position` - preview, prepare, or execute Aave position changes through the managed wallet flow.

Lido:

- `get_evm_lido_overview` - fetch Lido protocol overview data relevant to the wallet surface.
- `get_evm_lido_positions` - inspect the wallet's Lido positions.
- `get_evm_lido_withdrawal_requests` - inspect outstanding Lido withdrawal requests.
- `manage_evm_lido_position` - preview, prepare, or execute a Lido staking position change.
- `manage_evm_lido_withdrawal` - preview, prepare, or execute a Lido withdrawal management action.

Across these service-backed flows, read operations remain directly callable, while write operations stay behind preview, explicit intent, and host-issued approval tokens before execution.

For the default Solana flow, run the installer directly:

```bash
npx @agentlayer.tech/wallet install --yes
```

That installs the runtime, patches the OpenClaw plugin config, generates local
runtime secrets when missing, and creates the first encrypted per-user Solana
mainnet wallet. The agent receives the public address and guarded wallet tools,
not the private key.

BTC and EVM are separate host-side setup flows.

Bitcoin:

```bash
sh agent-wallet/scripts/setup_btc_wallet.sh
```

EVM:

```bash
sh agent-wallet/scripts/setup_evm_wallet.sh
```

That host-side bootstrap can auto-start the local `wdk-evm-wallet` service, create or unlock the vault wallet, bind both `base` and `ethereum` for the same local user, and patch OpenClaw config to `backend=wdk_evm_local`.

Advanced operators can still supply their own runtime provisioning secrets
instead of using `--yes` auto-generation:

```bash
export AGENT_WALLET_BOOT_KEY="$(openssl rand -base64 32)"
export AGENT_WALLET_MASTER_KEY="$(openssl rand -base64 32)"
export AGENT_WALLET_APPROVAL_SECRET="$(openssl rand -base64 32)"
npx @agentlayer.tech/wallet install --no-auto-secrets
```

If you prefer Python instead of `openssl`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run it three times and assign the outputs to:

- `AGENT_WALLET_BOOT_KEY`
- `AGENT_WALLET_MASTER_KEY`
- `AGENT_WALLET_APPROVAL_SECRET`

These variables are provisioning inputs only. Runtime secrets are sealed into
`~/.openclaw/sealed_keys.json`; normal runtime execution should use
`AGENT_WALLET_BOOT_KEY` or `AGENT_WALLET_BOOT_KEY_FILE`, not direct
`AGENT_WALLET_MASTER_KEY` / `AGENT_WALLET_APPROVAL_SECRET` env loading.

## Connect the MCP server

```json
{
  "mcpServers": {
    "agent-layer": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}
```

## Connect Hermes Agent

OpenClaw remains the primary local environment, but the repo also ships an optional Hermes Agent bridge at:

```bash
hermes/plugins/agent_wallet
```

It exposes a thin bridge, not a separate wallet implementation:

- `agent_wallet_tools`
- `agent_wallet_invoke`
- `agent_wallet_approve`
- `agent_wallet_evm_status`
- `agent_wallet_evm_setup`

Install it by symlinking the plugin directory into Hermes:

```bash
npx @agentlayer.tech/wallet hermes install --yes
```

That command installs the Hermes plugin, runs `hermes plugins enable agent-wallet`, writes non-secret runtime paths into `~/.hermes/.env`, and points Hermes at a local boot-key file. Secrets stay in the protected OpenClaw runtime paths, especially `~/.openclaw/sealed_keys.json`; do not put wallet secrets into Hermes tool config.

## What you get after install

If you install through npm, the runtime is extracted under:

```bash
~/.openclaw/agent-wallet-runtime/current
```

The installer then:

- creates `agent-wallet/.env` from `agent-wallet/.env.example` if it does not exist
- creates `agent-wallet/.runtime-venv` and installs the Python backend
- installs Node dependencies for `wdk-btc-wallet`, `wdk-evm-wallet`, and `flash-sdk-bridge`
- creates a minimal `~/.openclaw/openclaw.json` if one does not exist
- if the required secrets are already present, writes or updates `~/.openclaw/sealed_keys.json`
- if the required secrets are already present, patches `~/.openclaw/openclaw.json` to load the `agent-wallet` extension and point it at the installed runtime
- `wallet hermes install --yes` additionally connects Hermes Agent to the same runtime without copying wallet tools or policy

When the installer reaches the final config step, the default plugin config is:

- `backend=solana_local`
- `network=mainnet`

For a fresh Solana install, `wallet install --yes` also provisions the first local mainnet
wallet for the configured local `userId`. The wallet secret stays encrypted under
`~/.openclaw/users/.../wallets/`; the agent-facing surface only receives the public
address and guarded wallet tools.

## What is not done automatically

The installer does not:

- create a BTC wallet
- unlock a BTC wallet
- create an EVM wallet
- unlock an EVM wallet
- start the local `wdk-btc-wallet` service
- start the local `wdk-evm-wallet` service
- expose seed phrases to the agent
- install `python3`, `node`, or `npm` for you

For existing Solana installs, the runtime keeps the current identity precedence:

- read-only mode: `SOLANA_AGENT_PUBLIC_KEY`
- signing mode: a sealed `private_key` or `SOLANA_AGENT_KEYPAIR_PATH`
- otherwise: the encrypted per-user local wallet created by onboarding

Optional private Solana payout routing is also available through Houdini. To enable it, add the Houdini partner credentials to the wallet runtime:

- `HOUDINI_API_KEY`
- `HOUDINI_API_SECRET`
- `HOUDINI_USER_IP`

The first supported flow is intentionally narrow: same-token private Solana payouts (`SOL->SOL` and `USDC->USDC`) through the existing preview/prepare/execute safety model. The runtime binds execute to the approved Houdini `quoteId`, creates a single private exchange, and then sends the exact deposit locally from the wallet. That removes the extra Solana batch-tx relay step and keeps signing local.

For production, prefer placing the Houdini partner secrets on `provider-gateway` and exposing only the authenticated Houdini relay endpoints to `agent-wallet`. That keeps `HOUDINI_API_KEY` and `HOUDINI_API_SECRET` out of end-user runtimes while preserving local signing.

## BTC setup

The BTC path already has a one-command host bootstrap wrapper:

```bash
sh agent-wallet/scripts/setup_btc_wallet.sh
```

That flow:

- prompts for `user-id`
- prompts for `mainnet`, `testnet`, or `regtest`
- defaults to `http://127.0.0.1:8080`
- can auto-start `wdk-btc-wallet/run-local.sh` if the local service is not already healthy
- creates or unlocks the local BTC wallet binding
- patches OpenClaw config to `backend=wdk_btc_local`

BTC setup only supports localhost service URLs. The local BTC service is protected by a bearer token stored at:

```bash
~/.openclaw/wdk-btc-wallet/local-auth-token
```

If you need to reveal the BTC seed phrase later, that remains a host-side step:

```bash
sh agent-wallet/scripts/reveal_btc_seed.sh
```

## EVM setup

The EVM runtime is installed by `setup.sh`, and the host-side onboarding now has the same one-command shape as BTC:

```bash
sh agent-wallet/scripts/setup_evm_wallet.sh
```

That flow:

- prompts for `user-id`
- prompts for `ethereum`, `base`, `sepolia`, or `base-sepolia`
- defaults to `http://127.0.0.1:8081`
- can auto-start `wdk-evm-wallet/run-local.sh` if the local service is not already healthy
- creates or unlocks the local EVM wallet binding
- also binds the paired EVM network by default: `ethereum <-> base`, `sepolia <-> base-sepolia`
- patches OpenClaw config to `backend=wdk_evm_local`

You can still use the lower-level CLI if needed:

```bash
printf '%s\n' 'your-local-evm-password' | \
agent-wallet/.venv/bin/python -m agent_wallet.openclaw_cli evm-wallet-create \
  --user-id your-user-id \
  --password-stdin \
  --config-json '{"backend":"wdk_evm_local","network":"base","wdkEvmServiceUrl":"http://127.0.0.1:8081"}'
```

Important EVM notes:

- only localhost service URLs are supported for the OpenClaw EVM flow
- the local EVM service uses a bearer token at `~/.openclaw/wdk-evm-wallet/local-auth-token`
- the agent-facing EVM surface is intentionally narrow: balances, fee rates, receipts, transfers, Velora swaps, Aave V3 account/reserve/position flows, and Lido staking/withdrawal flows
- Velora swap and Aave V3 support are currently limited to `ethereum` and `base`
- Lido support is currently limited to `ethereum` and exposes read-only staking APR data from Lido's public API in the overview response

## Solana notes

The installer defaults the plugin to `solana_local` on `devnet`.

The Solana runtime uses hardened local secrets:

- `AGENT_WALLET_BOOT_KEY` is required by the runtime
- `master_key` and `approval_secret` should live in `~/.openclaw/sealed_keys.json`
- `AGENT_WALLET_MASTER_KEY` and `AGENT_WALLET_APPROVAL_SECRET` are provisioning inputs for installer/admin flows, not long-term runtime env

Read-only Solana mode:

```bash
export SOLANA_AGENT_PUBLIC_KEY='...'
```

Signing Solana mode can use either:

- a sealed `private_key` stored in `sealed_keys.json`
- `SOLANA_AGENT_KEYPAIR_PATH`

The default shared path already includes:

- hosted provider-gateway defaults
- shared Solana RPC path unless you override it

You only need to bring your own RPC if you want to override the default route. Supported override paths are:

- `SOLANA_RPC_URL`
- `SOLANA_RPC_URLS`
- `ALCHEMY_API_KEY`
- `HELIUS_API_KEY`

The legacy global keypair auto-create flag still exists for compatibility, but normal
OpenClaw onboarding should use the encrypted per-user wallet path created by the installer:

```bash
SOLANA_AUTO_CREATE_WALLET=false
```

## Security model

The core rule is:

the agent gets wallet capabilities, not wallet ownership.

That means:

- secret material stays local
- signing stays in the wallet layer
- risky writes require approval
- BTC and EVM password-gated wallet operations remain host-side

## License and community use

This repository is public and source-available under the `PolyForm Small Business License 1.0.0`.

If you are an individual developer, researcher, student, security reviewer, or hobbyist, you can:

- read and audit the code
- fork the repo
- run it locally
- modify it for yourself
- open issues and send pull requests

If you are using the project for a company, the license allows use for small businesses covered by the PolyForm thresholds. If you need rights beyond that, reach out for a separate commercial license.
