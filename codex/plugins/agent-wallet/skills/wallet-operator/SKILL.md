---
name: "wallet-operator"
description: "Use whenever the user's own funds or wallet are involved — balances, portfolio, transfers, swaps, bridging, staking, lending, or x402 payments — even if the user never says \"wallet\". Trigger phrases include \"my balance\", \"how much SOL/ETH/BTC/USDC do I have\", \"send/transfer X to\", \"swap\", \"bridge\", \"stake\", \"my portfolio\". Prefer wallet tools over shell commands, preview writes first, and keep approval/signing semantics intact."
---

# Agent Wallet Operator

Use this plugin when the user wants Codex to work with the existing local AgentLayer wallet.

Rules:

- Do not create a new wallet unless the user explicitly asks for wallet provisioning outside this plugin.
- Prefer wallet tools over shelling out to chain CLIs, curl, or ad hoc scripts.
- For writes, start with `preview` or `intent_preview` when the tool supports it.
- Execute only after the user explicitly confirms the shown summary. For ordinary requests, including swaps and transfers, use the confirmation call below.
- On mainnet, restate the network, asset, amount, and destination before execute.
- Do not ask the user for `approval_token`. The bridge manages approval binding internally.
- If approval context is missing or stale, repeat preview instead of improvising.
- Use `set_wallet_backend` to switch between Solana and EVM wallets within a session, and `set_evm_network` to pick ethereum, base, or robinhood.
- Balance and position answers, on every network (Solana, Ethereum, Base, Robinhood, Arc) and for DeFi positions (Kamino, Morpho, Aave, Lido, Uniswap, staking): show a Markdown table `Asset | Amount | USD` with one row per asset or position, using human amounts (`amount_ui`/`balance_ui`, never raw base units) and `value_usd`, then the network and the total (`total_value_usd`, or the sum of the rows). An asset that has a symbol but no price stays in the table with `—` as its USD value. Hide assets that have neither a symbol nor a USD price (usually spam airdrops) and say how many were hidden. Slash commands that define their own format take precedence.

## Confirm a preview

When the workflow requires user confirmation, show the actual preview, then
call `functions.request_user_input_async`:

```json
{"questions":[{"title":"<actual preview summary>. Confirm <operation>?","options":["Confirm","Cancel"]}]}
```

Fill `title` from the actual preview: network, assets, amount and destination,
plus minimum received, fees and risks when applicable. Do not invent missing
fields or send placeholders. Wait for the submitted answer before executing;
the tool acknowledgement or preselected
option is not consent. A submitted `Confirm` or an unambiguous affirmative chat
reply approves only that preview. `Cancel` stops. Keep the existing workflow's
approval scope, exceptions, expiry and retry rules; the menu adds no approval.
If this async tool is absent or disallows confirmations, ask one concise chat
question. Do not use the Plan-only `request_user_input` for this purpose.
