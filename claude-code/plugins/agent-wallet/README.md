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

### From inside Claude Code (no terminal needed)

The plugin ships in a git marketplace at the repo root, so you can install it —
and its backend runtime — without leaving the CLI. Two commands, then restart:

```text
/plugin marketplace add lopushok9/Agent-Layer
/plugin install agent-wallet@agentlayer
```

Restart Claude Code (or `/reload-plugins`). On the next session start a
`SessionStart` hook runs `scripts/bootstrap_backend.sh`, a thin bridge to the
npm installer (`npx @agentlayer.tech/wallet install --yes`). The marketplace only
copies this MCP bridge into Claude Code's cache; the bootstrap step lays down the
Python backend runtime (venv + `agent_wallet` + `server.py`) that the bridge
talks to, with the wallet configured out of the box. It is idempotent and a
no-op once the backend is healthy.

- `/wallet-setup` — install (or repair) the backend explicitly instead of
  waiting for the hook (requires `/reload-plugins` first so the command is
  registered).
- `AGENT_WALLET_AUTO_BOOTSTRAP=0` — opt out of the auto-install: the
  `SessionStart` hook then only reminds you to run `/wallet-setup` instead of
  installing the backend itself.

For near-zero typed commands, pre-register the marketplace in
`.claude/settings.json` with `extraKnownMarketplaces` + `enabledPlugins` so
Claude Code prompts to install on trust.

### Automated via npm

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
