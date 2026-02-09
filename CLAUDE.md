# OpenClaw Crypto Infrastructure Layer

## Vision

Transform `market-pulse` skill from a simple price checker into a comprehensive crypto infrastructure layer enabling AI agents to interact with blockchain ecosystems through analytics, on-chain data, DeFi protocols, and smart money tracking.

## Current State Analysis

### What We Have (v1.0 - Prompt-Only Skill)

**Architecture:**
```
User → Agent → WebFetch/WebSearch → Parse → Response
```

**Features:**
- Basic price queries (CoinGecko API)
- Market sentiment (Fear & Greed Index)
- DeFi yields (web scraping DeFiLlama)
- Stock indices (web search)

**Limitations:**
1. **Performance:** 500-2000ms latency per query (HTTP round-trips)
2. **No caching:** Repeated "BTC price?" queries hit API every time
3. **No batching:** "BTC ETH SOL" = 3 separate requests
4. **Rate limits:** CoinGecko free tier easily exhausted
5. **Limited data:** No on-chain analytics, no smart money tracking
6. **No streaming:** Can't subscribe to real-time updates

## Architectural Learnings from Best Practices

### ElizaOS Otaku Pattern Analysis

**Key Innovations:**
- **Plugin-based architecture:** Each data source = separate plugin with typed actions
- **WebSocket streaming:** Long-running operations (portfolio analysis) stream progress
- **React Query caching:** Client-side deduplication
- **Safety-first validation:** Always verify wallet balance before on-chain operations
- **Multi-step reasoning:** Agents decompose complex queries into sequential actions

**Example Architecture:**
```typescript
Agent → Plugin Interface → External API → Formatted Response
         ↓
    TypeScript types enforce action contracts
```

### Moltbook API Design Principles

**Agent-Friendly Patterns:**
- **Stateless bearer tokens:** No session management, works across distributed processes
- **Rate limiting in headers:** `X-RateLimit-Remaining` enables adaptive request planning
- **Structured JSON only:** No HTML parsing required
- **Immediate API key issuance:** Zero waiting periods
- **Transparent ranking:** Community-driven visibility via karma/votes

## OpenClaw Extension Mechanisms

### Three Integration Approaches

| Mechanism | Execution | Latency | Language | Use Case |
|-----------|-----------|---------|----------|----------|
| **Skills** | Prompt-only (current) | 500-2000ms | Markdown | Quick prototypes, behavior docs |
| **Plugins** | In-process code | <10ms | TypeScript | High-performance data layer |
| **MCP Servers** | External service | 50-200ms | Any (Python/Rust) | Heavy compute, external services |

### When to Use Each

**Skills (`.md` files):**
- ✅ Easy deployment (copy to `~/.openclaw/skills/`)
- ✅ No code execution required
- ✅ Version-controlled documentation
- ❌ Slow (every query = HTTP call)
- ❌ No state/caching

**Plugins (TypeScript modules):**
- ✅ In-process = instant access
- ✅ Can register Gateway RPC methods
- ✅ Background services (WebSocket subscriptions)
- ✅ Shared state across agent sessions
- ❌ Requires npm packaging
- ❌ Tied to OpenClaw runtime

**MCP Servers (external processes):**
- ✅ Language-agnostic (Python for crypto libs)
- ✅ Isolated (crash won't kill Gateway)
- ✅ Reusable across AI platforms (Claude Desktop, Cursor)
- ✅ Easier deployment (single server, multiple clients)
- ❌ Network latency (HTTP/SSE transport)

## Recommended Architecture

### Hybrid Approach: Skill + MCP + (Future) Plugin

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenClaw Agent                            │
├─────────────────────────────────────────────────────────────┤
│  market-pulse Skill (SKILL.md)                              │
│  - Defines behavior, response formats                        │
│  - Orchestrates tool calls                                   │
│  - Caching rules and batching logic                          │
└────────────┬────────────────────────────────────────────────┘
             │
             ├─→ MCP Server: openclaw-crypto-mcp (Python)
             │   ├─ Redis cache layer (30s price, 5min yields)
             │   ├─ Multi-source aggregation
             │   │  ├─ CoinAPI (MCP-compatible, 400+ exchanges)
             │   │  ├─ Nansen (labeled wallets, smart money)
             │   │  ├─ Zerion (38+ chains, portfolio data)
             │   │  ├─ DeFiLlama (protocol TVL, yields)
             │   │  └─ Amberdata (AI-driven intelligence)
             │   └─ Tools:
             │      ├─ crypto.get_prices (batch support)
             │      ├─ crypto.get_smart_money_flows
             │      ├─ crypto.get_portfolio
             │      ├─ crypto.get_defi_yields
             │      └─ crypto.analyze_wallet
             │
             └─→ (Future) Plugin: openclaw-crypto-plugin
                 ├─ Real-time WebSocket subscriptions
                 ├─ In-memory cache (ultra-low latency)
                 └─ Price alerts / notifications
```

### Performance Comparison

| Implementation | Latency | Caching | Batching | Complexity |
|----------------|---------|---------|----------|------------|
| **Current (WebFetch only)** | 500-2000ms | ❌ | ❌ | Low |
| **Skill + MCP** | 50-200ms | ✅ Redis | ✅ | Medium |
| **Skill + MCP + Plugin** | 10-50ms | ✅ Multi-layer | ✅ | High |

## Implementation Roadmap

### Phase 1: Enhanced Skill (Quick Wins) ✅ CURRENT

**Goal:** Improve current `SKILL.md` without code changes

**Actions:**
- [x] Add caching rules to prompt ("check memory first")
- [ ] Document batching patterns ("combine BTC ETH SOL queries")
- [ ] Specify rate limit fallback strategies
- [ ] Add data freshness guidelines (prices: 30s, yields: 5min)
- [ ] Document structured error handling
- [ ] Recommend better APIs (CoinAPI > CoinGecko)

**Expected Impact:** 20-30% fewer redundant API calls through prompt optimization

---

### Phase 2: MCP Server Foundation 🎯 NEXT

**Goal:** Build `openclaw-crypto-mcp` server in Python

**Architecture:**
```
openclaw-crypto-mcp/
├── src/
│   ├── server.py              # MCP server entry point
│   ├── cache.py               # Redis cache layer with TTL
│   ├── config.py              # API keys, rate limits
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── coinapi.py         # Primary price source
│   │   ├── nansen.py          # Smart money tracking
│   │   ├── zerion.py          # Multi-chain portfolios
│   │   ├── defillama.py       # DeFi protocol data
│   │   └── amberdata.py       # AI-driven intelligence
│   └── tools/
│       ├── prices.py          # get_prices, get_market_global
│       ├── onchain.py         # get_wallet_balance, get_tx_history
│       ├── defi.py            # get_protocol_tvl, get_yields
│       ├── smart_money.py     # get_whale_movements, get_flows
│       └── portfolio.py       # analyze_portfolio, get_pnl
├── mcp.json                   # MCP manifest
├── requirements.txt           # Dependencies
├── Dockerfile                 # Container deployment
└── README.md                  # Setup instructions
```

**Core Tools to Implement:**

1. **`crypto.get_prices`**
   - Input: `symbols: string[]` (e.g., `["BTC", "ETH", "SOL"]`)
   - Output: `{ symbol, price, change_24h, volume_24h, timestamp }`
   - Cache: 30 seconds
   - Source: CoinAPI (fallback: CoinGecko)

2. **`crypto.get_smart_money_flows`**
   - Input: `chain: string, timeframe: string`
   - Output: Labeled wallet movements (Nansen data)
   - Cache: 5 minutes
   - Source: Nansen API

3. **`crypto.analyze_portfolio`**
   - Input: `wallets: string[], chains: string[]`
   - Output: Aggregated balance, PnL, allocation
   - Cache: 2 minutes
   - Source: Zerion API

4. **`crypto.get_defi_yields`**
   - Input: `limit: number, min_tvl: number`
   - Output: Top protocols with APY, TVL, risk score
   - Cache: 10 minutes
   - Source: DeFiLlama

5. **`crypto.get_whale_movements`**
   - Input: `token: string, min_amount: number`
   - Output: Recent large transactions with labeled addresses
   - Cache: 1 minute
   - Source: Nansen + Etherscan

**Caching Strategy:**
```python
# cache.py
class CacheLayer:
    def __init__(self, redis_url):
        self.redis = Redis.from_url(redis_url)

    async def get_or_fetch(self, key, ttl, fetch_fn):
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)

        data = await fetch_fn()
        await self.redis.setex(key, ttl, json.dumps(data))
        return data
```

**Rate Limiting:**
```python
# providers/coinapi.py
class RateLimiter:
    def __init__(self, max_calls, window_seconds):
        self.max_calls = max_calls
        self.window = window_seconds
        self.calls = deque()

    async def acquire(self):
        now = time.time()
        # Remove old calls outside window
        while self.calls and self.calls[0] < now - self.window:
            self.calls.popleft()

        if len(self.calls) >= self.max_calls:
            # Wait until oldest call expires
            sleep_time = self.calls[0] + self.window - now
            await asyncio.sleep(sleep_time)

        self.calls.append(now)
```

**Deployment:**
- Docker container on Fly.io / Railway
- Single server, multiple OpenClaw clients
- Environment variables for API keys
- Health check endpoint for monitoring

**Expected Impact:**
- 70-80% latency reduction (50-200ms vs 500-2000ms)
- 90%+ cache hit rate for repeated queries
- Batch support (1 call for multiple symbols)
- Professional data sources (Nansen, Zerion)

---

### Phase 3: Advanced Analytics 🔮 FUTURE

**Goal:** Deep on-chain intelligence and multi-chain analysis

**New Tools:**

6. **`crypto.track_smart_contract`**
   - Monitor contract events, state changes
   - Source: Alchemy/Infura WebHooks

7. **`crypto.analyze_liquidity`**
   - DEX liquidity depth, impermanent loss calculator
   - Source: Uniswap/Curve APIs

8. **`crypto.get_token_metrics`**
   - Holder distribution, supply dynamics, vesting schedules
   - Source: Token Terminal, Dune Analytics

9. **`crypto.find_arbitrage`**
   - Cross-DEX price differences, bridge opportunities
   - Real-time calculation engine

10. **`crypto.assess_protocol_risk`**
    - Smart contract audits, TVL history, exploit history
    - Source: DeFiSafety, CertiK

---

### Phase 4: Plugin for Real-Time 🚀 FUTURE

**Goal:** Ultra-low latency for price-sensitive operations

**Use Cases:**
- Price alerts ("notify when BTC > $100k")
- Portfolio rebalancing signals
- MEV opportunity detection
- Liquidation risk monitoring

**Architecture:**
```typescript
// openclaw-crypto-plugin/src/index.ts
export default function (api) {
  // Background WebSocket service
  api.registerService({
    name: "crypto-stream",
    start: async () => {
      const ws = connectToCoinAPI();

      ws.on('ticker', (data) => {
        // Update in-memory cache
        cache.set(`price:${data.symbol}`, data);

        // Check price alerts
        checkAlerts(data.symbol, data.price);
      });
    }
  });

  // Instant tool for agents
  api.registerTool({
    name: "get_price_instant",
    description: "Ultra-fast price lookup from in-memory cache",
    execute: async (symbol) => {
      return cache.get(`price:${symbol}`);
    }
  });

  // Price alert registration
  api.registerGatewayMethod("crypto.set_alert", ({ symbol, price, condition }) => {
    alerts.add({ symbol, price, condition });
  });
}
```

**Expected Impact:**
- <10ms response time (in-memory)
- Real-time streaming updates
- Event-driven notifications
- Background monitoring without agent polling

---

## Data Source Strategy

### Tier 1: Core Market Data (Phase 2)

| Source | Purpose | Priority | Cost |
|--------|---------|----------|------|
| **CoinAPI** | Real-time prices, 400+ exchanges, MCP-compatible | 🔴 Critical | $79-499/mo |
| **CoinGecko** | Fallback prices, free tier | 🟡 Backup | Free |
| **Alternative.me** | Fear & Greed Index | 🟢 Nice-to-have | Free |
| **DeFiLlama** | Protocol TVL, yields | 🔴 Critical | Free |

### Tier 2: On-Chain Intelligence (Phase 2-3)

| Source | Purpose | Priority | Cost |
|--------|---------|----------|------|
| **Nansen** | Labeled wallets, smart money tracking | 🔴 Critical | Enterprise |
| **Zerion API** | Multi-chain portfolio (38+ chains) | 🔴 Critical | $299-999/mo |
| **Etherscan** | Transaction verification, contract data | 🟡 Backup | Free-$99/mo |
| **Dune Analytics** | Custom on-chain queries | 🟢 Nice-to-have | Free-$390/mo |

### Tier 3: Advanced Features (Phase 3-4)

| Source | Purpose | Priority | Cost |
|--------|---------|----------|------|
| **Amberdata** | AI-driven market intelligence | 🟡 Backup | Enterprise |
| **Token Terminal** | Fundamental metrics (revenue, fees) | 🟢 Nice-to-have | $149-999/mo |
| **DeFiSafety** | Protocol risk scores | 🟢 Nice-to-have | Free |
| **Blocknative** | Gas optimization, MEV protection | 🔵 Future | Custom |

### Cost Optimization Strategy

---

## 💰 Cost Optimization & Free Tier Strategy

> **TL;DR:** Start with $0/month using 100% free APIs. Scale only when necessary.

### Free Tier Services (Zero Cost)

#### **Crypto Prices - NO API KEY REQUIRED**

| Service | Rate Limit | Auth Required | Coverage | Best For |
|---------|------------|---------------|----------|----------|
| **CoinGecko Demo** | 30/min, 10k/month | ❌ No key | 13k+ coins | Primary source |
| **CoinCap** | Unlimited | ❌ No key | Top 2000 | Fallback |
| **CoinPaprika** | 20k/month | ❌ No key | Top 2000 | Alternative |

**Endpoints:**
```bash
# CoinGecko - Works WITHOUT key!
https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true

# CoinCap - No key needed
https://api.coincap.io/v2/assets/bitcoin

# CoinPaprika - No key
https://api.coinpaprika.com/v1/tickers/btc-bitcoin
```

#### **DeFi Data - COMPLETELY FREE & UNLIMITED** 🎉

| Service | Rate Limit | Auth | What You Get |
|---------|------------|------|--------------|
| **DeFiLlama** | UNLIMITED | ❌ No key | TVL, yields, fees, volumes, bridge data |

**Endpoints:**
```bash
# ALL FREE, NO KEYS:
https://api.llama.fi/protocols              # All protocol TVLs
https://yields.llama.fi/pools               # All pool yields with APY
https://api.llama.fi/tvl/ethereum           # Chain-specific TVL
https://stablecoins.llama.fi/stablecoins    # Stablecoin data
https://api.llama.fi/summary/fees/aave      # Protocol fees
```

#### **On-Chain Data - Public RPC (No Keys, No Limits)**

| Provider | Chains | Rate Limit | Auth |
|----------|--------|------------|------|
| **PublicNode (Grove)** | 70+ chains | None | ❌ No key |
| **Pocket Network** | 60+ chains | None | ❌ No key |
| **Ankr** | 80+ chains | Free tier | ⚠️ Key (free) |

**Endpoints:**
```javascript
// NO KEYS REQUIRED!
const endpoints = {
  ethereum: "https://ethereum-rpc.publicnode.com",
  base: "https://base-rpc.publicnode.com",
  arbitrum: "https://arbitrum-one-rpc.publicnode.com",
  polygon: "https://polygon-bor-rpc.publicnode.com",
  optimism: "https://optimism-rpc.publicnode.com",
  bsc: "https://bsc-rpc.publicnode.com"
};

// Read wallet balances, token transfers, contract calls - all FREE
```

#### **Blockchain Explorers - Free Tier (100k calls/day each)**

| Explorer | Chain | Daily Limit | Signup Time |
|----------|-------|-------------|-------------|
| **Etherscan** | Ethereum | 100,000 | Instant |
| **Arbiscan** | Arbitrum | 100,000 | Instant |
| **Basescan** | Base | 100,000 | Instant |
| **BscScan** | BSC | 100,000 | Instant |

**Setup:**
1. Visit etherscan.io/myapikey
2. Sign up (30 seconds)
3. Get free API key instantly
4. Repeat for other chains

#### **Market Sentiment - Free**

| Service | Data | Auth |
|---------|------|------|
| **Alternative.me** | Fear & Greed Index | ❌ No key |

```bash
curl "https://api.alternative.me/fng/?limit=1"
# {"data":[{"value":"72","value_classification":"Greed"}]}
```

---

### Free Stack Capacity Analysis

**With Smart Caching (30s TTL, 80% hit rate):**

```python
# CoinGecko Free: 30 calls/min = 43,200 calls/day
# With 80% cache hit rate:
actual_api_calls_per_user = 10 queries * 0.2 = 2 API calls

# Capacity:
users_per_day = 43,200 / 2 = 21,600 users/day

# WITHOUT caching:
users_per_day = 43,200 / 10 = 4,320 users/day

# Cache ROI: 5x capacity increase
```

**Free Stack Capacity:**
- ✅ 10,000-20,000 queries/day (price data)
- ✅ Unlimited DeFi yields/TVL
- ✅ Unlimited on-chain reads
- ✅ 100,000 explorer calls/day per chain

---

### Paid Tier Comparison

#### **When Free Isn't Enough**

| Milestone | Symptom | Solution | Monthly Cost |
|-----------|---------|----------|--------------|
| **1-10k users/mo** | Rate limits <3/day | Aggressive caching + CDN | $0-10 |
| **10-50k users/mo** | Rate limits daily | CoinGecko Analyst | $129 |
| **50k+ users/mo** | Need historical data | + CoinAPI Startup | $208 |
| **Enterprise** | Need smart money | + Nansen | Custom |

#### **Budget-Friendly Stack ($10-150/month)**

| Service | Plan | Cost/mo | What You Get | When to Add |
|---------|------|---------|--------------|-------------|
| **QuickNode** | Build | $9 | Better RPC, multiple chains | Free RPC slow |
| **NOWNodes** | Starter | $29 | 100k requests/day | Need more RPC calls |
| **CoinGecko** | Analyst | $129 | 500/min, 500k/month | Hitting rate limits |

#### **Professional Stack ($200-500/month)**

| Service | Cost/mo | Critical Feature |
|---------|---------|------------------|
| **CoinAPI** | $79 | 400+ exchanges, historical OHLCV |
| **Alchemy** | $49 | Webhooks, better reliability |
| **Zerion** | $299 | 38+ chains portfolio data |
| **Etherscan Pro** | $99 | Higher limits, priority support |

#### **Enterprise Stack ($1000+/month)**

Only add when generating significant revenue:
- **Nansen** (custom pricing) - Smart money tracking
- **Amberdata** (custom) - AI-driven intelligence
- **The Graph** (pay-per-query) - Decentralized indexing
- **Token Terminal** ($999/mo) - Fundamental metrics

---

### Cost Optimization Techniques

#### **1. Aggressive Caching Strategy**

```python
# .env configuration
CACHE_TTL_PRICES=30          # 30s (30x fewer API calls)
CACHE_TTL_DEFI_YIELDS=300    # 5min (60x fewer)
CACHE_TTL_PROTOCOL_TVL=600   # 10min (120x fewer)
CACHE_TTL_FEAR_GREED=3600    # 1hr (720x fewer)

# Result: 90%+ reduction in API calls
```

#### **2. Request Batching**

```python
# BAD: 10 API calls
for coin in ["BTC", "ETH", "SOL", ...]:
    price = fetch_price(coin)

# GOOD: 1 API call (CoinGecko supports 250 coins per request)
prices = fetch_prices(["BTC", "ETH", "SOL", ...])

# Savings: 90% fewer API calls
```

#### **3. Smart Fallback Chain**

```python
async def get_prices(symbols):
    # Try free source first
    try:
        return await coingecko_free.fetch(symbols)
    except RateLimitError:
        # Return stale cache (5min old acceptable)
        cached = await cache.get_stale(symbols, max_age=300)
        if cached:
            return {**cached, "source": "cache-stale"}
        # Fallback to alternative free source
        return await coincap.fetch(symbols)
```

#### **4. Rate Limit Awareness**

```python
class AdaptiveRateLimiter:
    """Track remaining quota and adjust behavior"""

    def __init__(self, max_per_min=30):
        self.remaining = max_per_min
        self.reset_time = time.time() + 60

    async def check_quota(self):
        if self.remaining < 5:  # <20% remaining
            logger.warning("Approaching rate limit, enabling aggressive cache")
            cache.extend_ttl(multiplier=2)  # Double cache TTL
```

#### **5. Use Public RPC Instead of APIs**

```python
# EXPENSIVE: Use paid API for wallet balance
balance = await nansen.get_wallet_balance(address)  # $$$ per call

# FREE: Query blockchain directly via public RPC
from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://ethereum-rpc.publicnode.com"))
balance = w3.eth.get_balance(address)  # $0 per call
```

---

### Recommended Implementation Phases

#### **Phase 0: MVP (Month 1-2)** - $0/month

```yaml
Stack:
  prices: CoinGecko Demo (30/min, no key)
  fallback: CoinCap (unlimited, no key)
  defi: DeFiLlama (unlimited, no key)
  rpc: PublicNode (unlimited, no key)
  explorers: Etherscan Free (100k/day, free key)
  sentiment: Alternative.me (no key)

Optimizations:
  - 30s price cache
  - 5min DeFi cache
  - Request batching
  - Stale cache fallback

Capacity: 10k-20k queries/day
Cost: $0
Users: 100-1000 monthly
```

#### **Phase 1: Growth (Month 3-6)** - $10-150/month

```yaml
Add when:
  - Hitting rate limits >3x/day
  - Users complaining about "slow" responses

Upgrades:
  - CoinGecko Analyst ($129) OR
  - Aggressive caching + CDN ($10)

Capacity: 50k-100k queries/day
Cost: $10-150
Users: 1k-10k monthly
```

#### **Phase 2: Scale (Month 6+)** - $200-500/month

```yaml
Add when:
  - Generating revenue (>$500/mo)
  - Need advanced features

Stack:
  - CoinAPI Startup ($79) - Historical data
  - Alchemy Growth ($49) - Better RPC
  - Keep free tiers as fallbacks

Capacity: 500k+ queries/day
Cost: $200-500
Users: 10k-50k monthly
Revenue: $1000+/month
```

---

### ROI Calculator

```python
# Scenario: 1000 active users/month
# Avg 20 queries per user = 20,000 queries/month

# Option A: All Paid APIs (no caching)
cost_per_query = $0.01  # Industry average
monthly_cost = 20000 * 0.01 = $200

# Option B: Free + Smart Caching (80% hit rate)
api_calls = 20000 * 0.2 = 4000
monthly_cost = $0  # Within free tier limits

# Savings: $200/month or $2400/year
# Break-even: Can support 1000 users for FREE
```

---

### Quick Start: Zero Cost Setup

**5-Minute Setup (No Credit Card):**

1. **Copy `.env.example` to `.env`**
2. **Sign up for free explorer keys:**
   - Etherscan: https://etherscan.io/myapikey (30 seconds)
   - Arbiscan: https://arbiscan.io/myapikey (30 seconds)
   - Basescan: https://basescan.org/myapikey (30 seconds)
3. **Everything else works WITHOUT keys!**

```bash
# Your .env for FREE tier:
COINGECKO_API_URL=https://api.coingecko.com/api/v3
DEFILLAMA_BASE_URL=https://api.llama.fi
ETH_RPC_URL=https://ethereum-rpc.publicnode.com
ETHERSCAN_API_KEY=YourFreeKeyHere  # Only key needed!
CACHE_TTL_PRICES=30
USE_IN_MEMORY_CACHE=true
```

4. **Deploy to Fly.io free tier** (512MB RAM, 3GB storage)
5. **Connect to OpenClaw via MCP**

**Total cost: $0/month**
**Capacity: 10,000+ queries/day**
**Setup time: 5 minutes**

---

### When to Upgrade (Decision Matrix)

| Metric | Free Tier OK | Consider Paid | Must Upgrade |
|--------|--------------|---------------|--------------|
| **Daily API errors** | <3 | 3-10 | >10 |
| **Cache hit rate** | >80% | 60-80% | <60% |
| **Monthly users** | <1k | 1k-10k | >10k |
| **Revenue/month** | $0 | $100-500 | >$500 |
| **Avg response time** | <500ms | 500-1000ms | >1000ms |
| **Need historical data** | No | Nice to have | Critical |
| **Need smart money** | No | Nice to have | Critical |

**Rule of Thumb:** Upgrade when free tier limits your growth OR when you're making money.

---

**Free Tier Stack (MVP):**
- CoinGecko Demo (30/min, no key)
- CoinCap (unlimited, no key)
- DeFiLlama (unlimited, no key)
- Public RPC (unlimited, no key)
- Etherscan basic (100k/day, free key)
- Alternative.me (no key)
- **Monthly Cost: $0**
- **Capacity: 10k-20k queries/day with caching**

**Professional Stack (~$200-500/mo):**
- CoinAPI Startup ($79/mo)
- Alchemy Growth ($49/mo)
- Zerion Standard ($299/mo)
- Keep free tiers as fallbacks
- **Monthly Cost: $427**
- **Capacity: 500k+ queries/day**

**Enterprise Stack (custom pricing):**
- Nansen Enterprise (custom)
- Amberdata Intelligence (custom)
- CoinAPI Premium ($499/mo)
- Zerion Business ($999/mo)
- **Monthly Cost: $2000+**
- **Capacity: Unlimited with dedicated support**

## Technical Implementation Details

### MCP Server Technology Stack

```yaml
Language: Python 3.11+
Framework: FastMCP (Anthropic's MCP SDK)
Cache: Redis 7+ (or in-memory fallback)
HTTP Client: httpx (async)
Data Validation: Pydantic v2
Error Tracking: Sentry
Monitoring: Prometheus + Grafana
Deployment: Docker + Fly.io/Railway
```

### Key Dependencies

```txt
# requirements.txt
fastmcp>=0.2.0
redis>=5.0.0
httpx>=0.25.0
pydantic>=2.0.0
python-dotenv>=1.0.0
sentry-sdk>=1.40.0
prometheus-client>=0.19.0
```

### Configuration Management

> **See `.env.example`** for complete configuration template with free and paid tier options.

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # === FREE TIER APIs (no keys required) ===
    coingecko_api_url: str = "https://api.coingecko.com/api/v3"
    coincap_api_url: str = "https://api.coincap.io/v2"
    defillama_base_url: str = "https://api.llama.fi"
    defillama_yields_url: str = "https://yields.llama.fi"

    # Public RPC endpoints (no keys)
    eth_rpc_url: str = "https://ethereum-rpc.publicnode.com"
    base_rpc_url: str = "https://base-rpc.publicnode.com"
    arbitrum_rpc_url: str = "https://arbitrum-one-rpc.publicnode.com"

    # Blockchain explorers (free tier keys)
    etherscan_api_key: str  # Get free at etherscan.io/myapikey
    arbiscan_api_key: str   # Get free at arbiscan.io/myapikey
    basescan_api_key: str   # Get free at basescan.org/myapikey

    # === PAID TIER APIs (optional) ===
    coinapi_key: str | None = None      # $79/mo for Startup plan
    nansen_key: str | None = None       # Enterprise pricing
    zerion_key: str | None = None       # $299/mo for Standard
    alchemy_key: str | None = None      # $49/mo for Growth

    # Redis (or in-memory for dev)
    redis_url: str = "redis://localhost:6379"
    use_in_memory_cache: bool = True    # Set False for production

    # Cache TTLs (seconds) - optimized for cost savings
    cache_ttl_price: int = 30           # 30s (90% API call reduction)
    cache_ttl_defi: int = 300           # 5min
    cache_ttl_onchain: int = 60         # 1min

    # Rate Limits (calls per minute)
    rate_limit_coingecko_free: int = 30  # Free tier limit
    rate_limit_coinapi: int = 100        # Paid tier (if enabled)
    rate_limit_nansen: int = 20          # Enterprise tier

    class Config:
        env_file = ".env"

settings = Settings()
```

### Error Handling Strategy

```python
# tools/prices.py
async def get_prices(symbols: list[str]) -> list[PriceData]:
    try:
        # Try primary source
        return await coinapi.fetch_prices(symbols)
    except RateLimitError:
        # Fallback to cache (allow stale data)
        cached = await cache.get_stale(symbols)
        if cached:
            logger.warning(f"Rate limited, returning stale cache")
            return cached
        raise
    except APIError as e:
        # Try fallback source
        logger.error(f"CoinAPI failed: {e}, trying CoinGecko")
        return await coingecko.fetch_prices(symbols)
    except Exception as e:
        # Last resort: return empty with error message
        logger.exception(f"All sources failed: {e}")
        raise ToolError(f"Unable to fetch prices: {str(e)}")
```

### Monitoring & Observability

```python
# server.py
from prometheus_client import Counter, Histogram

# Metrics
tool_calls = Counter('mcp_tool_calls_total', 'Total tool calls', ['tool_name'])
tool_duration = Histogram('mcp_tool_duration_seconds', 'Tool execution time', ['tool_name'])
cache_hits = Counter('mcp_cache_hits_total', 'Cache hit rate', ['key_type'])
api_errors = Counter('mcp_api_errors_total', 'API errors', ['source', 'error_type'])

@tool("crypto.get_prices")
async def get_prices(symbols: list[str]):
    tool_calls.labels(tool_name="get_prices").inc()

    with tool_duration.labels(tool_name="get_prices").time():
        # Check cache first
        cache_key = f"prices:{','.join(symbols)}"
        cached = await cache.get(cache_key)

        if cached:
            cache_hits.labels(key_type="prices").inc()
            return cached

        # Fetch and cache
        try:
            data = await fetch_prices(symbols)
            await cache.set(cache_key, data, ttl=30)
            return data
        except Exception as e:
            api_errors.labels(source="coinapi", error_type=type(e).__name__).inc()
            raise
```

## Testing Strategy

### Unit Tests
```python
# tests/test_prices.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_get_prices_cached():
    cache = AsyncMock()
    cache.get.return_value = [{"symbol": "BTC", "price": 67000}]

    result = await get_prices(["BTC"], cache=cache)

    assert result[0]["symbol"] == "BTC"
    assert cache.get.called
    assert not api_client.fetch.called  # Should not hit API

@pytest.mark.asyncio
async def test_get_prices_fallback_on_rate_limit():
    primary = AsyncMock(side_effect=RateLimitError())
    fallback = AsyncMock(return_value=[{"symbol": "BTC", "price": 66500}])

    with patch('coinapi.fetch', primary), patch('coingecko.fetch', fallback):
        result = await get_prices(["BTC"])

    assert result[0]["price"] == 66500
    assert fallback.called
```

### Integration Tests
```python
# tests/integration/test_mcp_server.py
from mcp.client import Client

async def test_full_price_flow():
    client = Client("http://localhost:3000/mcp")

    # Should return cached data on second call
    result1 = await client.call("crypto.get_prices", {"symbols": ["BTC"]})
    result2 = await client.call("crypto.get_prices", {"symbols": ["BTC"]})

    assert result1 == result2  # Same data from cache
    assert "price" in result1[0]
    assert "timestamp" in result1[0]
```

## Security Considerations

### API Key Management
- **Never commit** API keys to git
- Use environment variables or secret management (Doppler, AWS Secrets Manager)
- Rotate keys quarterly
- Use separate keys for dev/staging/prod

### Rate Limiting
- Implement client-side rate limiting to prevent quota exhaustion
- Use exponential backoff for retries
- Monitor remaining quota via API headers

### Data Privacy
- **No PII storage** — only public blockchain addresses
- Log aggregation should exclude sensitive data
- GDPR compliance: allow users to delete cached wallet data

### Input Validation
```python
from pydantic import BaseModel, Field, validator

class GetPricesInput(BaseModel):
    symbols: list[str] = Field(..., min_items=1, max_items=50)

    @validator('symbols')
    def validate_symbols(cls, v):
        for symbol in v:
            if not symbol.isalnum() or len(symbol) > 10:
                raise ValueError(f"Invalid symbol: {symbol}")
        return [s.upper() for s in v]
```

## Success Metrics

### Performance KPIs
- **P50 latency:** <100ms (currently 500-2000ms)
- **P95 latency:** <300ms
- **Cache hit rate:** >85%
- **API error rate:** <1%

### Cost Efficiency
- **API calls saved:** >80% via caching
- **Cost per 1000 queries:** <$0.10 (with CoinAPI)

### User Experience
- **Batch support:** 90% of multi-symbol queries use single API call
- **Stale data fallback:** 99% uptime even during API outages

## Migration Path

### From Current Skill to MCP

**Week 1-2: MCP Server Core**
- [ ] Set up Python project structure
- [ ] Implement basic MCP server with FastMCP
- [ ] Add Redis caching layer
- [ ] Integrate CoinAPI for prices
- [ ] Deploy to Fly.io

**Week 3-4: Advanced Tools**
- [ ] Add Nansen integration (smart money)
- [ ] Add Zerion integration (portfolios)
- [ ] Add DeFiLlama integration (yields)
- [ ] Implement rate limiting and fallbacks

**Week 5-6: OpenClaw Integration**
- [ ] Install openclaw-mcp-plugin
- [ ] Configure MCP server connection
- [ ] Update SKILL.md to use MCP tools
- [ ] Test full flow in OpenClaw

**Week 7-8: Documentation & Monitoring**
- [ ] Write deployment guide
- [ ] Set up Prometheus metrics
- [ ] Create Grafana dashboards
- [ ] Write user documentation

### Backward Compatibility

The skill will support **graceful degradation**:
```markdown
## Data Fetching Strategy (SKILL.md)

1. **Try MCP first** (if available):
   - `mcp.call("crypto.get_prices", ["BTC", "ETH"])`
   - Fast, cached, batch support

2. **Fallback to WebFetch**:
   - `WebFetch: https://api.coingecko.com/...`
   - Works without MCP server

3. **Last resort: WebSearch**:
   - `WebSearch: "bitcoin price today"`
   - Always available, less structured
```

## Future Vision: Full Crypto Agent Layer

### Phase 5: Transaction Capabilities (Read-Write)

**Goal:** Enable agents to execute on-chain actions (with user approval)

**Capabilities:**
- Wallet connection (WalletConnect, Metamask)
- Transaction simulation (Tenderly)
- Gas optimization (Blocknative)
- Multi-chain swaps (1inch, LiFi)
- DeFi interactions (lending, staking, LP)

**Safety First:**
- All transactions require explicit user approval
- Simulation before execution
- Slippage protection
- Transaction monitoring

### Phase 6: Autonomous Trading Strategies

**Goal:** AI-driven portfolio management

**Features:**
- Portfolio rebalancing based on risk models
- Yield farming optimization
- Automated DCA (dollar-cost averaging)
- Stop-loss / take-profit automation
- Tax-loss harvesting

**Guardrails:**
- User-defined risk limits
- Whitelist of approved protocols
- Daily transaction caps
- Emergency pause mechanism

---

## Resources & References

### Documentation
- [OpenClaw Plugin Architecture](https://docs.openclaw.ai/tools/plugin)
- [OpenClaw MCP Plugin](https://github.com/lunarpulse/openclaw-mcp-plugin)
- [FastMCP SDK](https://github.com/anthropics/fastmcp)
- [Model Context Protocol Spec](https://modelcontextprotocol.io)

### Best Practice Examples
- [ElizaOS Otaku](https://github.com/elizaOS/otaku) — Crypto analytics infrastructure
- [Moltbook API](https://github.com/moltbook/api) — Agent-friendly API design

### Data Provider Docs
- [CoinAPI Documentation](https://docs.coinapi.io)
- [Nansen API](https://docs.nansen.ai)
- [Zerion API](https://docs.zerion.io)
- [DeFiLlama API](https://defillama.com/docs/api)
- [Amberdata](https://docs.amberdata.io)

### Deployment Guides
- [Fly.io Python Apps](https://fly.io/docs/languages-and-frameworks/python/)
- [Railway Python Deployment](https://docs.railway.app/guides/python)
- [Redis Caching Strategies](https://redis.io/docs/manual/patterns/caching/)

---

## Contact & Contribution

**Project Goal:** Build the most comprehensive crypto analytics infrastructure for AI agents.

**Contribution Areas:**
- New data source integrations
- Performance optimizations
- Security audits
- Documentation improvements
- Example use cases

**Development Philosophy:**
- Start simple, iterate fast
- Performance matters
- Agent experience first
- Security cannot be compromised
- Open source where possible

---

_Last Updated: 2026-02-09_
_Version: 2.0 Architecture Proposal_
