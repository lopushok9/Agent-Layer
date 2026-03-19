![OpenClaw](logo+name.png)

# OpenClaw Finance MCP Server

**The finance layer for AI agents.** A production-grade MCP server giving any AI agent real-time access to finance, crypto, DeFi protocols, on-chain data, and blockchain identity (via ERC-8004) — with zero infrastructure cost.

---

## Install 

Connect from OpenClaw or any MCP client — no setup required:

```json
{
  "mcpServers": {
    "AgentLayer": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}
```

> This is a beta version. If you need a server without API limits, deploy your own.

---

## What It Does

AI agents need financial data. This server provides it: prices, yields, gas, wallet balances, transaction history, protocol analytics, and on-chain agent identity — all through 19 structured MCP tools with built-in caching, fallback chains, and rate limiting.

No parsing HTML. No fighting APIs. Just clean JSON that agents can reason about.

---

## Tools

| Tool | Description |
|------|-------------|
| `get_crypto_prices` | Batch prices for up to 50 symbols, 24h change, volume, market cap |
| `get_market_overview` | Total market cap, BTC/ETH dominance, global volume |
| `get_trending_coins` | Top trending coins over the last 24h |
| `get_fear_greed_index` | Market sentiment score (0-100) |
| `get_defi_yields` | Top yield opportunities with chain and TVL filters |
| `get_protocol_tvl` | TVL for any protocol or top protocols by chain |
| `get_protocol_fees` | 24h fees and revenue for any DeFi protocol |
| `get_stablecoin_stats` | Stablecoin market caps, peg types, chain distribution |
| `get_wallet_balance` | Native token balance across 6 chains |
| `get_token_balances` | ERC-20 token balances for any wallet |
| `get_wallet_portfolio` | Full portfolio with native + ERC-20 + USD valuations |
| `get_token_transfers` | ERC-20 transfer history for any wallet |
| `get_transaction_history` | Full transaction history |
| `get_gas_prices` | Current gas estimates (slow/standard/fast) per chain |
| `search_crypto` | AI-powered search across crypto news and research |
| `get_agent_by_id` | ERC-8004 on-chain agent identity: owner, wallet, metadata |
| `list_erc8004_chains` | Lists chains indexed by the 8004 explorer |
| `search_erc8004_agents` | Searches ERC-8004 agents by query and chain |
| `get_erc8004_agent_profile` | Returns a normalized agent profile by chain and token ID |

---

## Architecture

```
mcp-server/
├── server.py          # FastMCP entrypoint, HTTP and stdio transport
├── config.py          # Environment-based configuration (pydantic-settings)
├── cache.py           # In-memory TTL cache with stale fallback
├── rate_limiter.py    # Sliding window rate limiter per provider
├── models.py          # Pydantic response models
├── providers/         # CoinGecko, CoinCap, DexScreener, DeFiLlama,
│                      # Alchemy, Etherscan, PublicNode RPC, Tavily, ERC-8004
└── tools/             # prices, defi, onchain, gas, sentiment, search, agents
```

**Data sources:** CoinGecko, CoinCap, DexScreener, DeFiLlama, Alternative.me, PublicNode RPC, Etherscan family, Alchemy, Tavily AI

**Price fallback chain:** CoinGecko → CoinCap → DexScreener (for DEX-only micro-caps) → stale cache

---

## Run Locally

```bash
cd mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python server.py --http --port=8765
```

Core functionality works without any API keys. For transaction history, add free explorer keys:

```bash
cp .env.example .env
# ETHERSCAN_API_KEY=...  (etherscan.io/myapikey)
# ALCHEMY_API_KEY=...    (for token balances and portfolio)
```

---

## Local Agent Wallet

This repository also includes a local OpenClaw wallet extension and Python wallet backend in `agent-wallet/` and `.openclaw/extensions/agent-wallet/`.

It is a self-hosted Solana wallet for OpenClaw agents. The agent gets a constrained tool surface for reads, previews, and approved writes, while custody and signing stay local on the operator machine.

> AgentLayer Wallet is in beta. Do not use it as your primary wallet, and always account for operational and security risks before using it.

### What It Does

- Reads wallet address, native balance, token portfolio, token prices, validators, and stake accounts
- Supports SOL transfers, SPL transfers, Jupiter swaps, native staking, stake deactivation, stake withdrawal, and devnet airdrops
- Uses a `preview -> prepare -> execute` flow for risky actions
- Keeps `prepare` non-custodial: it returns an execution plan only and never leaks signed transaction bytes
- Requires a host-issued one-time `approval_token` for `execute`
- Supports `devnet`, `testnet`, and `mainnet`

Agent-facing Jupiter `Portfolio` and `Earn` tools are currently disabled, but the backend code remains in place for a later re-enable.

### Installation Requirements

- Python 3.11+
- Local OpenClaw install
- A local secret for `AGENT_WALLET_BOOT_KEY`
- Solana RPC access:
  - public RPC works as fallback
  - for real `mainnet` usage, set your own `ALCHEMY_API_KEY`, `HELIUS_API_KEY`, `SOLANA_RPC_URL`, or `SOLANA_RPC_URLS`

### Install

```bash
cd agent-wallet
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
```

There is also a one-command installer:

```bash
python3 agent-wallet/scripts/install_agent_wallet.py
```

If you are already working with a local coding agent on this machine, that agent can run the installer for you. In practice, you can simply ask your agent to install the wallet. The agent can create the local files, patch `openclaw.json`, create the Python environment, and finish setup when the required env vars are present.

It will:

- create `agent-wallet/.env` from `.env.example` if needed
- create `agent-wallet/.venv` and install the package there by default
- create a minimal `~/.openclaw/openclaw.json` if it does not exist yet
- finish OpenClaw wallet configuration immediately if the required secret env vars are already present
- otherwise print which env vars are still missing

If you want the installer to fully configure the wallet in one pass, export at least:

```bash
export AGENT_WALLET_BOOT_KEY='...'
export AGENT_WALLET_MASTER_KEY='...'
export AGENT_WALLET_APPROVAL_SECRET='...'
```

The important boundary is that the operator still owns the secrets. The agent can execute the setup steps, but `AGENT_WALLET_BOOT_KEY` and the other required secret env vars should be chosen and provided by the user, not silently invented and hidden by the agent.

Minimal self-hosted runtime configuration:

```bash
AGENT_WALLET_BOOT_KEY=...
ALCHEMY_API_KEY=...
# or
HELIUS_API_KEY=...
```

`AGENT_WALLET_BOOT_KEY` is a local secret created by the operator. It is not a blockchain private key and not something we issue or host. It is the unlock key for `~/.openclaw/sealed_keys.json`, which stores the wallet runtime secrets in encrypted form.

Recommended generation:

```bash
openssl rand -base64 32
```

Store it in a password manager or local secrets manager. Do not commit it to Git, do not hardcode it in the repository, and do not share it with the agent as general-purpose context.

If you need a custom RPC chain instead of provider shortcuts:

```bash
SOLANA_RPC_URLS=https://your-primary-rpc.example,https://api.mainnet-beta.solana.com
```

### Security Model

- Runtime secrets are loaded from `~/.openclaw/sealed_keys.json`
- Per-user wallet encryption is mandatory
- Per-user HKDF derivation is mandatory
- Mainnet wallets are pinned by address and cannot be silently recreated
- `AGENT_WALLET_MASTER_KEY`, `AGENT_WALLET_APPROVAL_SECRET`, and `SOLANA_AGENT_PRIVATE_KEY` are not accepted as direct runtime env secrets
- `execute` requires a host-issued approval token bound to the exact operation

### OpenClaw Integration

The extension is designed for a local OpenClaw install:

- TypeScript plugin bridge: `.openclaw/extensions/agent-wallet`
- Python runtime/backend: `agent-wallet`

Typical local plugin config:

```json
{
  "plugins": {
    "allow": ["agent-wallet"],
    "entries": {
      "agent-wallet": {
        "enabled": true,
        "config": {
          "userId": "openclaw-local-user",
          "backend": "solana_local",
          "network": "devnet",
          "signOnly": false,
          "packageRoot": "/absolute/path/to/agent-wallet",
          "pythonBin": "/absolute/path/to/python"
        }
      }
    }
  }
}
```

Recommended operational flow:

1. Read with balance, portfolio, validator, and stake tools.
2. Use `preview` before any write action.
3. Use `prepare` only to build an execution plan.
4. Use `execute` only after the host issues an approval token.

For detailed wallet setup and extension docs, see `agent-wallet/README.md` and `.openclaw/extensions/agent-wallet/README.md`.

---

## Deploy to Railway

1. New Project → Deploy from GitHub
2. **Settings → Root Directory:** `mcp-server`
3. **Start Command:** `python server.py --http`
4. **Networking → Port:** `8000`
5. Add API keys as environment variables

---

## Design Principles

- **Zero base cost** — all core providers are free or keyless
- **Agents first** — structured JSON, consistent schemas, no ambiguity
- **Resilient by default** — every provider has a fallback, every response has a cache
- **Coverage without compromise** — from Bitcoin to DEX-only micro-caps via DexScreener
- **Standard protocol** — works with Claude, Cursor, Windsurf, any MCP client
