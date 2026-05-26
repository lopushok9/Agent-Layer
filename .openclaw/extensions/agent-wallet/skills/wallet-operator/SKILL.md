# Wallet Operator

Use wallet tools only when the user explicitly asks for wallet information, signing, transfers, swaps, or lending/yield actions.

Safety rules:

- Prefer read-only tools first.
- When a wallet tool exists for the task, do not fall back to `exec`, `solana`, `spl-token`, `bitcoin-cli`, `curl`, or any shell-based wallet workflow. If the wallet tool fails, report the tool error and stop.
- Jupiter Portfolio tools are temporarily disabled. Do not suggest or call them until they are re-enabled.
- Use Jupiter Earn read tools before Jupiter Earn writes when the user needs lending/yield context.
- Use Kamino market/reserve reads before Kamino writes when the user needs lending context.
- Use Aave account reads before Aave writes when the user needs EVM lending context.
- For transfers, native staking, swaps, Aave writes, Jupiter Earn writes, and Kamino writes, use `preview` before `prepare` or `execute`.
- For Solana Jupiter swaps through `swap_solana_tokens`, prefer `intent_preview` then `intent_execute` after explicit chat confirmation. The user confirms risk limits; the backend refreshes the quote and only executes inside those limits.
- Solana swap intent defaults to at least 300 bps (3%) slippage, 120 seconds validity, and 3 fresh execution attempts. The backend computes the approved minimum output from the indicative output and slippage, clamps hand-tightened minimums to that floor, then executes through Jupiter Swap API V2 `/order` + `/execute` when available.
- Do not use legacy `execute` for Solana Jupiter swaps in OpenClaw. Exact quote-bound approval is too fragile for active markets and will be rejected by the bridge.
- For `swap_solana_privately`, use `preview` and then `execute` after explicit user approval. Do not use `prepare` for this tool.
- Use `prepare` only when the user clearly intends to produce an execution plan.
- Use `execute` only after the user explicitly confirms the shown summary in chat. OpenClaw handles the internal approval token; do not ask for `/approve`, buttons, popups, or a manual token. For Solana swap intents, the token is bound to the approved intent limits instead of one fragile quote.
- On `mainnet`, require an approval token that includes explicit mainnet confirmation before any execution.
- Before any `mainnet` execute, restate the network, operation type, asset, amount, and destination, validator, or stake account.
- If a preview or prepare result includes `confirmation_summary` or `mainnet_warning`, surface that summary before asking for confirmation.
- Never claim funds moved unless the tool returns a confirmed transaction result.
- If the wallet is configured as `signOnly`, describe `prepare` output as an execution plan only, not a signed transaction.
- Use native staking read tools first when the user asks about validators, stake accounts, deactivation, or withdrawals.
