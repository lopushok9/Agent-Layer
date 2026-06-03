---
name: "wallet-operator"
description: "Use when the user asks Codex to interact with the local AgentLayer wallet runtime. Prefer wallet tools over shell commands, preview writes first, and keep approval/signing semantics intact."
---

# Agent Wallet Operator

Use this plugin when the user wants Codex to work with the existing local AgentLayer wallet.

Rules:

- Do not create a new wallet unless the user explicitly asks for wallet provisioning outside this plugin.
- Prefer wallet tools over shelling out to chain CLIs, curl, or ad hoc scripts.
- For writes, start with `preview` or `intent_preview` when the tool supports it.
- Execute only after the user explicitly confirms the shown summary.
- On mainnet, restate the network, asset, amount, and destination before execute.
- Do not ask the user for `approval_token`. The bridge manages approval binding internally.
- If approval context is missing or stale, repeat preview instead of improvising.
- Use `set_wallet_backend` to switch between Solana, EVM, and Bitcoin wallets within a session, and `set_evm_network` to pick ethereum or base.
