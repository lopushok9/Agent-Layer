---
description: Show the connected EVM wallet overview for Ethereum directly in chat.
allowed-tools: mcp__agent_wallet__get_wallet_overview
disable-model-invocation: true
---

Show the connected EVM wallet overview for Ethereum directly in chat.

1. Call `get_wallet_overview` with:

```json
{
  "backend": "evm",
  "network": "ethereum"
}
```

2. Format the response as a compact wallet report:

- state the wallet as `EVM (Ethereum)`
- include `chain`, `network` (or `requested_network`), `address`, and `total_value_usd` when present
- render a Markdown table with columns: `Asset | Type | Amount | USD Value`
- use `assets` when present
- for each asset row, prefer:
  - asset label: `symbol`, then `token_address`, then `asset_type`
  - amount: `amount_ui`, then `balance_ui`, then `balance_native`, then `amount_raw`
  - usd value: `value_usd`, then `balance_usd`
- omit zero-value rows only when both the amount and USD value are clearly zero
- if no asset rows are available, still report the native balance summary in prose

3. After the table, add one short metadata line with any available sources:

- `source`
- `token_discovery_source`
- `pricing_source`

4. Do not suggest transfers, swaps, or other write actions unless the user explicitly asks for them.
