# OpenClaw Crypto MCP Server

  {                                                                                                                                                           
    "mcpServers": {                                                                                                                                           
      "openclaw-crypto": {                                                                                                                                    
        "url": "https://agent-layer-production-852f.up.railway.app/mcp"                                                                                       
      }                                                                                                                                                       
    }                                                                                                                                                         
  }

MCP server for crypto analytics — prices, DeFi yields/TVL, on-chain data, sentiment, gas prices.

**100% free-tier APIs.** No paid subscriptions required.

## Quick Start

```bash
cd mcp-server
pip install -e .
python server.py
```

The server starts in stdio mode (standard MCP transport).

## Tools (12)

| Tool | Description |
|------|-------------|
| `get_crypto_prices` | Batch prices (up to 50 symbols) with 24h change, volume, mcap |
| `get_market_overview` | Global market: total mcap, volume, BTC/ETH dominance |
| `get_trending_coins` | Trending coins in the last 24h |
| `get_fear_greed_index` | Crypto Fear & Greed Index (0-100) |
| `get_defi_yields` | Top DeFi yields with chain/TVL/stablecoin filters |
| `get_protocol_tvl` | TVL for a protocol or top protocols |
| `get_protocol_fees` | Protocol fees/revenue (24h) |
| `get_stablecoin_stats` | Stablecoin supply, peg type, chains |
| `get_wallet_balance` | Native token balance on 6 chains |
| `get_token_transfers` | ERC-20 transfers (requires explorer key) |
| `get_transaction_history` | Transaction history (requires explorer key) |
| `get_gas_prices` | Gas prices (slow/standard/fast) per chain |

## Free APIs Used

| API | Rate Limit | Key Required |
|-----|-----------|-------------|
| CoinGecko | 30/min | No |
| CoinCap | Unlimited | No |
| DeFiLlama | Unlimited | No |
| Alternative.me | Unlimited | No |
| PublicNode RPC | Unlimited | No |
| Etherscan/Arbiscan/Basescan | 100k/day | Free signup |

## Configuration

Copy `.env.example` to `.env`. Most settings have sensible defaults.

Only explorer API keys need manual setup (for `get_token_transfers` and `get_transaction_history`):

1. Go to [etherscan.io/myapikey](https://etherscan.io/myapikey)
2. Sign up (30 seconds)
3. Copy your free API key to `.env`

## Connect to Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "openclaw-crypto": {
      "command": "python",
      "args": ["/path/to/mcp-server/server.py"]
    }
  }
}
```

## Docker

```bash
cp .env.example .env
# Edit .env with your explorer keys
docker compose up -d
```

## Development

```bash
pip install -e ".[dev]"

# Interactive MCP Inspector
fastmcp dev server.py

# Tests
pytest tests/ -v

# Lint
ruff check .
```
