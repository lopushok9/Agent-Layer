# Graph Report - architecture-corpus  (2026-05-18)

## Corpus Check
- Corpus is ~775 words - fits in a single context window. You may not need a graph.

## Summary
- 29 nodes · 41 edges · 5 communities detected
- Extraction: 83% EXTRACTED · 15% INFERRED · 2% AMBIGUOUS · INFERRED: 6 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Wallet Policy And Solana Flows|Wallet Policy And Solana Flows]]
- [[_COMMUNITY_BTC And EVM Wallet Runtimes|BTC And EVM Wallet Runtimes]]
- [[_COMMUNITY_Shared Provider And MCP Data Plane|Shared Provider And MCP Data Plane]]
- [[_COMMUNITY_Agent Hosts And Plugin Bridges|Agent Hosts And Plugin Bridges]]
- [[_COMMUNITY_Delivery, A2A, And Registration Surfaces|Delivery, A2A, And Registration Surfaces]]

## God Nodes (most connected - your core abstractions)
1. `agent-wallet` - 11 edges
2. `OpenClaw Finance Stack` - 10 edges
3. `provider-gateway` - 8 edges
4. `wdk-evm-wallet` - 6 edges
5. `mcp-server` - 5 edges
6. `OpenClaw Host` - 5 edges
7. `wdk-btc-wallet` - 3 edges
8. `solana-8004` - 3 edges
9. `OpenClaw Plugin: Agent Wallet` - 2 edges
10. `OpenClaw Plugin: pay-bridge` - 2 edges

## Surprising Connections (you probably didn't know these)
- `provider-gateway` --supports_related_reads--> `Velora Swaps`  [AMBIGUOUS]
  architecture-corpus/00_repo_map.md → architecture-corpus/01_wallets_and_networks.md
- `mcp-server` --reads_registration_data--> `ERC-8004 Registration`  [INFERRED]
  architecture-corpus/00_repo_map.md → architecture-corpus/02_tools_inventory.md
- `wdk-evm-wallet` --can_route_via--> `provider-gateway`  [INFERRED]
  architecture-corpus/01_wallets_and_networks.md → architecture-corpus/00_repo_map.md
- `provider-gateway` --relays--> `Bags`  [EXTRACTED]
  architecture-corpus/00_repo_map.md → architecture-corpus/01_wallets_and_networks.md
- `provider-gateway` --relays--> `Jupiter Earn`  [EXTRACTED]
  architecture-corpus/00_repo_map.md → architecture-corpus/01_wallets_and_networks.md
- `OpenClaw Plugin: Agent Wallet` --bridges_to--> `agent-wallet`  [EXTRACTED]
  architecture-corpus/02_tools_inventory.md → architecture-corpus/00_repo_map.md

## Communities

### Community 0 - "Wallet Policy And Solana Flows"
Cohesion: 0.29
Nodes (7): OpenClaw Finance Stack, agent-wallet, Solana Networks, Bags, Jupiter Earn, Kamino Lending, x402 Paid API Flow

### Community 1 - "BTC And EVM Wallet Runtimes"
Cohesion: 0.27
Nodes (6): wdk-btc-wallet, Bitcoin Networks, wdk-evm-wallet, EVM Networks, Velora Swaps, Aave V3

### Community 2 - "Shared Provider And MCP Data Plane"
Cohesion: 0.27
Nodes (6): provider-gateway, Shared Solana RPC, Shared EVM RPC, mcp-server, Market / DeFi / On-chain Tools, ERC-8004 Discovery

### Community 3 - "Agent Hosts And Plugin Bridges"
Cohesion: 0.27
Nodes (6): OpenClaw Host, OpenClaw Plugin: Agent Wallet, OpenClaw Plugin: pay-bridge, Hermes Agent, Hermes Plugin: agent_wallet, pay CLI / pay.sh

### Community 4 - "Delivery, A2A, And Registration Surfaces"
Cohesion: 0.17
Nodes (4): agent-a2a-gateway, landing site, solana-8004, ERC-8004 Registration

## Ambiguous Edges - Review These
- `provider-gateway` → `Velora Swaps`  [AMBIGUOUS]
  architecture-corpus/00_repo_map.md · relation: supports_related_reads

## Knowledge Gaps
- **11 isolated node(s):** `Solana Networks`, `Bitcoin Networks`, `EVM Networks`, `Shared Solana RPC`, `Shared EVM RPC` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `provider-gateway` and `Velora Swaps`?**
  _Edge tagged AMBIGUOUS (relation: supports_related_reads) - confidence is low._
- **Why does `agent-wallet` connect `Wallet Policy And Solana Flows` to `BTC And EVM Wallet Runtimes`, `Shared Provider And MCP Data Plane`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Why does `OpenClaw Plugin: Agent Wallet` connect `Agent Hosts And Plugin Bridges` to `Wallet Policy And Solana Flows`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **What connects `Solana Networks`, `Bitcoin Networks`, `EVM Networks` to the rest of the system?**
  _11 weakly-connected nodes found - possible documentation gaps or missing edges._