---
description: Show the connected Base EVM wallet portfolio directly in chat and switch the active wallet backend to Base.
allowed-tools: mcp__agent_wallet__get_wallet_overview, mcp__agent_wallet__set_wallet_backend
disable-model-invocation: true
---

Show the connected Base EVM wallet portfolio directly in chat, and leave the
session's active wallet backend switched to Base so follow-up wallet calls in
this conversation don't need the backend specified again.

1. Call `get_wallet_overview` and `set_wallet_backend` together — they are
   independent, so issue both in the same turn rather than sequentially:

```json
// get_wallet_overview
{
  "backend": "evm",
  "network": "base"
}
```

```json
// set_wallet_backend
{
  "backend": "base",
  "network": "base"
}
```

2. Format the `get_wallet_overview` response as a compact wallet report:

- state the wallet as `EVM (Base)`
- include `chain`, `network` (or `requested_network` when `network` is absent), `address`, and `total_value_usd` when present
- render a Markdown table with columns: `Asset | Type | Amount | USD Value`
- use `assets` when present
- for each asset row, prefer:
  - asset label: `symbol`, then `name`, then `token_address`, then `asset_type`
  - when the label came from `symbol`/`name` (not the token_address itself) and a `token_address` is present, append it shortened in parentheses next to the label as `first6…last4` (e.g. `USDC (0x833589…029139)`) — keep the contract visible but compact, never show it twice
  - amount: `amount_ui`, then `balance_ui`, then `balance_native`, then `amount_raw`
  - usd value: `value_usd`, then `balance_usd`
- omit zero-value rows only when both the amount and USD value are clearly zero
- if no asset rows are available, still report the native balance summary in prose
- do not include source metadata lines or footer fields such as `source`, `token_discovery_source`, or `pricing_source`

3. Assets with no `symbol`/`name` and no `price_usd` are unverified contracts
   (commonly spam or airdropped tokens on Base). Do not list them individually
   in the table — instead add one short line after the table noting how many
   were omitted, e.g. "Plus 46 unverified ERC-20 contracts with no symbol or
   price data (not included in the total)."

4. After the table, add one short line confirming the session wallet backend
   is now Base so the user knows follow-up wallet requests will target it by
   default. If `set_wallet_backend` failed, add one short warning line instead
   (e.g. a stale local EVM daemon holding its port after a plugin upgrade) —
   note that the portfolio above is still accurate, and that the backend
   switch can be retried. Never drop the portfolio report because the switch
   failed.

5. Do not suggest transfers, swaps, bridging, or other write actions unless
   the user explicitly asks for them.
