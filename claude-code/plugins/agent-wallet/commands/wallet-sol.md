---
description: Show the connected Solana wallet portfolio directly in chat.
allowed-tools: mcp__agent_wallet__get_wallet_portfolio
disable-model-invocation: true
---

Show the connected Solana wallet portfolio directly in chat.

1. Call `get_wallet_portfolio` with:

```json
{}
```

2. Format the response as a compact wallet report:

- state the wallet as `Solana`
- include `chain`, `network` (or `requested_network` when `network` is absent), `address`, and `total_value_usd` when present
- render a Markdown table with columns: `Asset | Type | Amount | USD Value`
- use `assets` when present
- for each asset row, prefer:
  - asset label: `symbol`, then `name`, then `mint`, then `token_address`, then `asset_type`
  - when the label came from `symbol`/`name` (not the mint/token_address itself) and a `mint` or `token_address` is present, append it shortened in parentheses next to the label as `first6…last4` (e.g. `USDC (EPjFWd…TDt1v)`) — keep the contract visible but compact, never show it twice
  - amount: `amount_ui`, then `balance_ui`, then `balance_native`, then `amount_raw`
  - usd value: `value_usd`, then `balance_usd`
- omit zero-value rows only when both the amount and USD value are clearly zero
- if no asset rows are available, still report the native balance summary in prose
- do not include source metadata lines or footer fields such as `source`, `token_discovery_source`, `pricing_source`, or `pricing_errors`

3. Do not suggest transfers, swaps, or other write actions unless the user explicitly asks for them.
