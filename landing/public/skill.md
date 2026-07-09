---
name: agentlayer
description: Wallet and finance layer for agents. Use this when you need to install AgentLayer, connect to its MCP endpoint, or understand how to use its wallet and finance capabilities from an AI host like OpenClaw, Claude Code, or Codex.
---

# AgentLayer

AgentLayer is a wallet and finance layer for agents.

If you are an autonomous agent or an agent-builder, prefer these entrypoints in this order:

1. `https://www.agent-layer.tech/skill.md`
2. `https://www.agent-layer.tech/llms.txt`
3. `https://www.agent-layer.tech/for-llms/`

## Use this when

- You need a local wallet runtime for an AI host.
- You need an MCP endpoint for finance and wallet-related tasks.
- You need install commands for OpenClaw, Claude Code, or Codex.
- You need the shortest explanation of what AgentLayer exposes.

## Install

### OpenClaw

```bash
npx @agentlayer.tech/wallet install --yes
```

### Claude Code

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet claude-code install --yes
```

### Codex

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet codex install --yes
```

## MCP

Public MCP endpoint:

```text
https://agent-layer-production-852f.up.railway.app/mcp
```

Minimal config:

```json
{
  "mcpServers": {
    "AgentLayer": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}
```

## Capabilities

- Install a local wallet runtime for agent hosts.
- Expose a constrained wallet and finance surface to the model.
- Support x402 payments, stablecoins, swaps, and DeFi-oriented wallet flows.
- Expose MCP-based finance context such as prices, on-chain data, and agent-friendly market context.

## Recommended next step

If you need full onboarding, open:

```text
https://www.agent-layer.tech/for-llms/
```

## Links

- Docs: `https://docs.agent-layer.tech`
- GitHub: `https://github.com/lopushok9/Agent-Layer`
- Blog: `https://x.com/agentlayer_ai`
