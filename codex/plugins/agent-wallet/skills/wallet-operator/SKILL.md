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
- Execute only after the user explicitly confirms the shown summary.
- On mainnet, restate the network, asset, amount, and destination before execute.
- Do not ask the user for `approval_token`. The bridge manages approval binding internally.
- If approval context is missing or stale, repeat preview instead of improvising.
- Use `set_wallet_backend` to switch between Solana and EVM wallets within a session, and `set_evm_network` to pick ethereum, base, or robinhood.
- Balance and position answers, on every network (Solana, Ethereum, Base, Robinhood, Arc) and for DeFi positions (Kamino, Morpho, Aave, Lido, Uniswap, staking): show a Markdown table `Asset | Amount | USD` with one row per asset or position, using human amounts (`amount_ui`/`balance_ui`, never raw base units) and `value_usd`, then the network and the total (`total_value_usd`, or the sum of the rows). An asset that has a symbol but no price stays in the table with `—` as its USD value. Hide assets that have neither a symbol nor a USD price (usually spam airdrops) and say how many were hidden. Slash commands that define their own format take precedence.

## Question menus

Use the host's native question menu (`request_user_input_async` or
`request_user_input`) for missing choices only when the tool is exposed and
its current mode and purpose restrictions allow it. Follow that tool's actual
schema; use short options and free text where supported. Otherwise ask in chat
in a format allowed by the host. Reuse choices and amounts the user already
provided; do not ask them again. Do not request keys, passwords, card details
or approval tokens through a question menu.

For a confirmation required by the active workflow, show the same preview and terms, then use a
menu only if the host permits that tool for confirmations; otherwise ask in
chat. Keep the workflow's existing consent rules and confirmation exceptions.
A service/type/amount selection is not payment consent. An async call returning,
a preselected option, an empty answer, cancellation or elapsed time is not
consent: wait for the user's submitted answer before any dependent action.
Question menus do not replace host approval or backend checks or authorize
changed parameters. Keep existing approval scope, expiry, batch/continuation
and retry rules; a menu never expands them. Do not add another confirmation
solely to display a menu. Never switch modes just to open a menu or promise a
keyboard shortcut controlled by the host.
