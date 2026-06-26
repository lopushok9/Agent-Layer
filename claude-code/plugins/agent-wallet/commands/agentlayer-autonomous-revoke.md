---
description: Disable AgentLayer autonomous Base swaps and EVM DeFi tools.
allowed-tools: mcp__agent_wallet__agentlayer_autonomous_revoke, mcp__agent_wallet__agentlayer_autonomous_status
---

Disable the full high-trust autonomous AgentLayer permission group.

Call `agentlayer_autonomous_revoke` with:

```json
{
  "scope": "base_swaps"
}
```

Then call `agentlayer_autonomous_status` and report whether both `base_swaps` and `defi_tools` are disabled.
