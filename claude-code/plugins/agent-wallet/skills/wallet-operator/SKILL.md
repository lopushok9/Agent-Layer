---
description: "Use when the user asks Claude Code to interact with the local AgentLayer wallet runtime: check balances, transfer tokens, swap, DeFi operations, or x402 payments. Prefer wallet tools over shell commands. Preview writes first and execute only after explicit user confirmation."
---

# Agent Wallet Operator

Use this skill when the user wants Claude Code to work with the existing local AgentLayer wallet.

Rules:

- Do not create a new wallet unless the user explicitly requests wallet provisioning.
- Prefer wallet tools over shelling out to chain CLIs, curl, or ad hoc scripts.
- For writes, start with `preview` or `intent_preview` when the tool supports it.
- Execute only after the user explicitly confirms the shown summary.
- On mainnet, restate the network, asset, amount, and destination before execute.
- Do not ask the user for `approval_token`. The bridge manages approval binding internally.
- If approval context is missing or stale, repeat preview instead of improvising.
- Use `set_wallet_backend` to switch between Solana, EVM, and Bitcoin wallets within a session.
