# AgentLayer Wallet — Agent Guide

> **Relationship to `skills/wallet-operator/SKILL.md`:** that file is the
> authoritative, terse routing skill actually loaded by hosts (provider map, param
> tables, approval-flow template) — keep changes to tool routing/params there, not
> here. This document is a narrative companion: written the way an agent (or a human
> reading over its shoulder) would want the product *explained*, not just routed —
> modeled on how the `catena` CLI ships a self-contained `catena guide` command
> alongside its terse `--help` output; the `/guide` command in this plugin serves
> that exact role. Tool names below are short; the full MCP name is
> `mcp__plugin_agent-wallet_agent-wallet__<name>`.

This server holds funds in the local AgentLayer wallet across Solana, EVM
(Ethereum, Base, Robinhood chain), and Bitcoin. It is not a generic
crypto-data tool — every write here moves real money unless stated as
mainnet-gated preview. Leverage markets (Flash Trade perps:
`flash_trade_open_position`, `flash_trade_close_position`,
`get_flash_trade_markets`, `get_flash_trade_positions`) are out of scope for
this guide — do not use them without separate instructions.

## What You Can Do

- **Solana**: transfers, swaps via Jupiter, native staking, Kamino (lending +
  earn vaults + LP positions), token launches via Bags.
- **EVM** (Ethereum / Base / Robinhood): transfers, swaps (Velora or
  Uniswap), and DeFi — Aave (lending), Lido (ETH staking), Morpho (markets +
  vaults), and Uniswap concentrated liquidity positions (create / increase /
  decrease / claim fees, V3 and V4 — existing V4 positions can't be
  auto-discovered, only V3; for a V4 position the id has to come from the
  user).
- **Cross-chain bridging** (LI.FI): Ethereum / Base / Solana to each other.
- **x402**: pay per-request HTTP 402 paywalls straight from the wallet —
  preview the payment terms for free, then pay in one call.

See the sections below for exact tool names and parameters.

## Setup & Session State

1. `get_active_wallet_backend` — which backend (solana / evm / btc) is live
   for this session, and whether it differs from the startup default.
2. `get_wallet_address` — the address for the active backend.
3. `get_wallet_capabilities` — chain, backend, and the safety limits in force.
4. `set_wallet_backend` (`backend`: solana / evm / ethereum / base /
   robinhood / btc / bitcoin, optional `network`) — switch backend for this
   session without touching config files.
5. For EVM specifically: `get_evm_network` shows the effective network and
   which networks support swaps; `set_evm_network` (ethereum / base /
   robinhood) changes it.

Balance reads (Solana): `get_wallet_balance` / `get_wallet_portfolio` are the
same enriched payload (native SOL + non-zero SPL accounts + USD pricing via
Jupiter) — `_portfolio` is just the more detailed name for the same call.
`get_wallet_overview` does the same lookup for an arbitrary backend/network/
address **without** switching the session's active wallet — use it to peek at
another chain or address in passing.

## Quick Commands (Claude Code slash commands)

The plugin also ships fixed-format slash commands for the most common
requests — faster and more predictable than a free-form tool call, but each
covers only its one exact use case:

| Command | What it does |
|---|---|
| `/wallet-setup` | Install or repair the local wallet backend runtime. |
| `/wallet-sol` | Print the Solana wallet portfolio. |
| `/wallet-evm` | Print the EVM wallet overview for the current/default network. |
| `/wallet-base` | Print the Base wallet overview, and switch the session's active backend to Base. |
| `/wallet-ethereum` | Print the Ethereum mainnet wallet overview. |
| `/cards` | Buy a Laso Finance prepaid card (US or international), paid via x402 from the connected wallet. |
| `/agentlayer-autonomous-approve` | Turn on the full autonomous permission group (see below), with an in-command confirmation step first. |
| `/agentlayer-autonomous-revoke` | Turn it back off. |
| `/guide` | Walk a new user through this document conversationally. |

Every command except `/wallet-setup` requires the user to type it themselves
— the agent cannot trigger them on its own.

## The preview → prepare → execute → approve Pattern

Nearly every write tool (transfers, swaps, staking, DeFi positions, BTC
sends, token launch) shares one lifecycle via a `mode` argument:

- `preview` — read-only summary of what the operation would do. No signing,
  no broadcast. Always do this first.
- `prepare` — returns an execution plan (unsigned) for the same operation.
  Requires `user_intent: true`. Used when the host needs to inspect the plan
  before approving.
- `execute` — actually signs and broadcasts. Requires a host-issued approval
  token bound to the exact previewed operation. In an interactive session the
  host's own confirmation dialog supplies this. When it doesn't,
  `issue_wallet_approval` is the explicit bridge step: call it with the
  `tool_name` and the verbatim `confirmation_summary` from the prepare
  response, plus `mainnet_confirmed: true` to acknowledge real funds are at
  stake.

In Claude Code, don't call `issue_wallet_approval` or ask the user for a raw
`approval_token` yourself — the host's own confirmation dialog supplies it
once the user approves the call.

Never skip straight to `execute` on a mainnet operation the user has not
explicitly approved. Preview it, show the human what it does, then execute.

Always pass a short `purpose` string on write calls — it's the human-facing
audit label for what the transaction is for.

## Standing Authority: Autonomous Sessions

Two separate mechanisms remove the per-transaction approval step. Both grant
broad, real-money authority and must only be turned on when the user has
explicitly asked for it:

- **Scoped autonomous session** — `start_autonomous_session` (preview then
  execute) opens a bounded session: `allowed_tools`, `allowed_networks`,
  `allowed_recipients`, per-tx / hourly / daily spend caps, tx-rate cap,
  operation count cap, and a session TTL. `allow_mainnet: true` is required to
  let it touch real funds. `get_autonomous_session` reads current status
  (active, limits, operations used, expiry); `stop_autonomous_session` always
  works and hands control back to per-transaction approval.
- **Full high-trust permission group** — `agentlayer_autonomous_approve`
  (scope `all`) is broader and unbounded by comparison: it covers *every*
  wallet write tool (transfers, bridges, Solana swaps, staking, x402
  payments, contract calls, EVM DeFi management) with no per-operation
  allow-list. Requires `user_intent: true` and an explicit purpose.
  `agentlayer_autonomous_status` reads it; `agentlayer_autonomous_revoke`
  turns it off.

Prefer the scoped session over the full permission group whenever the task
has a defined boundary (a specific token, a specific recipient, a spend cap)
— it's the difference between "let the agent do this one job unattended" and
"let the agent spend freely until told to stop."

There is no narrower version of the full permission group — pass `scope:
"all"`; for a bounded grant, use the scoped session instead.

## Solana

- **Transfers**: `transfer_sol` (native), `transfer_spl_token` (by mint
  address, optional `decimals` override).
- **Swaps**: `swap_solana_tokens` routes through Jupiter. Prefer
  `mode: intent_preview` then `intent_execute` — it re-quotes fresh
  immediately before sending and only executes within the previously
  approved limits, which matters because Jupiter quotes expire fast. Legacy
  `preview`/`prepare`/`execute` still works but is not preferred.
- **Prices**: `get_solana_token_prices` — Jupiter prices for a list of mints.
- **Housekeeping**: `close_empty_token_accounts` reclaims rent from
  zero-balance SPL token accounts (preview lists them, execute closes up to
  `limit`, default 8).
- **Native staking** (Solana Stake Program, not a DeFi protocol):
  `stake_sol_native` (to a validator vote account), `get_solana_stake_account`
  (activation status of one stake account), `get_solana_staking_validators`
  (list validators by commission/activated stake), `deactivate_solana_stake`,
  `withdraw_solana_stake`.
- **Kamino** (Solana's largest lend/earn/liquidity protocol):
  - Discovery (read-only): `get_kamino_lend_markets` → main market first;
    `get_kamino_lend_market_reserves` for per-token supply/borrow APY and
    maxLtv; `get_kamino_vaults` for Earn-vault discovery
    (`include_metrics: true` for APY/TVL, `token_mint` to filter).
  - Lending writes: `kamino_lend_deposit`, `kamino_lend_borrow`,
    `kamino_lend_repay`, `kamino_lend_withdraw` — all take `market`, `reserve`,
    `amount_ui`; prefer `intent_preview` → `intent_execute` for the same
    re-quote-before-send reason as swaps.
  - Earn vault writes: `kamino_earn_deposit`, `kamino_earn_withdraw` (take
    `kvault`, `amount_ui`).
  - Position reads: `get_kamino_lend_user_obligations` (one market),
    `get_kamino_open_positions` (all lending positions across markets),
    `get_kamino_earn_positions`, `get_kamino_liquidity_positions`,
    `get_kamino_lend_user_rewards`, and `get_kamino_portfolio` for the single
    unified view across lending/earn/liquidity/staking.
- **Token launch**: `launch_bags_token` creates a token via Bags with a
  fee-share config (`claimers` + `basis_points`, must sum to 10000) and an
  optional `initial_buy_sol`. Same preview/prepare/execute lifecycle.

## EVM (Ethereum, Base, Robinhood chain)

- **Read utilities**: `get_evm_token_balance`, `get_evm_token_metadata`,
  `get_evm_transaction_receipt` (by tx hash), `get_evm_fee_rates`.
- **Transfers**: `transfer_evm_native` (wei), `transfer_evm_token` (ERC-20,
  raw base units + `token_address`).
- **Swaps — two independent routers, pick one**:
  - Velora: `get_evm_swap_quote` (read-only) → `swap_evm_tokens`. Ethereum/
    Base only.
  - Uniswap: `get_uniswap_swap_quote` → `swap_evm_uniswap_tokens`. Covers
    CLASSIC pools, UniswapX orders, and ETH↔WETH wrap/unwrap; supports
    Ethereum, Base, and Robinhood chain; has a `slippage_bps` param (default
    300 = 3%).
  - `search_uniswap_pairs` finds a token's contract address by ticker/name
    via DexScreener — **security note**: free-text ticker search can surface
    impersonator tokens with fabricated liquidity/FDV, especially for tickers
    claiming to represent a real-world stock/ETF. Verify the resolved
    `token_address` independently (`get_evm_token_metadata`, or the chain's
    official contract list) before quoting or swapping a real-world-asset
    ticker — a successful quote does not itself prove legitimacy.
- **DeFi protocols** (read tools are free; every write follows preview →
  execute):
  - **Aave v3** (lending): `get_evm_aave_account` (health factor etc.),
    `get_evm_aave_positions` (per-reserve supplied/borrowed),
    `get_evm_aave_reserves` (market catalog) →
    `manage_evm_aave_position` with `operation`: supply / withdraw / borrow /
    repay.
  - **Lido** (ETH liquid staking, Ethereum mainnet only):
    `get_evm_lido_overview`, `get_evm_lido_positions` (stETH/wstETH),
    `get_evm_lido_withdrawal_requests` →
    `manage_evm_lido_position` (`stake_eth_for_wsteth` / `wrap_steth` /
    `unwrap_wsteth`) and `manage_evm_lido_withdrawal`
    (`request_withdrawal_steth` / `request_withdrawal_wsteth` /
    `claim_withdrawal`, needs `request_id` to claim).
  - **Morpho** (lending markets + curated vaults): `get_evm_morpho_markets` /
    `get_evm_morpho_vaults` for discovery (filter by asset, sort by APY —
    pair APY sorts with a `min_supply_usd`/`min_tvl_usd` floor to skip dust),
    `get_evm_morpho_positions` for what the wallet currently holds →
    `manage_evm_morpho_market_position` (supply_collateral / borrow / repay /
    withdraw_collateral, isolated market by `market_id` or `market_preset`)
    and `manage_evm_morpho_vault_position` (supply / withdraw, by
    `vault_address` or `vault_preset`).
  - **Uniswap Liquidity Provisioning** (concentrated LP positions, V3 and
    V4): discovery first — `get_evm_uniswap_pools` finds an existing pool by
    token pair and returns its `poolReferenceIdentifier`;
    `get_evm_uniswap_positions` lists the wallet's V3 position NFTs (fee
    tier, tick range, owed fees) — V4 position discovery isn't available
    (V4's PositionManager isn't enumerable on-chain the way V3's is) →
    `manage_evm_uniswap_liquidity` with `action`: create / increase /
    decrease / claim_fees. `create` needs `existingPool.poolReference` (the
    discovery tool's `poolReferenceIdentifier` value, under a different
    field name); increase/decrease/claim_fees need the position's NFT token
    id. Never guess either identifier — always discover it first, the tool
    rejects the call outright if it's missing. This is a thin pass-through
    to Uniswap's own official Liquidity API; deploying a brand-new pool is
    out of scope.

## Cross-Chain Bridging (LI.FI)

- `get_lifi_supported_chains` — currently allowed chains for routing.
- `get_lifi_quote` — read-only quote between any two of Ethereum / Base /
  Solana (bridge preferences via `allow_bridges` / `deny_bridges` /
  `prefer_bridges`, slippage as a decimal fraction).
- `swap_evm_lifi_cross_chain_tokens` — execute EVM-origin (Ethereum/Base) →
  Ethereum/Base/Solana.
- `swap_solana_lifi_cross_chain_tokens` — execute Solana-origin →
  Ethereum/Base.
- `get_lifi_transfer_status` — poll a bridge transfer by source tx hash.

Same preview/prepare/execute + approval-token discipline as everything else.
Mayan routes are deliberately denied — see `skills/wallet-operator/SKILL.md`.

## Bitcoin

- `transfer_btc` — amount in `amount_sats`, optional `fee_rate` (sats/vB) or
  `confirmation_target`.
- `get_btc_fee_rates`, `get_btc_max_spendable` (post-fee spendable estimate),
  `get_btc_transfer_history` (filter by `direction`, paginate with
  `limit`/`skip`).

## x402 — Paying HTTP 402 Endpoints

- `x402_search_services` — read-only discovery of paid services via CDP
  Bazaar or Agentic Market (filter by `query`, `max_usd_price`, `network`).
- `x402_get_service_details` — resolve one service/resource URL into details.
- `x402_preview_request` — makes the *unpaid* request, reads the 402
  challenge, and summarizes payment options. Does not pay.
- `x402_pay_request` — does the whole flow in one call: probes the endpoint,
  validates it, signs the payment from the active wallet backend, and
  returns the paid response. Requires `purpose`.

This is the same x402 v2 protocol the `catena` MCP/CLI speaks — a discrete
pay-per-request charge, not a subscription or usage meter — but here the
payer is this wallet directly rather than a governed bank rail, so there is
no separate approval-parking step: the preview → execute discipline above is
what stands between the agent and the payment.

## Explaining This to a Human

If asked to summarize this server in plain terms: it's a direct line to the
local AgentLayer wallet — Solana, an EVM chain (Ethereum/Base/Robinhood),
and Bitcoin — plus the major yield/lending/LP protocols on those chains
(Kamino, Aave, Lido, Morpho, Uniswap concentrated liquidity) and the ability
to pay per-request API/data paywalls (x402) straight from the wallet.
Everything that moves funds is gated by a preview step and an approval token
by default; "autonomous session" and "autonomous permission group" are the
two ways a human can explicitly grant the agent standing authority to skip
that per-transaction gate, bounded (the former) or broad (the latter) —
always confirm with the user before either one is enabled, and treat any
operation on mainnet as real, irreversible money movement.
