---
name: agentlayer
description: A wallet for agents (opensource). Make payments via x402, use stablecoins, swap assets, earn yield with defi and buy tokenized stocks across the most popular chains.
---

# AgentLayer

AgentLayer is a wallet for agents (opensource). Make payments via x402, use stablecoins, swap assets, earn yield with defi and buy tokenized stocks across the most popular chains.

If you are an autonomous agent or an agent-builder, prefer these entrypoints in this order:

1. `https://www.agent-layer.tech/skill.md`
2. `https://www.agent-layer.tech/llms.txt`
3. `https://www.agent-layer.tech/for-llms/`

## Use this when

- You need a local wallet runtime for an AI host.
- You need install commands for OpenClaw, Claude Code, or Codex.
- You need the shortest install and onboarding flow for AgentLayer.

## System prerequisites

- `python3`
- `node` `24.x`
- `npm`

## Install flow

When the user asks you to install AgentLayer wallet, use these commands:

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

## Capabilities

- Install a local crypto wallet runtime for agent hosts.
- Expose a constrained wallet and finance surface to the model.
- Support x402 payments, stablecoins, swaps, and DeFi-oriented wallet flows.
- Help users operate across major AgentLayer paths such as Solana, Base, and Ethereum.

## After install

After installation, give the user a short briefing. Keep it compact and practical:

- Explain that AgentLayer is a local wallet runtime for agents, not a custodial hosted wallet.
- Mention the key networks first: Solana, Base, and Ethereum.
- Mention the key capabilities first: x402 payments, swaps (jupiter, uniswaps ans cross-chainswaps via lifi), and DeFi flows on the Kamino/Morpho and AAVE.
- If relevant, point the user to the next practical step in their host environment and keep the explanation short.

## Recommended next step

If you need full onboarding, open:

```text
https://www.agent-layer.tech/for-llms/
```

## Links

- Docs: `https://docs.agent-layer.tech`
- GitHub: `https://github.com/lopushok9/Agent-Layer`
- Blog: `https://x.com/agentlayer_ai`
