# Agent Wallet Claude Code Plugin

This plugin adds the existing local AgentLayer wallet runtime to Claude Code.

It does not create a new wallet. It reuses the current runtime under:

```bash
~/.openclaw/agent-wallet-runtime/current/agent-wallet
```

Primary design rules:

- keep wallet policy, approvals, and signing in `agent-wallet/`
- keep this plugin as a thin MCP bridge for Claude Code
- reuse the same wallets, networks, and tool surface already used by OpenClaw, Hermes, and Codex
- avoid secrets in plugin config or marketplace metadata

## What it exposes

- direct wallet tools for Solana, Bitcoin, and EVM (same surface as OpenClaw and Codex)
- session wallet selection with `set_wallet_backend`
- EVM network selection with `set_evm_network`
- auto-managed approval binding for `preview -> execute` write flows

## Runtime requirements

- install the AgentLayer runtime first with `npx @agentlayer.tech/wallet install --yes`
- keep the local wallet files and `~/.openclaw/sealed_keys.json` in place
- run `npx @agentlayer.tech/wallet claude-code install --yes` to register this plugin

## Installation

### Automated (recommended)

```bash
npx @agentlayer.tech/wallet install --yes
npx @agentlayer.tech/wallet claude-code install --yes
```

### Manual

```bash
# Load for a single session (dev / testing)
claude --plugin-dir /path/to/claude-code/plugins/agent-wallet

# Or install permanently via Claude Code:
# 1. Open Claude Code
# 2. Run /plugin and point it at this directory
```

## Path resolution

The bridge resolves the wallet runtime from:

1. `AGENT_WALLET_PACKAGE_ROOT`
2. `OPENCLAW_AGENT_WALLET_PACKAGE_ROOT`
3. `~/.openclaw/agent-wallet-runtime/current/agent-wallet`

If the runtime lives elsewhere, set one of the env overrides before starting Claude Code.

## MCP server

The plugin launches an MCP server via `scripts/run_mcp.sh`, which runs the same
`server.py` FastMCP bridge used by the Codex plugin. `${CLAUDE_PLUGIN_ROOT}` is
substituted by Claude Code at plugin load time.
