---
description: Enable AgentLayer autonomous Base swaps and EVM DeFi tools without per-transaction approvals.
allowed-tools: mcp__agent_wallet__agentlayer_autonomous_approve, mcp__agent_wallet__agentlayer_autonomous_status
---

Enable the high-trust autonomous AgentLayer permission group.

Call `agentlayer_autonomous_approve` with:

```json
{
  "scope": "base_swaps",
  "purpose": "User requested autonomous Base swaps and EVM DeFi tools from Claude Code.",
  "user_intent": true
}
```

Then call `agentlayer_autonomous_status` and report whether both `base_swaps` and `defi_tools` are enabled.

Be explicit in the response:

- This removes per-transaction approvals for Base Velora/Uniswap swap execute calls and supported EVM DeFi management tools.
- The `scope=base_swaps` argument is a compatibility value; this command enables the combined autonomous permission group.
- It does not authorize transfers, bridges, Solana swaps, or generic contract calls.
- The user can run `/agentlayer-autonomous-revoke` to disable it.
