# OpenClaw Repo Presentation Schema

```mermaid
flowchart LR
    Repo[OpenClaw Finance Stack]

    subgraph Hosts[Agent Hosts]
        OpenClaw[OpenClaw Host]
        Hermes[Hermes Agent]
        OCAW[Plugin: Agent Wallet]
        OCPay[Plugin: pay-bridge]
        HermesWallet[Plugin: agent_wallet]
        PayCLI[pay CLI]
    end

    subgraph Wallets[Wallet Policy And Execution]
        AgentWallet[agent-wallet]
        Solana[Solana networks\nmainnet devnet testnet]
        BTC[wdk-btc-wallet]
        BTCNet[Bitcoin networks\nbitcoin testnet regtest]
        EVM[wdk-evm-wallet]
        EVMNet[EVM networks\nethereum sepolia base base-sepolia]
    end

    subgraph Protocols[Protocol Surfaces]
        Bags[Bags]
        Jupiter[Jupiter Earn]
        Kamino[Kamino Lending]
        X402[x402 paid APIs]
        Velora[Velora swaps]
        Aave[Aave V3]
    end

    subgraph Infra[Shared Infra And Data]
        Gateway[provider-gateway]
        SolRPC[Shared Solana RPC]
        EvmRPC[Shared EVM RPC]
        MCP[mcp-server]
        MCPTools[Market DeFi On-chain tools]
        ERCDiscovery[ERC-8004 discovery]
    end

    subgraph Delivery[Public Delivery Surfaces]
        A2A[agent-a2a-gateway]
        Landing[landing site]
        Sol8004[solana-8004]
        ERCReg[ERC-8004 registration]
    end

    Repo --> AgentWallet
    Repo --> BTC
    Repo --> EVM
    Repo --> Gateway
    Repo --> MCP
    Repo --> A2A
    Repo --> Landing
    Repo --> Sol8004
    Repo --> OpenClaw
    Repo --> Hermes

    OpenClaw --> OCAW
    OpenClaw --> OCPay
    Hermes --> HermesWallet
    OCAW --> AgentWallet
    HermesWallet --> AgentWallet
    OCPay --> PayCLI

    AgentWallet --> Solana
    AgentWallet --> BTC
    AgentWallet --> EVM
    AgentWallet -. shared provider mode .-> Gateway
    AgentWallet --> Bags
    AgentWallet --> Jupiter
    AgentWallet --> Kamino
    AgentWallet --> X402

    BTC --> BTCNet
    EVM --> EVMNet
    EVM --> Velora
    EVM --> Aave
    EVM -. gateway rpc .-> Gateway

    Gateway --> SolRPC
    Gateway --> EvmRPC
    Gateway --> Bags
    Gateway --> Jupiter

    MCP --> MCPTools
    MCP --> ERCDiscovery

    A2A -. forwards .-> OpenClaw
    Sol8004 --> ERCReg
    MCP -. reads .-> ERCReg
```

## Reading Guide

- `agent-wallet` is the control center: policy, approvals, backend selection, Solana execution.
- `wdk-btc-wallet` and `wdk-evm-wallet` are separate localhost runtimes for non-Solana assets.
- `provider-gateway` is shared infra for RPC and selected protocol relays, not a signer.
- `mcp-server` is a read-oriented agent data plane for prices, DeFi, on-chain lookups, gas, search, and ERC-8004 discovery.
- `.openclaw` and `hermes/plugins/agent_wallet` are thin bridges that expose tool surfaces to different agent hosts.
