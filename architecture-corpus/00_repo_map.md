# OpenClaw Finance Stack Repo Map

This repository is a local-first finance and wallet stack for agents.

The top-level architecture has six primary product surfaces:

- `agent-wallet` is the authoritative wallet backend and policy layer.
- `wdk-btc-wallet` is a separate localhost-only Bitcoin wallet runtime.
- `wdk-evm-wallet` is a separate localhost-only EVM wallet runtime.
- `provider-gateway` is the shared provider and RPC relay layer.
- `mcp-server` is the read-oriented crypto MCP server for agents.
- `.openclaw` and `hermes/plugins/agent_wallet` are host bridges for different agent runtimes.

Supporting delivery surfaces:

- `agent-a2a-gateway` exposes A2A-style HTTP endpoints and forwards prompts to OpenClaw.
- `landing` is the marketing and documentation site.
- `solana-8004` is a focused Solana agent registration utility for ERC-8004 style publishing.

Core architectural rule:

- signing and approval stay local in `agent-wallet`, `wdk-btc-wallet`, and `wdk-evm-wallet`
- shared provider access stays in `provider-gateway`
- read-only cross-chain analytics stay in `mcp-server`
- host/plugin UX stays in `.openclaw` and Hermes plugin bridges

Primary runtime flow:

1. OpenClaw or Hermes exposes tools to the agent.
2. Tool calls go through a thin plugin bridge.
3. The bridge forwards into `agent-wallet`.
4. `agent-wallet` selects the active backend: Solana local, BTC local, or EVM local.
5. Wallet reads and writes use direct RPC or the shared `provider-gateway` depending on mode.
6. Analytics and discovery use the separate `mcp-server`.

Presentation communities:

- Wallet policy and execution
- Network-specific wallet runtimes
- Shared provider infrastructure
- Agent-facing MCP and discovery
- Host plugins and bridges
- Public delivery and registration surfaces
