---
name: balance
description: Show the signed-in user's NEAR Omni Account balances across the NEAR wallet, NEAR Intents, Base and Ethereum using the NEAR Omni Account MCP. Use for /balance, $balance, or a request for this specific wallet's balance; this is separate from the local AgentLayer wallet.
---

# NEAR Omni Account balance

Call `omni_balances` once with no arguments from the connected NEAR Omni Account MCP (the server may be named `near-omni-account` in Codex or `near-omni` in Claude Code). Use the currently signed-in account; do not substitute the local AgentLayer wallet, CDP wallet, another MCP, or an arbitrary address. This is read-only: do not switch wallet backends, sign, transfer or create a wallet.

Show a compact table with columns `Location | Asset | Amount | USD`. Include the NEAR wallet, NEAR Intents and each EVM network returned. Use the asset's `symbol`, `formatted` amount and `value_usd` (show `—` when absent); do not show raw smallest-unit amounts. For an empty section say it has no reported assets. Include returned DeFi positions and their value if present, and the overall `total_value_usd` if provided. Note that USD values are approximate and that unpriced assets are excluded from totals. If `partial` is true or errors are returned, explain which sections failed; do not present incomplete data as a complete balance. Mention available versus storage-locked NEAR when provided.

If the MCP or tool is unavailable, say that the NEAR Omni Account MCP must be connected and authorized, and stop. If the call fails, report the error without guessing a balance or silently falling back to another wallet.
