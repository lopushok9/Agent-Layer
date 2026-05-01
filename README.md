![AgentLayer](logo+name.png)

# AgentLayer

AgentLayer is a beta local-first wallet and finance stack for agents.

The repository includes:

- `agent-wallet/` - the main wallet backend for AgentLayer
- `.openclaw/` - the local AgentLayer bridge layer
- `wdk-btc-wallet/` - the local Bitcoin wallet service
- `wdk-evm-wallet/` - the local EVM wallet service
- `provider-gateway/` - shared provider access for Solana RPC, Bags, and related finance reads
- `mcp-server/` - the finance and crypto MCP layer

The goal is simple:

- keep wallet secrets local
- let agents use constrained wallet capabilities
- support real onchain flows without giving agents direct key ownership

## Beta

This project is in beta.

Do not treat it as a finished production wallet stack. Test every flow before relying on it.

## Quick install

System prerequisites:

- `python3`
- `node`
- `npm`

Install from the latest GitHub release bundle:

```bash
curl -fsSL https://raw.githubusercontent.com/lopushok9/Agent-Layer/main/install-from-github.sh | sh
```

Install through npm:

```bash
npx @agentlayer.tech/wallet install --yes
```

Or install the CLI globally first:

```bash
npm install -g @agentlayer.tech/wallet
openclaw-agent-wallet install --yes
```

The npm CLI runs the same bundled installer, but uses a versioned runtime layout:

```bash
~/.openclaw/agent-wallet-runtime/releases/<version>
~/.openclaw/agent-wallet-runtime/current
```

`--yes` generates local runtime secrets when this is the first install. The installer stores `master_key` and `approval_secret` in `~/.openclaw/sealed_keys.json`; only the boot key needed to unlock that sealed bundle is written to the installed runtime `.env`.

Useful npm CLI commands:

```bash
openclaw-agent-wallet status
openclaw-agent-wallet doctor
openclaw-agent-wallet update --yes
openclaw-agent-wallet rollback
```

Install from a local clone:

```bash
sh ./setup.sh
```

If you want the installer to finish the OpenClaw plugin wiring in the same pass, provide the runtime secrets before running it:

Solana:

```bash
export AGENT_WALLET_BOOT_KEY="$(openssl rand -base64 32)"
export AGENT_WALLET_MASTER_KEY="$(openssl rand -base64 32)"
export AGENT_WALLET_APPROVAL_SECRET="$(openssl rand -base64 32)"
```
Bitcoin:

```bash
sh agent-wallet/scripts/setup_btc_wallet.sh
```

EVM:

```bash
cd wdk-evm-wallet && sh run-local.sh
```

Create a local EVM wallet binding for an OpenClaw user:

```bash
printf '%s\n' 'your-local-evm-password' | \
agent-wallet/.venv/bin/python -m agent_wallet.openclaw_cli evm-wallet-create \
  --user-id your-user-id \
  --password-stdin \
  --config-json '{"backend":"wdk_evm_local","network":"base","wdkEvmServiceUrl":"http://127.0.0.1:8081"}'
```

Unlock an existing EVM wallet binding:

```bash
printf '%s\n' 'your-local-evm-password' | \
agent-wallet/.venv/bin/python -m agent_wallet.openclaw_cli evm-wallet-unlock \
  --user-id your-user-id \
  --password-stdin \
  --config-json '{"backend":"wdk_evm_local","network":"base","wdkEvmServiceUrl":"http://127.0.0.1:8081"}'
```

That generates three fresh local secrets in the current shell session. If you prefer Python instead of `openssl`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run it three times and assign the outputs to:

- `AGENT_WALLET_BOOT_KEY`
- `AGENT_WALLET_MASTER_KEY`
- `AGENT_WALLET_APPROVAL_SECRET`

Without those secrets, the installer still lays down the runtime and installs dependencies, but it stops short of the final hardened OpenClaw config step and prints the exact `next_configure_command` you should run after secrets are available.

## Connect the MCP server

```json
{
  "mcpServers": {
    "agent-layer": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}
```

## What you get after install

If you install from GitHub release, the bundle is extracted under:

```bash
~/.openclaw/agent-wallet-runtime/current
```

The installer then does the following:

- creates `agent-wallet/.env` from `agent-wallet/.env.example` if it does not exist
- creates `agent-wallet/.venv` and installs the Python backend with `pip install -e`
- installs Node dependencies for `wdk-btc-wallet` and `wdk-evm-wallet`
- creates a minimal `~/.openclaw/openclaw.json` if one does not exist
- if the required secrets are already present, writes or updates `~/.openclaw/sealed_keys.json`
- if the required secrets are already present, patches `~/.openclaw/openclaw.json` to load the `agent-wallet` extension and point it at the installed runtime

When the installer reaches the final config step, the default plugin config is:

- `backend=solana_local`
- `network=devnet`

## What is not done automatically

The installer does not:

- create a BTC wallet
- unlock a BTC wallet
- create an EVM wallet
- unlock an EVM wallet
- start the local `wdk-btc-wallet` service
- start the local `wdk-evm-wallet` service
- expose seed phrases to the agent
- install `python3`, `node`, or `npm` for you

For Solana specifically, install alone does not make signed transactions available. You still need a readable wallet identity:

- read-only mode: `SOLANA_AGENT_PUBLIC_KEY`
- signing mode: a sealed `private_key` or `SOLANA_AGENT_KEYPAIR_PATH`

## BTC setup

The BTC path already has a one-command host bootstrap wrapper:

```bash
sh agent-wallet/scripts/setup_btc_wallet.sh
```

That flow:

- prompts for `user-id`
- prompts for `mainnet`, `testnet`, or `regtest`
- defaults to `http://127.0.0.1:8080`
- can auto-start `wdk-btc-wallet/run-local.sh` if the local service is not already healthy
- creates or unlocks the local BTC wallet binding
- patches OpenClaw config to `backend=wdk_btc_local`

BTC setup only supports localhost service URLs. The local BTC service is protected by a bearer token stored at:

```bash
~/.openclaw/wdk-btc-wallet/local-auth-token
```

If you need to reveal the BTC seed phrase later, that remains a host-side step:

```bash
sh agent-wallet/scripts/reveal_btc_seed.sh
```

## EVM setup

The EVM runtime is installed by `setup.sh`, but the host-side wallet onboarding is still a manual CLI flow.

Start the local EVM service:

```bash
cd wdk-evm-wallet && sh run-local.sh
```

Create a local EVM wallet binding for an OpenClaw user:

```bash
printf '%s\n' 'your-local-evm-password' | \
agent-wallet/.venv/bin/python -m agent_wallet.openclaw_cli evm-wallet-create \
  --user-id your-user-id \
  --password-stdin \
  --config-json '{"backend":"wdk_evm_local","network":"base","wdkEvmServiceUrl":"http://127.0.0.1:8081"}'
```

Unlock an existing EVM wallet binding:

```bash
printf '%s\n' 'your-local-evm-password' | \
agent-wallet/.venv/bin/python -m agent_wallet.openclaw_cli evm-wallet-unlock \
  --user-id your-user-id \
  --password-stdin \
  --config-json '{"backend":"wdk_evm_local","network":"base","wdkEvmServiceUrl":"http://127.0.0.1:8081"}'
```

Then switch the OpenClaw plugin config to the EVM backend:

```bash
AGENT_WALLET_BOOT_KEY='...' \
agent-wallet/.venv/bin/python agent-wallet/scripts/install_openclaw_local_config.py \
  --backend wdk_evm_local \
  --network base \
  --user-id your-user-id \
  --package-root agent-wallet \
  --extension-path .openclaw/extensions/agent-wallet \
  --python-bin agent-wallet/.venv/bin/python
```

That final config step assumes `~/.openclaw/sealed_keys.json` already exists. The normal path is to let the main installer create it by running install with `AGENT_WALLET_BOOT_KEY`, `AGENT_WALLET_MASTER_KEY`, and `AGENT_WALLET_APPROVAL_SECRET` available.

Important EVM notes:

- only localhost service URLs are supported for the OpenClaw EVM flow
- the local EVM service uses a bearer token at `~/.openclaw/wdk-evm-wallet/local-auth-token`
- the agent-facing EVM surface is intentionally narrow: balances, fee rates, receipts, transfers, Velora swaps, Aave V3 account/reserve/position flows, and Lido staking/withdrawal flows
- Velora swap and Aave V3 support are currently limited to `ethereum` and `base`
- Lido support is currently limited to `ethereum` and exposes read-only staking APR data from Lido's public API in the overview response

## Solana notes

The installer defaults the plugin to `solana_local` on `devnet`.

The Solana runtime uses hardened local secrets:

- `AGENT_WALLET_BOOT_KEY` is required by the runtime
- `master_key` and `approval_secret` should live in `~/.openclaw/sealed_keys.json`
- `AGENT_WALLET_MASTER_KEY` and `AGENT_WALLET_APPROVAL_SECRET` are provisioning inputs for installer/admin flows, not long-term runtime env

Read-only Solana mode:

```bash
export SOLANA_AGENT_PUBLIC_KEY='...'
```

Signing Solana mode can use either:

- a sealed `private_key` stored in `sealed_keys.json`
- `SOLANA_AGENT_KEYPAIR_PATH`

The default shared path already includes:

- hosted provider-gateway defaults
- shared Solana RPC path unless you override it

You only need to bring your own RPC if you want to override the default route. Supported override paths are:

- `SOLANA_RPC_URL`
- `SOLANA_RPC_URLS`
- `ALCHEMY_API_KEY`
- `HELIUS_API_KEY`

Automatic local Solana wallet creation exists, but it is off by default:

```bash
SOLANA_AUTO_CREATE_WALLET=false
```

## Security model

The core rule is:

the agent gets wallet capabilities, not wallet ownership.

That means:

- secret material stays local
- signing stays in the wallet layer
- risky writes require approval
- BTC and EVM password-gated wallet operations remain host-side

## License and community use

This repository is public and source-available under the `PolyForm Small Business License 1.0.0`.

If you are an individual developer, researcher, student, security reviewer, or hobbyist, you can:

- read and audit the code
- fork the repo
- run it locally
- modify it for yourself
- open issues and send pull requests

If you are using the project for a company, the license allows use for small businesses covered by the PolyForm thresholds. If you need rights beyond that, reach out for a separate commercial license.
