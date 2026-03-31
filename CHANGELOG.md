# Changelog

## Unreleased

- No unreleased changes recorded yet.

## v0.1.0-beta.2 - 2026-03-31

Second public beta release that expands the stack beyond the initial MCP, wallet, and OpenClaw bridge scope.

### Added

- `wdk-btc-wallet/`: separate BTC-only wallet service built on top of Tether WDK for local Bitcoin wallet operations.
- `provider-gateway/`: non-custodial shared provider access layer for hosted Solana RPC defaults, Bags launch and fees, and Jupiter Earn.
- `docs/`: Starlight-based documentation app for AgentLayer onboarding, architecture, and capability docs.

### Notes

- `mcp-server/`, `agent-wallet/`, and `.openclaw/extensions/agent-wallet/` remain part of the beta stack from `v0.1.0-beta.1`.
- This is still a beta release intended for testing, onboarding, and early integration work.
- Mainnet use should remain explicit, operator-approved, and cautious.

## v0.1.0-beta.1 - 2026-03-21

First public beta centered on the repo's three primary deliverables: `mcp-server`, `agent-wallet`, and `.openclaw/extensions/agent-wallet`.

### Added

- `mcp-server/`: finance and crypto MCP server with market, DeFi, on-chain, and agent identity tooling.
- `agent-wallet/`: Python wallet backend for local Solana wallet operations with guarded read, preview, prepare, and execute flows.
- `.openclaw/extensions/agent-wallet/`: repo-shipped OpenClaw extension bridge that forwards tool execution into the Python wallet backend.

### Notes

- This is a beta release intended for testing and early integration work.
- Mainnet use should remain explicit, operator-approved, and cautious.
