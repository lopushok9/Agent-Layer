---
description: "Use whenever the user's own funds or wallet are involved — balances, portfolio, transfers, swaps, bridging, staking, lending, or x402 payments — even if the user never says \"wallet\". Trigger phrases include \"my balance\", \"how much SOL/ETH/BTC/USDC do I have\", \"send/transfer X to\", \"swap\", \"bridge\", \"stake\", \"my portfolio\", \"pay for this API\", \"x402\". Prefer agent-wallet MCP tools over shell commands, raw RPC, or crypto data servers. Preview writes first and execute only after explicit user confirmation."
user-invocable: false
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
- Use `set_wallet_backend` to switch between Solana and EVM wallets within a session.
- Balance and position answers, on every network (Solana, Ethereum, Base, Robinhood, Arc) and for DeFi positions (Kamino, Morpho, Aave, Lido, Uniswap, staking): show a Markdown table `Asset | Amount | USD` with one row per asset or position, using human amounts (`amount_ui`/`balance_ui`, never raw base units) and `value_usd`, then the network and the total (`total_value_usd`, or the sum of the rows). An asset that has a symbol but no price stays in the table with `—` as its USD value. Hide assets that have neither a symbol nor a USD price (usually spam airdrops) and say how many were hidden. Slash commands that define their own format take precedence.
