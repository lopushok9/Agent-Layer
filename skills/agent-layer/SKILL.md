---
name: agent-layer
description: Use when installing or setting up AgentLayer wallet for an AI agent. Trigger phrases include "install agent wallet", "set up agentlayer", "install wallet plugin", "wallet install", "add wallet to claude code", "add wallet to codex", "add wallet to hermes", "npx agentlayer", "agent-layer install".
compatibility: Requires node 24.x, npm, and python3 on the host.
metadata:
  author: lopushok9
  version: "0.1.47"
---

# AgentLayer

Local-first wallet and finance stack for AI agents. Agents get constrained wallet capabilities — keys and signing stay on the host.

## Prerequisites

- `node` 24.x
- `npm`
- `python3`

---

## Install by agent type

### OpenClaw

```bash
npx @agentlayer.tech/wallet install --yes
```


---

### Claude Code

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet claude-code install --yes
```

---

### Codex

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet codex install --yes
```

---

### Hermes

```bash
npx @agentlayer.tech/wallet install --yes && npx @agentlayer.tech/wallet hermes install --yes
```

---

## What the installer does

- Extracts the runtime to `~/.openclaw/agent-wallet-runtime/current`
- Creates a Python backend venv
- Installs Node deps for BTC/EVM wallet services
- Generates secrets sealed into `~/.openclaw/sealed_keys.json`
- Provisions the first local Solana mainnet wallet
- Patches `~/.openclaw/openclaw.json` to load the plugin

Default after install: `backend=solana_local`, `network=mainnet`.

---

## Update

If CLI `>= 0.1.22`:

```bash
wallet update --yes
```

Otherwise:

```bash
npx --yes @agentlayer.tech/wallet@latest update --yes
```

Check status after:

```bash
wallet status
wallet doctor
```

---

## Optional: BTC and EVM wallets

BTC and EVM are not set up by the base installer. Run separately:

```bash
sh agent-wallet/scripts/setup_btc_wallet.sh
sh agent-wallet/scripts/setup_evm_wallet.sh
```

---

## Security model

The agent gets wallet tools, not wallet keys. Secret material stays local. Signing stays in the wallet layer. Risky writes require approval.
