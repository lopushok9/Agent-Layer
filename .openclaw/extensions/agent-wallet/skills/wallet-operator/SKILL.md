# Wallet Operator

Use wallet tools only when the user explicitly asks for wallet information, signing, transfers, or swaps.

Safety rules:

- Prefer read-only tools first.
- For transfers, native staking, swaps, and Jupiter Earn writes, use `preview` before `prepare` or `execute`.
- Use `prepare` only when the user clearly intends to sign.
- Use `execute` only after explicit user confirmation.
- On `mainnet`, require an extra `mainnet_confirmed=true` step before any execution.
- Never claim funds moved unless the tool returns a confirmed transaction result.
- If the wallet is configured as `signOnly`, describe prepared transactions as signed but not broadcast.
- Use Jupiter read tools first when the user asks about portfolio positions, staked JUP, or Earn balances.
- Use native staking read tools first when the user asks about validators, stake accounts, deactivation, or withdrawals.
