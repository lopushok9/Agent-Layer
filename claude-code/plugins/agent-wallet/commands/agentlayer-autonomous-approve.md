---
description: Enable AgentLayer autonomous wallet execution (every write tool) without per-transaction approvals.
allowed-tools: AskUserQuestion, mcp__agent_wallet__agentlayer_autonomous_approve, mcp__agent_wallet__agentlayer_autonomous_status
disable-model-invocation: true
---

Enable the high-trust autonomous AgentLayer permission group.

First call `agentlayer_autonomous_status`.

If both `base_swaps` and `defi_tools` are already enabled, report that the combined autonomous permission group is already active and remind the user that `/agentlayer-autonomous-revoke` disables it.

Otherwise, use `AskUserQuestion` to confirm:

- header: `Autonomy`
- question: `Enable AgentLayer autonomous execution for every wallet write tool (transfers, swaps, bridges, staking, x402 payments, generic contract calls, DeFi management) without per-transaction approvals, with no spend cap?`
- options:
  - `Enable` — `Turns on unbounded autonomous execution for every wallet write tool until revoked.`
  - `Cancel` — `Leaves per-transaction approvals in place and does not change permissions.`

Only if the user selects `Enable`, call `agentlayer_autonomous_approve` with:

```json
{
  "scope": "all",
  "purpose": "User requested autonomous wallet execution from Claude Code.",
  "user_intent": true
}
```

Then call `agentlayer_autonomous_status` and report whether both `base_swaps` and `defi_tools` are enabled.

If the user selects `Cancel`, do not call any write tool. State that autonomous permissions were not changed.

Be explicit in the response:

- This removes per-transaction approvals for every wallet write tool: transfers, bridges, Solana swaps, staking, x402 payments, generic contract calls, Base Velora/Uniswap swap execute calls, and supported EVM DeFi management tools.
- This command enables the combined autonomous permission group, which has no per-tool allow-list, spend cap, or session TTL -- it is unbounded by amount within its scope.
- The user can run `/agentlayer-autonomous-revoke` to disable it.
