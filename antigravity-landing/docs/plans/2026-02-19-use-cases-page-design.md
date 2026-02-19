# Use Cases Page Design
**Date:** 2026-02-19
**Status:** Approved

## Vision
Narrative scroll page showing 4 real agent scenarios built on AgentLayer. Same visual language as Product page — same header, same section structure (number + large type + description + tags), same footer.

## Structure

### Hero
- Label: `Use Cases` (11px uppercase)
- Headline: `What agents build with AgentLayer` (~5.5vw, 800)
- Subtext: Four scenarios, from portfolio monitoring to autonomous DeFi strategy.

### 4 Use Case Sections
Each: number (01–04) + large feature name + description + MCP tool tags

| # | Name | Description | Tools |
|---|------|-------------|-------|
| 01 | Portfolio agent | Monitors wallets in real time: balances, P&L, transaction history | get_wallet_portfolio · get_token_transfers · get_crypto_prices |
| 02 | DeFi yield optimizer | Scans pools, compares APY across protocols and chains, builds strategy | get_defi_yields · get_protocol_tvl · get_protocol_fees |
| 03 | On-chain analyst | Reads network state: gas, protocol activity, stablecoin flows | get_gas_prices · get_stablecoin_stats · get_market_overview |
| 04 | Agent economy | Discovers agents in the on-chain registry — each agent has a wallet, metadata and a list of tasks it performs. Part of the agentic economy. | get_agent_by_id |

### Footer
Identical to Product page: `finance` + `for ai agents` + links.

## Files
- `src/components/UseCasesPage.jsx`
- `src/styles/UseCasesPage.css`
- `src/App.jsx` — add `#use-cases` hash route
- `src/components/Interface.jsx` — update Use Cases nav link
- `src/components/ProductPage.jsx` — update Use Cases nav link
