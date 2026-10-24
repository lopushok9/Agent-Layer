---
name: "yield"
description: "Scan the wallet's Morpho vault positions on Base and Ethereum for better vaults with the same asset, set up a scan every 3 days as a Codex automation, or move a position to another vault after explicit confirmation. Use when the user asks for $yield or /yield, wants their Morpho vault yields compared or a better vault found, or when an automation runs this skill."
---

# Yield — Morpho vault scanner

Use the local AgentLayer wallet MCP tools only.

The monitor compares the wallet's Morpho vault positions (V1 and V2) on Base
and Ethereum with other vaults holding the same asset on the same chain. A
candidate is listed, has no red warning, has at least $1M in deposits and beats the
current vault on both the realized 7-day and 30-day net APY. Migration gas is
an estimate shown to the user; it never removes a candidate.

## Scan (default, and every automation run)

1. Call `get_morpho_rebalance_report` with no arguments (it reads only). Do
   not call any wallet write tool in an automation run.
2. If `monitor.new_opportunity_count` is 0 and no position has candidates, say
   in one line that no better vaults were found and how many positions were
   checked.
3. Otherwise, per position: the current vault (current rate, 7d and 30d
   averages, deposits, position size), then each candidate in a compact
   table: 7d / 30d, difference versus the current vault, reward share,
   deposits (total supplied to the vault, shown compactly in USD, e.g.
   $120.7M), warnings, the young flag, and whether it is new since the last
   scan (`isNew`). Then the migration cost estimate.
4. Point out what deserves attention without deciding for the user: a large
   reward share, a young vault, a yellow warning, a vault with small
   deposits.
5. Say plainly that nothing was moved, then end with one short sentence
   offering the best move: amount and asset, from which vault to which, the
   network, and that a preview with gas comes first. For example: "Move
   1,000 USDC from Steakhouse USDC to Gauntlet USDC Prime on Base? Say yes and
   I will show the preview with gas first." If the user agrees, follow the
   move steps below.

## Schedule every 3 days

Call `get_morpho_monitor_schedule` with `host: "codex"` and give the user the
returned `user_steps` (a Codex automation that runs `$yield` every
3 days). Set it up only when the user asks for it.

## Question menus

Use the host's native question menu (`request_user_input_async` or
`request_user_input`) for missing choices only when the tool is exposed and
its current mode and purpose restrictions allow it. Follow that tool's actual
schema; use short options and free text where supported. Otherwise ask in chat
in a format allowed by the host. Reuse choices and amounts the user already
provided; do not ask them again. Do not request keys, passwords, card details
or approval tokens through a question menu.

For a confirmation required below, show the same preview and terms, then use a
menu only if the host permits that tool for confirmations; otherwise ask in
chat. Keep the workflow's existing consent rules and confirmation exceptions.
A service/type/amount selection is not payment consent. An async call returning,
a preselected option, an empty answer, cancellation or elapsed time is not
consent: wait for the user's submitted answer before any dependent action.
Question menus do not replace host approval or backend checks or authorize
changed parameters. Keep existing approval scope, expiry, batch/continuation
and retry rules; a menu never expands them. Do not add another confirmation
solely to display a menu. Never switch modes just to open a menu or promise a
keyboard shortcut controlled by the host.

## Move a position

1. Call `rebalance_evm_morpho_vault_position` with `mode: "intent_preview"`,
   the two vault addresses, the network of the position, an optional
   `amount_raw` (omit it to move the whole position) and a short `purpose`.
2. Show the preview: both vaults with their rates, the amount, the withdraw
   gas estimate, whether an approval runs before the supply, and any
   `target_risk_flags`. Ask under the question-menu confirmation rules above,
   using `Move` / `Cancel` when a menu is permitted. Only the submitted `Move`
   choice or the existing explicit chat confirmation `Move` is consent.
3. On `Move`: the same call with `mode: "intent_execute"` and identical
   arguments. The plugin attaches the approval for the previewed move.
4. Report each step's transaction hash. If `status` is `partial`, the funds
   are in the wallet: say so and do not retry on your own.
