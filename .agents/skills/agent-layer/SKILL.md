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

## Universal install

```bash
npx @agentlayer.tech/wallet install --yes
```

The installer detects OpenClaw, Codex, Claude Code, and Hermes and connects
every detected host to one shared runtime.

Choose hosts explicitly when requested:

```bash
npx @agentlayer.tech/wallet install --yes --hosts codex,claude-code
npx @agentlayer.tech/wallet detect --json
npx @agentlayer.tech/wallet install --yes --runtime-only
```

---

## What the installer does

- Extracts the runtime to `~/.openclaw/agent-wallet-runtime/current`
- Creates a Python backend venv
- Installs Node deps for BTC/EVM wallet services
- Generates secrets sealed into `~/.openclaw/sealed_keys.json`
- Stores the boot key in the native OS keystore by default (`auto`), with a
  local `0600` file only as a fallback
- Provisions the first local Solana mainnet wallet
- Connects only the selected host bridges
- Patches `~/.openclaw/openclaw.json` only when OpenClaw is selected

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

Updates repair only already-managed host integrations. They do not enroll a
newly detected framework and do not replace wallet files or sealed secrets.

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

On macOS, the default native keystore is the login Keychain. macOS may show a
Keychain access or password confirmation during install or update; approve it
only when you initiated the AgentLayer command.
