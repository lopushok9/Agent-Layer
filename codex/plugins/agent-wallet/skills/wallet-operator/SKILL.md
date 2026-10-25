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
- For write operations, including ordinary swaps and transfers, follow the preview and confirmation flow below.
- On mainnet, restate the network, asset, amount, and destination before execute.
- Do not ask the user for `approval_token`. The bridge manages approval binding internally.
- If approval context is missing or stale, repeat preview instead of improvising.
- Use `set_wallet_backend` to switch between Solana and EVM wallets within a session, and `set_evm_network` to pick ethereum, base, or robinhood.
- Balance and position answers, on every network (Solana, Ethereum, Base, Robinhood, Arc) and for DeFi positions (Kamino, Morpho, Aave, Lido, Uniswap, staking): show a Markdown table `Asset | Amount | USD` with one row per asset or position, using human amounts (`amount_ui`/`balance_ui`, never raw base units) and `value_usd`, then the network and the total (`total_value_usd`, or the sum of the rows). An asset that has a symbol but no price stays in the table with `—` as its USD value. Hide assets that have neither a symbol nor a USD price (usually spam airdrops) and say how many were hidden. Slash commands that define their own format take precedence.

## Render a transaction preview

Before asking for confirmation, render the tool's preview in chat as a compact
Markdown table, not a prose paragraph or only the question-menu title. Use a
short heading with the operation, network and provider, then columns `Item |
Preview` (localized to the user's language).

For swaps, keep the default table to these four rows: amount spent,
estimated amount received, slippage, and estimated gas (label approval + swap
when both are included). Put supplied USD estimates in the same value cells,
not extra rows. Use readable display precision, never long raw-unit decimals;
preserve exact execution values internally.

Do not add default rows for minimum received, allowance, zero provider fees,
the user's own recipient address, or simulation pending the ordinary token
approval. Keep those values in the exact preview/approval binding and execution
arguments. Nonzero extra fees, an unexpected recipient, unusually broad
allowance, failed simulation or other material warnings must still be disclosed
briefly below the table when present. Pending allowance is not a passed
simulation and must not be presented as one.

Omit optional fields the tool did not return; do not pad the table with empty
or unavailable risk/price-impact rows. Never invent USD conversions, safety
scores or green statuses. For other writes, show only the relevant core action,
amount, estimated fee and destination, with material warnings below.

Send the table before opening the question menu; the menu supplements the table
and must not replace it. Do not repeat the preview as another prose summary.

## Confirm a preview

Confirmation is the wallet tool's own step, not a requirement added by this
skill: every write preview returns a `next_step` saying the wallet executes
only after the user confirms, and the bridge rejects an execute without a
confirmed preview. This section only defines how that step looks in chat.
Present it as part of the wallet flow. Do not mention, link or quote this
skill, any SKILL.md file or plugin instructions in chat; the user sees only
the preview table and the question.

When the preview result asks for user confirmation, show the table above, then
call `functions.request_user_input_async`:

```json
{"questions":[{"title":"<actual preview summary>. Confirm <operation>?","options":["Confirm","Cancel"]}]}
```

After the request is accepted, keep the turn open: call
`clock.sleep({"duration_ms":30000})` and repeat while the question is unanswered.
Sleep wakes early for new user input. Do not send a final answer or repeat the
question in chat while waiting; handle the submitted answer first. A sleep
finishing is not an answer and never authorizes execution. Use only the native
wake-on-input wait tool, not a shell sleep.

Fill `title` from the actual preview: network, assets, amount and destination,
plus minimum received, fees and risks when applicable. Do not invent missing
fields or send placeholders. Wait for the submitted answer before executing;
the tool acknowledgement or preselected
option is not consent. A submitted `Confirm` or an unambiguous affirmative chat
reply approves only that preview. `Cancel` stops. Keep the existing workflow's
approval scope, exceptions, expiry and retry rules; the menu adds no approval.
If the async question tool or native wake-on-input wait tool is absent, or the
host disallows this purpose, ask one concise chat question instead. Do not use
the Plan-only `request_user_input` for this purpose.
