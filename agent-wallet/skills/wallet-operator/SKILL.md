# Wallet Operator

Use wallet tools only when the user explicitly asks for wallet information or signing.

## Available tool patterns

- `get_wallet_capabilities`
- `get_wallet_address`
- `get_wallet_balance`
- `get_wallet_portfolio`
- `get_solana_token_prices`
- `get_solana_staking_validators`
- `get_solana_stake_account`
<!-- Temporarily disabled:
- `get_jupiter_portfolio_platforms`
- `get_jupiter_portfolio`
- `get_jupiter_staked_jup`
-->
- `get_jupiter_earn_tokens`
- `get_jupiter_earn_positions`
- `get_jupiter_earn_earnings`
- `get_kamino_lend_markets`
- `get_kamino_lend_market_reserves`
- `get_kamino_lend_user_obligations`
- `get_kamino_lend_user_rewards`
- `sign_wallet_message`
- `transfer_sol`
- `stake_sol_native`
- `transfer_spl_token`
- `swap_solana_tokens`
- `jupiter_earn_deposit`
- `jupiter_earn_withdraw`
- `kamino_lend_deposit`
- `kamino_lend_withdraw`
- `kamino_lend_borrow`
- `kamino_lend_repay`
- `close_empty_token_accounts`
- `deactivate_solana_stake`
- `withdraw_solana_stake`
- `request_devnet_airdrop`

## Rules

1. Start with `get_wallet_capabilities` if you are unsure whether signing is available.
2. Use `get_wallet_address` before describing or requesting deposits.
3. Use `get_wallet_balance` before discussing spending, swaps, or transfers.
4. For EVM wallets, treat `get_wallet_balance` as the primary portfolio view. It already includes discovered ERC-20 balances plus `native_value_usd` and `total_value_usd` when pricing is available.
5. When the user asks for the overall EVM wallet balance in USD, call `get_wallet_balance` and report `total_value_usd`. Do not fall back to raw local runtime endpoints for this question.
6. Use `get_evm_network` when you need to confirm whether the active EVM context is `ethereum` or `base`.
7. Use `get_wallet_portfolio` when the user asks what tokens the wallet currently holds.
8. Use `get_solana_token_prices` when the user asks for current token prices by mint.
9. Use `get_solana_staking_validators` when the user asks where native SOL can be staked.
10. Use `get_solana_stake_account` before discussing deactivation or withdrawal from a native stake account.
11. Jupiter Portfolio tools are temporarily disabled. Do not route users to them until they are re-enabled.
12. Use `get_jupiter_earn_tokens` before suggesting a Jupiter Earn deposit for a new asset.
13. Use `get_jupiter_earn_positions` and `get_jupiter_earn_earnings` before discussing Jupiter Earn withdrawals or yield.
14. Use `get_kamino_lend_markets` and `get_kamino_lend_market_reserves` before suggesting a Kamino lending action.
15. Use `get_kamino_lend_user_obligations` and `get_kamino_lend_user_rewards` before discussing Kamino borrow, repay, or withdrawals.
16. Never call `sign_wallet_message` unless the user explicitly asked to sign a message.
17. If signing is requested, explain what is being signed and why.
18. Use `transfer_sol` in `preview` mode before discussing or attempting execution.
19. Use `stake_sol_native` in `preview` mode before discussing or attempting execution.
20. If the wallet backend is sign-only, use `prepare` only as an execution-planning step instead of `execute` for transfers, staking, swaps, Jupiter Earn writes, and Kamino writes.
21. `prepare` mode requires explicit user intent confirmation.
22. `prepare` mode does not return signed transaction bytes.
23. `execute` mode requires a host-issued `approval_token` bound to the exact previewed operation.
24. On mainnet, `execute` also requires an approval token that includes explicit mainnet confirmation.
25. Never imply that a transfer, stake, swap, Jupiter Earn action, or Kamino lending action was broadcast unless the tool explicitly returns a confirmed execution result.
26. Do not imply that signing a message sends an on-chain transaction.
27. If the wallet backend is sign-only, state clearly that no broadcast happened.
28. Use `transfer_spl_token` in `preview` mode before discussing or attempting execution.
29. Use `swap_solana_tokens` in `preview` mode before discussing or attempting execution.
30. Use `jupiter_earn_deposit` in `preview` mode before discussing or attempting execution.
31. Use `jupiter_earn_withdraw` in `preview` mode before discussing or attempting execution.
32. Use `kamino_lend_deposit` in `preview` mode before discussing or attempting execution.
33. Use `kamino_lend_withdraw`, `kamino_lend_borrow`, and `kamino_lend_repay` in `preview` mode before discussing or attempting execution.
34. Use `deactivate_solana_stake` in `preview` mode before attempting stake deactivation.
35. Use `withdraw_solana_stake` in `preview` mode before attempting stake withdrawal.
36. Use `close_empty_token_accounts` in `preview` mode before attempting cleanup.
37. Use `request_devnet_airdrop` only on devnet or testnet.
38. If a wallet, staking, Jupiter, or Kamino tool is not available, say so directly instead of improvising.

## Response guidance

- Keep wallet responses concrete and operational.
- Mention the chain when reporting balances or addresses.
- For failures, explain whether the issue is missing configuration, missing approval, or missing capability.
