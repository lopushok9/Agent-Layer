# OpenClaw Finance MCP Server

**The finance layer for AI agents.** A production-grade MCP server giving any AI agent real-time access to crypto markets, DeFi protocols, on-chain data, and blockchain identity — with zero infrastructure cost.

---

## Install 

Connect from OpenClaw or any MCP client — no setup required:

```json
{
  "mcpServers": {
    "openclaw-crypto": {
      "url": "https://agent-layer-production-852f.up.railway.app/mcp"
    }
  }
}
```

> This is a public demo instance. If you need a no API limits server, deploy your own.

---

## What It Does

AI agents need financial data. This server provides it: prices, yields, gas, wallet balances, transaction history, protocol analytics, and on-chain agent identity — all through 16 structured MCP tools with built-in caching, fallback chains, and rate limiting.

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
