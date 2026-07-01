---
name: "wallet-sol"
description: "Show the current Solana wallet portfolio from the local AgentLayer wallet in a compact chat table. Use when the user asks for /wallet-sol or wants the Solana wallet shown directly in chat."
---

# Solana Wallet Portfolio

Use the local AgentLayer wallet MCP tools only.

Workflow:

1. Call `set_wallet_backend` with `backend=solana`.
2. Call `get_wallet_portfolio` with no address override.
3. Render the result directly in chat in this shape:
   - title: `Solana Wallet Portfolio`
   - bullets for `Chain`, `Network`, `Address`, and `Total Value (USD)` when available
   - one compact Markdown table with columns: `Asset | Type | Amount | USD Value`

Formatting rules:

- Use `assets` when present.
- For the asset label, prefer `symbol`, then `name`, then `mint`, then `token_address`, then `asset_type`.
- When the label came from `symbol`/`name` (not the mint/token_address itself) and a `mint` or `token_address` is present, append it shortened in parentheses next to the label as `first6…last4` (e.g. `USDC (EPjFWd…TDt1v)`) — keep the contract visible but compact, never show it twice.
- For the asset type, use `asset_type` when present; otherwise infer `native` for the native asset and `token` for the rest.
- For the amount, prefer `amount_ui`, then `balance_ui`, then `balance_native`, then `amount_raw`.
- For the USD value, prefer `value_usd`, then `balance_usd`.
- Do not include source metadata lines or extra footer fields such as `source`, `token_discovery_source`, `pricing_source`, or `pricing_errors`.
- Keep the response concise. Do not add strategy suggestions, swap ideas, or write actions unless the user explicitly asks for them.
- If the wallet tool fails, surface the tool error plainly and stop.
