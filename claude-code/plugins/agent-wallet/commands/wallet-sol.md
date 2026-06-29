---
description: Show the connected Solana wallet overview directly in chat.
allowed-tools: mcp__agent_wallet__set_wallet_backend, mcp__agent_wallet__get_wallet_balance
disable-model-invocation: true
---

Show the connected Solana wallet overview directly in chat.

1. Call `set_wallet_backend` with:

```json
{
  "backend": "solana"
}
```

This resolves the current Solana wallet session and returns the active Solana network. Use the returned `selected_network` in the final report when the balance payload does not include `network`.

2. Then call `get_wallet_balance` with:

```json
{}
```

3. Format the response as a compact wallet report:

- state the wallet as `Solana`
- include `chain`, `network`, `address`, and `total_value_usd` when present
- render a Markdown table with columns: `Asset | Type | Amount | USD Value`
- use `assets` when present
- for each asset row, prefer:
  - asset label: `symbol`, then `mint`, then `token_address`, then `asset_type`
  - amount: `amount_ui`, then `balance_ui`, then `balance_native`, then `amount_raw`
  - usd value: `value_usd`, then `balance_usd`
- omit zero-value rows only when both the amount and USD value are clearly zero
- if no asset rows are available, still report the native balance summary in prose

4. After the table, add one short metadata line with any available sources:

- `source`
- `token_discovery_source`
- `pricing_source`

5. Do not suggest transfers, swaps, or other write actions unless the user explicitly asks for them.
