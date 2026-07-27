---
name: agent-layer
description: Use when installing or setting up AgentLayer wallet for an AI agent. Trigger phrases include "install agent wallet", "set up agentlayer", "install wallet plugin", "wallet install", "add wallet to claude code", "add wallet to codex", "add wallet to hermes", "npx agentlayer", "agent-layer install".
compatibility: Requires node 24.x, npm, and python3 on the host.
metadata:
  author: lopushok9
  version: "0.1.67"
---

# AgentLayer (plugin)

AgentLayer is a crypto wallet for agents (opensource). Make payments via x402, use stablecoins, swap assets, earn yield with defi and buy tokenized stocks across the most popular chains (solana, base, ethereum).


## Use this when

- You need a local crupto wallet runtime for an AI host.
- You need install commands for OpenClaw, Claude Code, or Codex.
- You need the shortest install and onboarding flow for AgentLayer.

## System prerequisites

- `python3`
- `node` `24.x`
- `npm`

## Install flow

When the user asks you to install AgentLayer wallet, use the universal installer:

```bash
npx @agentlayer.tech/wallet install --yes
```

It detects OpenClaw, Codex, Claude Code, and Hermes, then connects every
detected host to one shared local runtime.

Use an explicit host list only when the user asks for one:

```bash
npx @agentlayer.tech/wallet install --yes --hosts codex,claude-code
```

Detection and runtime-only examples:

```bash
npx @agentlayer.tech/wallet detect --json
npx @agentlayer.tech/wallet install --yes --runtime-only
```

On an existing installation, `wallet update --yes` updates the runtime and
repairs only already-managed hosts. It must not enroll newly detected hosts or
replace wallet files/sealed secrets.

The boot key uses the native OS keystore by default (`auto`) and falls back to
a local `0600` file only when the native backend is unavailable. On macOS this
means the login Keychain, so macOS may show an access or password confirmation
during install or update. Tell the user to approve it only when they initiated
the AgentLayer command.

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


## Links

- Docs: `https://docs.agent-layer.tech`
- GitHub: `https://github.com/lopushok9/Agent-Layer`
- Blog: `https://x.com/agentlayer_ai`
