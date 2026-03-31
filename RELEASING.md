# Releasing

This repository's `v0.1.0-beta.2` public release should be framed around six repo-owned deliverables:

1. `mcp-server/` - the finance and crypto MCP server
2. `agent-wallet/` - the Python wallet backend
3. `.openclaw/extensions/agent-wallet/` - the repo-shipped OpenClaw extension bridge
4. `wdk-btc-wallet/` - the BTC-only wallet service built on Tether WDK
5. `provider-gateway/` - the shared non-custodial provider access layer
6. `docs/` - the Starlight-based documentation site

### Release title

```text
AgentLayer Beta v0.1.0-beta.2
```

### Release body

```md
This is the second public beta release of the OpenClaw finance stack.

This release keeps the original beta foundation and adds three new repo-owned components:

- `mcp-server/` - finance and crypto MCP server
- `agent-wallet/` - Python wallet backend
- `.openclaw/extensions/agent-wallet/` - OpenClaw extension bridge for the wallet backend
- `wdk-btc-wallet/` - BTC-only wallet service for local Bitcoin operations
- `provider-gateway/` - shared provider access for hosted Solana RPC defaults, Bags, and Jupiter Earn
- `docs/` - documentation app for setup, architecture, and capability reference

## Highlights

- Expands the beta stack with a dedicated local BTC wallet service
- Adds a non-custodial shared provider gateway for Solana RPC, Bags, and Jupiter Earn
- Adds a separate documentation app for onboarding and reference material
- Keeps the MCP server, wallet backend, and OpenClaw extension bridge as the core beta foundation

## Included in this release

### New in `v0.1.0-beta.2`

#### `wdk-btc-wallet/`

- Separate BTC-only wallet service built on top of Tether WDK
- Local encrypted wallet vault, localhost-only HTTP surface, and local bearer-token auth
- Covers Bitcoin network selection, wallet lifecycle, balances, transfers, fees, and spendability

#### `provider-gateway/`

- Shared non-custodial provider layer for onboarding-friendly defaults
- Hosted Solana RPC gateway with method allowlist
- Shared Bags launch and fees access plus shared Jupiter Earn relay

#### `docs/`

- Separate Starlight-based documentation app for AgentLayer
- Covers getting started, infrastructure boundaries, wallet architecture, and capabilities
- Gives the beta stack a repo-owned documentation surface for onboarding and review

### Existing beta foundation

#### `mcp-server/`

- MCP server for crypto, DeFi, gas, on-chain, and agent identity workflows
- Structured tools for market data, protocol analytics, and blockchain lookups
- Self-hostable base for OpenClaw or other MCP-compatible clients

#### `agent-wallet/`

- Local Solana wallet backend for OpenClaw-connected agents
- Read, preview, prepare, and approval-gated execute flows
- Local secret handling and explicit operator approval model for risky actions

#### `.openclaw/extensions/agent-wallet/`

- Thin TypeScript bridge from OpenClaw into the Python wallet backend
- Repo-tracked plugin manifest and config schema
- Keeps wallet policy and execution logic in Python while exposing a small operational tool surface to OpenClaw

## Beta notes

- This is a beta release and should not be treated as production-ready custody infrastructure
- Mainnet use should remain cautious, explicit, and operator-controlled
- Early feedback on usability, safety, and integration gaps is expected and welcome
```

## Suggested release note structure

### Highlights

- Expands the stack with `wdk-btc-wallet/`, `provider-gateway/`, and `docs/`
- Keeps `mcp-server/`, `agent-wallet/`, and `.openclaw/extensions/agent-wallet/` as the base beta foundation
- Beta release intended for testing, onboarding, and early adopters

### Included in this release

#### `wdk-btc-wallet/`

- Local BTC wallet service built on Tether WDK
- Wallet lifecycle, balances, fee rates, spendability, and transfer support
- Separate runtime from the existing Solana wallet backend

#### `provider-gateway/`

- Hosted Solana RPC defaults through a shared gateway
- Bags launch and fees provider access
- Jupiter Earn provider access

#### `docs/`

- Separate documentation app for setup and architecture reference
- Covers infrastructure and wallet capability docs
- Repo-owned docs surface for the public beta

#### `mcp-server/`

- MCP server for crypto, DeFi, and on-chain data workflows
- Read-oriented market, protocol, gas, and identity tooling
- Local/self-hostable deployment path

#### `agent-wallet/`

- Local Solana wallet backend for OpenClaw-connected agents
- Read, preview, prepare, and approved execute flows
- Encrypted local secret handling and explicit approval gating for risky actions

#### `.openclaw/extensions/agent-wallet/`

- Thin TypeScript bridge from OpenClaw into the Python wallet backend
- Plugin manifest and config schema tracked in the repo
- Repo-local extension package for OpenClaw integration

### Beta notes

- This is a beta release and should not be presented as production-ready custody infrastructure
- Mainnet usage should remain cautious and operator-controlled
