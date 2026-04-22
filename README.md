![AgentLayer](logo+name.png)

# AgentLayer

AgentLayer is a beta local-first wallet and finance stack for agents.

The repository includes:

- `agent-wallet/` — the main wallet backend for AgentLayer
- `.openclaw/` — the local AgentLayer bridge layer
- `wdk-btc-wallet/` — the local Bitcoin wallet service
- `provider-gateway/` — shared provider access for Solana RPC, Bags, and Jupiter Earn
- `mcp-server/` — the finance and crypto MCP layer
- `docs/` — the documentation site for onboarding and architecture reference

The goal is simple:

- keep wallet secrets local
- let agents use constrained wallet capabilities
- support real onchain flows without giving agents direct key ownership

## Beta

This project is in beta.

Do not treat it as a finished production wallet stack. Use it carefully, test flows before relying on them, and expect ongoing changes.

## Quick Start

### Bitcoin

Start the local BTC wallet service:

```bash
cd wdk-btc-wallet && sh run-local.sh
```

Then connect it to AgentLayer:

```bash
sh agent-wallet/scripts/setup_btc_wallet.sh
```

That flow will ask for:

- `user-id`
- `mainnet`, `testnet`, or `regtest`
- a local wallet password

If the user ever needs to reveal the seed phrase later:

```bash
sh agent-wallet/scripts/reveal_btc_seed.sh
```

### Solana

Install the wallet backend:

```bash
sh ./setup.sh
```

That installer sets up the OpenClaw wallet plugin runtime in one pass:

- creates the Python environment for [`agent-wallet`](/Users/yuriytsygankov/Documents/openclaw_skill/agent-wallet)
- installs Python dependencies
- installs Node dependencies for [`wdk-btc-wallet`](/Users/yuriytsygankov/Documents/openclaw_skill/wdk-btc-wallet) and [`wdk-evm-wallet`](/Users/yuriytsygankov/Documents/openclaw_skill/wdk-evm-wallet)
- patches local `~/.openclaw/openclaw.json`

It does not yet create or unlock BTC/EVM wallets or auto-start local wallet services.

Then provide local runtime secrets:

```bash
export AGENT_WALLET_BOOT_KEY='...'
export AGENT_WALLET_MASTER_KEY='...'
export AGENT_WALLET_APPROVAL_SECRET='...'
```

You do not need to bring your own RPC just to get started.

The default setup already includes:

- shared Solana RPC through the hosted gateway
- Bags provider access for launch and fees

Bring your own RPC only if you want to override the default path.

## Security Model

The core rule is:

the agent gets wallet capabilities, not wallet ownership.

That means:

- secret material stays local
- signing stays in the wallet layer
- risky writes require approval
- the BTC wallet password and seed phrase are not exposed to the agent

## Notes

- `provider-gateway/` stays non-custodial
- `mcp-server/` is part of the system and provides finance and crypto data access
- the BTC wallet is built as a separate local service on top of Tether WDK

## License and Community Use

This repository is public and source-available under the `PolyForm Small
Business License 1.0.0`.

If you are an individual developer, researcher, student, security reviewer, or
hobbyist, you can comfortably:

- read and audit the code
- fork the repo
- run it locally
- modify it for yourself
- open issues and send pull requests

If you are using the project for a company, the license allows use for small
businesses covered by the PolyForm thresholds. If you need rights beyond that,
you should reach out for a separate commercial license.
