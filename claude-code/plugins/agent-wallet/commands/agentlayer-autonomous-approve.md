---
description: Enable AgentLayer autonomous Base swaps without per-transaction approvals.
allowed-tools: mcp__agent_wallet__agentlayer_autonomous_approve, mcp__agent_wallet__agentlayer_autonomous_status
---

Enable high-trust autonomous Base swaps for AgentLayer.

Call `agentlayer_autonomous_approve` with:

```json
{
  "scope": "base_swaps",
  "purpose": "User requested autonomous Base swaps from Claude Code.",
  "user_intent": true
}
```

Then call `agentlayer_autonomous_status` and report whether `base_swaps` is enabled.

Be explicit in the response:

- This only removes per-transaction approvals for Base Velora/Uniswap swap execute calls.
- It does not authorize transfers, withdrawals, lending, staking, bridges, Solana swaps, or non-Base networks.
- The user can run `/agentlayer-autonomous-revoke` to disable it.
