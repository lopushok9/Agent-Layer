---
name: "wallet-base"
description: "Show the current Base EVM wallet portfolio from the local AgentLayer wallet and switch the session's active wallet backend to Base. Use when the user asks for /wallet-base or wants their Base wallet shown directly in chat."
---

# Base EVM Wallet Portfolio

Use the local AgentLayer wallet MCP tools only.

Workflow:

1. Call `get_wallet_overview` with `backend=evm, network=base` and
   `set_wallet_backend` with `backend=base, network=base` — they are
   independent, so issue both in the same turn rather than sequentially.
2. Render the `get_wallet_overview` result directly in chat in this shape:
   - title: `EVM (Base) Wallet Portfolio`
   - bullets for `Chain`, `Network` (or `requested_network` when `network`
     is absent), `Address`, and `Total Value (USD)` when available
   - one compact Markdown table with columns: `Asset | Type | Amount | USD Value`

Formatting rules:

- Use `assets` when present.
- For the asset label, prefer `symbol`, then `name`, then `token_address`,
  then `asset_type`.
- When the label came from `symbol`/`name` (not the token_address itself)
  and a `token_address` is present, append it shortened in parentheses next
  to the label as `first6…last4` (e.g. `USDC (0x833589…029139)`) — keep the
  contract visible but compact, never show it twice.
- For the amount, prefer `amount_ui`, then `balance_ui`, then
  `balance_native`, then `amount_raw`.
- For the USD value, prefer `value_usd`, then `balance_usd`.
- Omit zero-value rows only when both the amount and USD value are clearly
  zero. If no asset rows are available, still report the native balance
  summary in prose.
- Assets with no `symbol`/`name` and no `price_usd` are unverified
  contracts (commonly spam or airdropped tokens on Base). Do not list them
  individually in the table — instead add one short line after the table
  noting how many were omitted, e.g. "Plus 46 unverified ERC-20 contracts
  with no symbol or price data (not included in the total)."
- Do not include source metadata lines or footer fields such as `source`,
  `token_discovery_source`, or `pricing_source`.

After the table:

- Add one short line confirming the session wallet backend is now Base, so
  the user knows follow-up wallet requests will target it by default. If
  `set_wallet_backend` failed, add one short warning line instead (e.g. a
  stale local EVM daemon holding its port after a plugin upgrade) — note
  that the portfolio above is still accurate, and that the backend switch
  can be retried. Never drop the portfolio report because the switch
  failed.

Keep the response concise. Do not suggest transfers, swaps, bridging, or
other write actions unless the user explicitly asks for them. If
`get_wallet_overview` fails, surface the tool error plainly and stop.
