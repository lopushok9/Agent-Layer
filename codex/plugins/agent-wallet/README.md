# Agent Wallet Codex Plugin

This plugin adds the existing local AgentLayer wallet runtime to Codex.

It does not create a new wallet. It reuses the current runtime under:

```bash
~/.openclaw/agent-wallet-runtime/current/agent-wallet
```

Primary design rules:

- keep wallet policy, approvals, and signing in `agent-wallet/`
- keep this plugin as a thin MCP bridge for Codex
- reuse the same wallets, networks, and tool surface already used by OpenClaw and Hermes
- avoid secrets in plugin config or marketplace metadata

## What it exposes

- direct wallet tools for Solana, Bitcoin, and EVM
- session wallet selection with `set_wallet_backend`
- EVM network selection with `set_evm_network`
- auto-managed approval binding for `preview -> execute` write flows
- bundled Codex skills, including `wallet-sol` for showing the Solana wallet
  portfolio directly in chat and `wallet-base` for showing the Base EVM
  wallet portfolio and switching the session's active backend to Base

## Runtime requirements

- install the AgentLayer runtime first with `npx @agentlayer.tech/wallet install --yes`
- keep the local wallet files and `~/.openclaw/sealed_keys.json` in place
- use `wallet codex install --yes` to install this plugin into Codex

## Bundled skills

After `wallet codex install --yes` and a Codex restart, the plugin ships
bundled skills:

- `wallet-sol` — invoke from the slash menu or explicitly as `$wallet-sol`
  to render the connected Solana wallet portfolio as a compact chat table.
- `wallet-base` — invoke from the slash menu or explicitly as `$wallet-base`
  to render the connected Base EVM wallet portfolio as a compact chat table
  and switch the session's active wallet backend to Base.

## Path resolution

The bridge resolves the wallet runtime from:

1. `AGENT_WALLET_PACKAGE_ROOT`
2. `OPENCLAW_AGENT_WALLET_PACKAGE_ROOT`
3. `~/.openclaw/agent-wallet-runtime/current/agent-wallet`

If the runtime lives elsewhere, set one of the env overrides before starting Codex.
