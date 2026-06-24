---
description: Disable AgentLayer autonomous Base swaps.
allowed-tools: mcp__agent_wallet__agentlayer_autonomous_revoke, mcp__agent_wallet__agentlayer_autonomous_status
---

Disable high-trust autonomous Base swaps for AgentLayer.

Call `agentlayer_autonomous_revoke` with:

```json
{
  "scope": "base_swaps"
}
```

Then call `agentlayer_autonomous_status` and report whether `base_swaps` is disabled.
