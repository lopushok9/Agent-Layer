![OpenClaw](logo+name.png)

# AgentLayer

AgentLayer is a beta local-first wallet and finance stack for agents.

The repository includes:

- `agent-wallet/` — the main wallet backend for OpenClaw
- `.openclaw/` — the local OpenClaw bridge
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

Then connect it to OpenClaw:

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
cd agent-wallet
python3 scripts/install_agent_wallet.py
```

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
