# OpenClaw Crypto MCP Server

  {                                                                                                                                                           
    "mcpServers": {                                                                                                                                           
      "openclaw-crypto": {                                                                                                                                    
        "url": "https://agent-layer-production-852f.up.railway.app/mcp"                                                                                       
      }                                                                                                                                                       
    }                                                                                                                                                         
  }

MCP server for crypto analytics + headless wallet ops (Turnkey) — prices, DeFi yields/TVL, on-chain data, sentiment, gas prices, wallet management.

**100% free-tier APIs.** No paid subscriptions required.

## Quick Start

```bash
cd mcp-server
pip install -e .
python server.py
```

The server starts in stdio mode (standard MCP transport).

## Tools (23)

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
| `get_curve_pools` | Curve pools by chain/registry with TVL/APY/gauge filters (base + rewards APY) |
| `get_curve_subgraph_data` | Curve chain metrics: TVL, 24h volume/fees, CRV APY |
| `get_wallet_balance` | Native token balance on 6 chains |
| `get_token_transfers` | ERC-20 transfers (requires explorer key) |
| `get_transaction_history` | Transaction history (requires explorer key) |
| `get_gas_prices` | Gas prices (slow/standard/fast) per chain |
| `turnkey_status` | Check Turnkey CLI + config readiness |
| `turnkey_create_wallet` | Create Turnkey wallet |
| `turnkey_create_ethereum_account` | Create ETH account in Turnkey wallet |
| `turnkey_list_accounts` | List wallet accounts |
| `turnkey_sign_transaction` | Sign unsigned ETH transaction |
| `turnkey_list_activities` | List organization activities (including pending consensus) |
| `turnkey_get_activity` | Get a specific activity by ID |
| `turnkey_approve_activity` | Approve activity by activity ID or fingerprint |
| `turnkey_reject_activity` | Reject activity by activity ID or fingerprint |

## Free APIs Used

| API | Rate Limit | Key Required |
|-----|-----------|-------------|
| CoinGecko | 30/min | No |
| CoinCap | Unlimited | No |
| DeFiLlama | Unlimited | No |
| Curve API | Unlimited | No |
| Alternative.me | Unlimited | No |
| PublicNode RPC | Unlimited | No |
| Etherscan/Arbiscan/Basescan | 100k/day | Free signup |

## Configuration

Copy `.env.example` to `.env`. Most settings have sensible defaults.

Only explorer API keys need manual setup (for `get_token_transfers` and `get_transaction_history`):

1. Go to [etherscan.io/myapikey](https://etherscan.io/myapikey)
2. Sign up (30 seconds)
3. Copy your free API key to `.env`

### Turnkey (VPS/headless wallet backend)

Install Turnkey CLI (binary):

```bash
curl -fsSL -o /usr/local/bin/turnkey \
  https://github.com/tkhq/tkcli/releases/download/v1.1.5/turnkey.linux-x86_64
chmod +x /usr/local/bin/turnkey
```

Configure `.env`:

```bash
TURNKEY_ENABLED=true
TURNKEY_CLI_PATH=turnkey
TURNKEY_ORGANIZATION_ID=...
TURNKEY_KEY_NAME=default
TURNKEY_ENCRYPTION_KEY_NAME=default
# optional:
# TURNKEY_KEYS_FOLDER=/path/to/.config/turnkey/keys
# TURNKEY_ENCRYPTION_KEYS_FOLDER=/path/to/.config/turnkey/encryption-keys
```

For Railway/container deployments with ephemeral filesystem, provide key material via env vars:

```bash
TURNKEY_API_PUBLIC_KEY="04ab12cd... (hex)"
TURNKEY_API_PRIVATE_KEY="9f8e7d... (hex)"
TURNKEY_ENCRYPTION_PUBLIC_KEY="04de34fa... (hex)"
TURNKEY_ENCRYPTION_PRIVATE_KEY="7c6b5a... (hex)"
```

The server will write them to `/tmp/turnkey/...` at runtime and pass proper folders to `turnkey` CLI.

Important: these values must be raw hex keys expected by `tkcli` key files (optionally `0x`-prefixed), not PEM blocks.

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
