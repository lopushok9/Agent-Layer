# MCP Server Project Overview

## Purpose

This project is an MCP server that gives AI agents structured access to:

- crypto market data
- DeFi analytics
- on-chain wallet data
- gas estimates
- crypto search/news
- ERC-8004 agent identity and discovery

It is designed as a finance-oriented middleware layer for agents, with a strong focus on:

- normalized JSON outputs
- simple integration through MCP
- low-cost/free-tier infrastructure
- resilience through caching and provider fallback

## High-Level Architecture

The codebase is split into three main layers:

1. `tools/`
   MCP-facing tool definitions. This layer validates inputs, builds cache keys, calls providers, normalizes outputs through Pydantic models, and returns JSON strings.

2. `providers/`
   Integration layer for external systems such as CoinGecko, DeFiLlama, Alchemy, explorer APIs, 8004scan, and RPC endpoints.

3. infrastructure modules
   Shared runtime building blocks such as config loading, HTTP client reuse, rate limiting, caching, exceptions, and validation.

## Runtime Entry Point

The server starts from [server.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/server.py).

It creates one `FastMCP` instance, one shared in-memory cache, and registers all active tool groups.

Supported transports:

- stdio mode by default
- HTTP mode with `--http`

## Active Tool Groups

### Prices

Defined in [tools/prices.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/prices.py)

- `get_crypto_prices`
- `get_market_overview`
- `get_trending_coins`

Main sources:

- CoinGecko
- CoinCap
- DexScreener

Important behavior:

- price lookup uses fallback order: CoinGecko -> CoinCap -> DexScreener
- results are cached with short TTLs

### DeFi

Defined in [tools/defi.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/defi.py)

- `get_defi_yields`
- `get_protocol_tvl`
- `get_protocol_fees`
- `get_stablecoin_stats`
- `get_curve_pools`
- `get_curve_subgraph_data`

Main sources:

- DeFiLlama
- Curve API

### On-Chain

Defined in [tools/onchain.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/onchain.py)

- `get_wallet_balance`
- `get_wallet_portfolio`
- `get_token_transfers`
- `get_transaction_history`
- `get_token_balances`

Main sources:

- RPC endpoints
- Alchemy
- Etherscan / Arbiscan / Basescan
- CoinGecko for portfolio pricing

Important behavior:

- RPC uses a primary endpoint plus PublicNode fallback
- portfolio combines native balances, ERC-20 balances, and USD pricing

### Gas

Defined in [tools/gas.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/gas.py)

- `get_gas_prices`

Main sources:

- explorer gas oracle when available
- RPC fallback otherwise

### Search

Defined in [tools/search.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/search.py)

- `search_crypto`

Main source:

- Tavily

### Sentiment

Defined in [tools/sentiment.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/sentiment.py)

- `get_fear_greed_index`

Main source:

- Alternative.me Fear & Greed Index

### ERC-8004 Agents

Defined in [tools/agents.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/agents.py)

- `get_agent_by_id`
- `list_erc8004_chains`
- `search_erc8004_agents`
- `get_erc8004_agent_profile`

Main sources:

- on-chain ERC-8004 IdentityRegistry reads through Alchemy
- off-chain 8004scan index API

Important behavior:

- `get_agent_by_id` is on-chain identity lookup
- `search_erc8004_agents` and `get_erc8004_agent_profile` are off-chain indexed discovery tools

## Disabled Wallet Backend

There is also a Turnkey-based wallet execution backend in:

- [tools/wallet.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/tools/wallet.py)
- [providers/turnkey.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/providers/turnkey.py)

This functionality is currently kept in the repository but disabled in MCP registration.

Reason:

- it is not needed right now
- the project may migrate to a different operational crypto wallet backend

## Shared Infrastructure

### Configuration

[config.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/config.py)

Contains:

- API base URLs
- API keys
- RPC endpoints
- cache TTLs
- rate limits
- HTTP timeout

### Cache

[cache.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/cache.py)

Features:

- in-memory TTL cache
- stale reads for provider failure fallback
- simple eviction when entry count grows too large

### Rate Limiting

[rate_limiter.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/rate_limiter.py)

Features:

- async-safe sliding window limiter
- one limiter per provider module

### HTTP Client

[http_client.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/http_client.py)

Features:

- one shared `httpx.AsyncClient`
- JSON-oriented default headers
- redirect support

### Validation

[validation.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/validation.py)

Features:

- EVM address validation
- supported chain validation
- symbol list validation
- agent-friendly error messages

### Response Models

[models.py](/Users/yuriytsygankov/Documents/openclaw_skill/mcp-server/models.py)

Pydantic models define the normalized response contracts used by the tools.

## Design Patterns Used Across the Project

Most tools follow the same flow:

1. validate inputs
2. build cache key
3. check fresh cache
4. call provider(s)
5. normalize with Pydantic models
6. serialize to JSON
7. fallback to stale cache when possible

This makes behavior predictable for agents and keeps tool implementations consistent.

## Operational Notes

- cache is in-memory only, so it is reset on restart
- there is no persistent database
- external APIs are the main source of truth
- several tools degrade gracefully when optional API keys are not configured
- provider fallbacks are an important part of reliability

## Summary

This codebase is best understood as an agent-facing finance middleware service:

- MCP layer for agent access
- provider layer for external data and chain integrations
- normalization, caching, and validation in the middle

It is already well-structured for analytics and agent discovery use cases, while execution-oriented wallet functionality is currently present but intentionally disabled.
