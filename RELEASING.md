# Releasing

This repository's public release should be framed around three repo-owned deliverables:

1. `mcp-server/` - the finance and crypto MCP server
2. `agent-wallet/` - the Python wallet backend
3. `.openclaw/extensions/agent-wallet/` - the repo-shipped OpenClaw extension bridge

### Release title

```text
AgentLayer Beta v0.1.0-beta.1
```

### Release body

```md
This is the first public beta release of the OpenClaw finance stack.

This release is centered on three repository-owned components:

- `mcp-server/` - finance and crypto MCP server
- `agent-wallet/` - Python wallet backend
- `.openclaw/extensions/agent-wallet/` - OpenClaw extension bridge for the wallet backend

## Highlights

- First public beta of the OpenClaw finance stack
- Ships the MCP server, wallet backend, and OpenClaw extension bridge together
- Designed for local or self-hosted use, testing, and early integrations

## Included in this release

### `mcp-server/`

- MCP server for crypto, DeFi, gas, on-chain, and agent identity workflows
- Structured tools for market data, protocol analytics, and blockchain lookups
- Self-hostable base for OpenClaw or other MCP-compatible clients

### `agent-wallet/`

- Local Solana wallet backend for OpenClaw-connected agents
- Read, preview, prepare, and approval-gated execute flows
- Local secret handling and explicit operator approval model for risky actions

### `.openclaw/extensions/agent-wallet/`

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

- First public beta of the OpenClaw finance stack
- Ships the MCP server, wallet backend, and OpenClaw extension bridge together
- Beta release intended for testing and early adopters

### Included in this release

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
