---
name: wallet-operator
description: Use whenever the user's own funds are involved, even if they never say "wallet": balances, portfolio, transfers, swaps, LI.FI cross-chain swaps, Jupiter swaps, Velora EVM swaps, BTC transfers, staking, Kamino lending, Bags launches, and wallet execution safety.
---

# Wallet Operator

Use this skill before calling OpenClaw wallet tools. It is the routing guide for wallet commands, providers, units, and confirmation flow.

## Core Rules

1. Start with `get_wallet_capabilities` when the active chain, signing support, or available tools are unclear.
2. Use `get_wallet_address` before asking for deposits or confirming a recipient/source wallet.
3. Use `get_wallet_balance` before spending, swapping, bridging, staking, lending, or claiming.
4. Treat `get_wallet_balance` as the default balance read for the active backend, not as a Solana-only helper. If `get_wallet_capabilities` says `can_get_balance=true`, prefer calling `get_wallet_balance` before assuming a backend lacks native balance support.
5. Use `preview` first for every write action. For Solana Jupiter swaps, prefer `intent_preview` then `intent_execute` after explicit chat confirmation so execution can refresh the quote inside approved limits. Solana swap intents are normalized by the backend to at least 300 bps slippage, 120 seconds validity, and 3 fresh execution attempts; do not pass a hand-tightened `minimum_output_amount_raw` unless the user explicitly set that floor. Use `prepare` only after explicit user intent. In OpenClaw, use `execute` only after the user explicitly confirms the shown summary in chat; do not ask the user for `/approve`, buttons, popups, or a manual token.
6. `prepare` returns an execution plan only; it must not return signed transaction bytes.
7. On mainnet, restate the network and material terms before `execute`; the OpenClaw plugin handles the internal execution authorization after chat confirmation.
8. If backend is `sign_only`, do not execute; use `prepare` and state that nothing was broadcast.
9. Never claim a transfer, swap, bridge, stake, claim, deposit, borrow, repay, or withdrawal happened unless the tool result says it was broadcast/confirmed.
10. Do not use Mayan. Direct Mayan paths were removed. Cross-chain swaps must go through LI.FI with Mayan denied.

## Provider Map

- Solana same-chain swap: `swap_solana_tokens` via Jupiter.
- EVM same-chain swap: `swap_evm_tokens` via Velora, ERC-20 to ERC-20 on `ethereum` or `base`.
- Cross-chain Solana -> EVM: `swap_solana_lifi_cross_chain_tokens` via LI.FI.
- Cross-chain EVM -> EVM/Solana: `swap_evm_lifi_cross_chain_tokens` via LI.FI.
- SOL/SPL transfers: `transfer_sol`, `transfer_spl_token`.
- EVM transfers: `transfer_evm_native`, `transfer_evm_token`.
- BTC transfer: `transfer_btc`.
- Solana staking: `stake_sol_native`, `deactivate_solana_stake`, `withdraw_solana_stake`.
- Kamino: `get_kamino_portfolio`, `get_kamino_vaults`, `get_kamino_earn_positions`, `get_kamino_liquidity_positions`, `kamino_lend_deposit`, `kamino_lend_withdraw`, `kamino_lend_borrow`, `kamino_lend_repay`, `kamino_earn_deposit`, `kamino_earn_withdraw`.
- Bags: `launch_bags_token`.

## Common Token IDs

- Native SOL for LI.FI: `sol`, `native`, or `11111111111111111111111111111111`.
- Native SOL mint for Jupiter swaps: `So11111111111111111111111111111111111111112`.
- Native ETH for LI.FI EVM destinations/sources: `eth`, `native`, or `0x0000000000000000000000000000000000000000`.
- EVM token addresses should be lowercase when possible. Checksummed addresses are accepted in current code and normalized for LI.FI.
- Solana USDC mint: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`.
- Base USDC: `0x833589fcd6edb6e08f4c7c32d4f71b54bda02913`.
- LI.FI chain IDs: Ethereum `1`, Base `8453`, Solana `1151111081099710`.

## Read Commands

- `get_wallet_capabilities`: available chain, backend, send/sign support.
- `get_wallet_address`: active wallet address.
- `get_wallet_balance`: primary balance/portfolio summary for the active backend.
  - Solana: native SOL plus discovered SPL assets and USD values when available.
  - EVM: native ETH balance plus discovered ERC-20 assets and USD values when available.
  - If the user asks for an EVM wallet balance, try this first before falling back to token-specific reads.
- `get_wallet_portfolio`: detailed Solana portfolio holdings. Do not assume this works on every backend; `wdk_evm_local` may reject portfolio lookup even when `get_wallet_balance` works.
- `get_solana_token_prices`: prices by Solana mint.
- `get_lifi_supported_chains`: supported LI.FI subset.
- `get_lifi_quote`: read-only LI.FI quote/status surface; use when user asks for indicative cross-chain quote outside the write flow.
- `get_lifi_transfer_status`: check LI.FI bridge status after a cross-chain source transaction.
- `get_evm_network`: active EVM network and supported EVM swap networks.
- `get_evm_token_balance`: ERC-20 balance by `token_address`, optional `network`. This is not the native ETH balance reader; use it for a specific token contract such as USDC or WETH.
- `get_evm_token_metadata`: ERC-20 metadata by `token_address`, optional `network`.
- `get_evm_fee_rates`: EVM fee suggestions.
- `get_evm_transaction_receipt`: EVM receipt by `tx_hash`.
- `get_btc_transfer_history`, `get_btc_fee_rates`, `get_btc_max_spendable`: BTC read helpers.

## Balance Routing

- Solana wallet balance request: use `get_wallet_balance`.
- EVM wallet balance request: use `get_wallet_balance` first for native ETH and discovered ERC-20 holdings.
- EVM specific token balance request: use `get_evm_token_balance` with a concrete ERC-20 `token_address`.
- EVM native transfer sizing: use `get_wallet_balance` for available ETH, then `get_evm_fee_rates` if the user needs fee context.
- If the tool descriptions and runtime capabilities seem inconsistent, prefer a direct read call over guessing from descriptions alone.

## Transfer Commands

- SOL transfer: `transfer_sol`
  - Params: `recipient`, `amount` in SOL UI units, `mode`, `purpose`, optional `user_intent`.
- SPL transfer: `transfer_spl_token`
  - Params: `recipient`, `mint`, `amount` in UI units, optional `decimals`, `mode`, `purpose`.
- EVM native transfer: `transfer_evm_native`
  - Params: `recipient`, `amount_wei` raw wei string, `mode`, `purpose`, optional `network`.
- EVM ERC-20 transfer: `transfer_evm_token`
  - Params: `token_address`, `recipient`, `amount_raw` base-unit string, `mode`, `purpose`, optional `network`.
- BTC transfer: `transfer_btc`
  - Params: `recipient`, `amount_sats`, optional `fee_rate`, `confirmation_target`, `mode`, `purpose`.

## Swap Commands

- Solana same-chain Jupiter swap: `swap_solana_tokens`
  - Params: `input_mint`, `output_mint`, `amount` in UI units, optional `slippage_bps`, `minimum_output_amount_raw`, `max_fee_lamports`, `valid_for_seconds`, `max_attempts`, `mode`, `purpose`.
  - Prefer `mode=intent_preview`, show the intent limits to the user, then after chat confirmation call `mode=intent_execute` with the same semantic params. This confirms risk limits, not a stale quote fingerprint.
  - Default Solana swap slippage is 300 bps (3%). The backend computes the approved minimum output from the indicative output and slippage, not from a strict RFQ threshold.
  - The primary execution path uses Jupiter Swap API V2 `/order` + `/execute`; if a JupiterZ/RFQ route fails, the backend retries with a non-JupiterZ route when possible.
  - Metis `/swap` fallback builds use Jupiter dynamic slippage and a bounded `veryHigh` priority fee instead of the old `"auto"` priority mode.
  - Do not use legacy `execute` for Solana Jupiter swaps in OpenClaw; exact quote-bound approval is too fragile for active markets.
  - Use for SOL<->SPL or SPL<->SPL on Solana. Do not use LI.FI for Solana-only swaps.
- EVM same-chain Velora swap: `swap_evm_tokens`
  - Params: `token_in`, `token_out`, `amount_in_raw` base-unit string, `mode`, `purpose`, optional `network`.
  - Current intended path is ERC-20 to ERC-20 on `ethereum` or `base`.
- EVM swap quote only: `get_evm_swap_quote`
  - Params: `token_in`, `token_out`, `amount_in_raw`, optional `network`.

## Cross-Chain Commands

- Solana -> Ethereum/Base: `swap_solana_lifi_cross_chain_tokens`
  - Source must be Solana mainnet.
  - Params: `input_token`, `destination_chain` (`ethereum`, `base`, `1`, `8453`), `output_token`, `destination_address`, `amount_in_raw`, optional `slippage`, bridge lists, `mode`, `purpose`.
  - Example SOL -> Base native ETH: `input_token=sol`, `destination_chain=base`, `output_token=native`, `amount_in_raw` in lamports.
  - Execute confirms the Solana source tx. Use `get_lifi_transfer_status` to track final destination-chain completion.
- Ethereum/Base -> Ethereum/Base/Solana: `swap_evm_lifi_cross_chain_tokens`
  - Source network is selected by active EVM network or optional `network`.
  - Params: `token_in`, `destination_chain` (`ethereum`, `base`, `solana`, `1`, `8453`, `1151111081099710`), `output_token`, `destination_address`, `amount_in_raw`, optional `slippage`, bridge lists, `mode`, `purpose`, optional `network`.
  - Native EVM input can be `native`, `eth`, or zero address.
  - Solana output token should be a Solana mint such as USDC mint.

## Staking And DeFi Commands

- `stake_sol_native`: `vote_account`, `amount` in SOL, `mode`, `purpose`.
- `deactivate_solana_stake`: `stake_account`, `mode`, `purpose`.
- `withdraw_solana_stake`: `stake_account`, `amount` in SOL, optional `recipient`, `mode`, `purpose`.
- Before Kamino lend writes, use `get_kamino_lend_markets`, `get_kamino_lend_market_reserves`, `get_kamino_lend_user_obligations`, and `get_kamino_lend_user_rewards`.
- For broader Kamino read coverage, prefer `get_kamino_portfolio` first, then drill into `get_kamino_vaults`, `get_kamino_earn_positions`, or `get_kamino_liquidity_positions` as needed.
- Kamino lend write params: `market`, `reserve`, `amount_ui` decimal string, `mode`, `purpose`.
- Kamino Earn write params: `kvault`, `amount_ui` decimal string, `mode`, `purpose`.
- `launch_bags_token`: `name`, `symbol`, `description`, `base_mint`, `claimers`, `basis_points`, `initial_buy_sol`, `mode`, `purpose`; optional socials/image/config type.
- `close_empty_token_accounts`: `limit`, `mode` (`preview` or `execute`), `purpose`.

## Approval Flow Template

1. Call the write tool with `mode=preview` and a concrete `purpose`.
2. Show the user the important fields: chain, token, amount, destination, provider, estimated output/minimum output, fees, and route/tool when present.
3. For `prepare`, call same tool with `mode=prepare`, same params, `user_intent=true`.
4. For `execute`, use the same semantic params after the user's chat confirmation. Do not mutate amount, token, destination, network, slippage, or minimum output between preview and execute; do not ask the user for a token or out-of-chat approval action.
5. For cross-chain swaps, after execute, offer `get_lifi_transfer_status` using the source tx hash and bridge/tool if returned.

## Disabled Or Avoided Paths

- Do not invent generic calldata, arbitrary contract calls, token approvals, or non-listed bridge providers.
- If a requested tool is absent from `list_tools` or capabilities, say the wallet runtime does not expose it.
