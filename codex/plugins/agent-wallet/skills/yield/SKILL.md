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

## Move a position

1. Call `rebalance_evm_morpho_vault_position` with `mode: "intent_preview"`,
   the two vault addresses, the network of the position, an optional
   `amount_raw` (omit it to move the whole position) and a short `purpose`.
2. Show the preview: both vaults with their rates, the amount, the withdraw
   gas estimate, whether an approval runs before the supply, and any
   `target_risk_flags`. Ask with `AskUserQuestion` (header `Move funds`),
   options `Move` / `Cancel`. Only `Move` is consent.
3. On `Move`: the same call with `mode: "intent_execute"` and identical
   arguments. The plugin attaches the approval for the previewed move.
4. Report each step's transaction hash. If `status` is `partial`, the funds
   are in the wallet: say so and do not retry on your own.
