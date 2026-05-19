# Wallets And Networks

The wallet stack is intentionally split by chain family.

## Authoritative wallet policy

- `agent-wallet` is the source of truth for wallet behavior.
- It owns preview, prepare, execute, approval tokens, spending limits, and session runtime assembly.
- It is the only layer that should be treated as the policy gate for agent-triggered execution.

## Solana wallet path

- Backend: `agent-wallet`
- Default networks: `mainnet`, `devnet`, `testnet`
- Capabilities: wallet reads, SOL transfers, SPL transfers, staking, Jupiter swaps, Jupiter Earn, Kamino lending, Bags launch and fees, LI.FI cross-chain routes, private swap flows, x402 paid API flows
- RPC mode: direct user RPC or shared proxy through `provider-gateway`

## Bitcoin wallet path

- Backend: `wdk-btc-wallet`
- Integration owner: `agent-wallet` selects it through backend `wdk_btc_local`
- Networks: `bitcoin`, `testnet`, `regtest`
- Capabilities: address resolution, balances, history, fee rates, max spendable, transfer quote, transfer send
- Runtime shape: localhost-only Node.js service with encrypted local vault and bearer token auth

## EVM wallet path

- Backend: `wdk-evm-wallet`
- Integration owner: `agent-wallet` selects it through backend `wdk_evm_local`
- Networks: `ethereum`, `sepolia`, `base`, `base-sepolia`
- Capabilities: native balances, ERC-20 balances and metadata, fee rates, receipts, Velora swaps, Aave V3 account and position flows, native and token transfers
- Runtime shape: localhost-only Node.js service with encrypted local vault and bearer token auth

## Shared provider mode

- `provider-gateway` can act as the upstream RPC transport for Solana and EVM
- Solana shared mode is mainnet-oriented and allowlisted
- EVM shared mode supports `ethereum` and `base`
- Shared mode exists for onboarding-friendly defaults, not for custody or signing

## Safety boundary

- `provider-gateway` never sees private keys
- `mcp-server` does not own signing
- `.openclaw` and Hermes do not reimplement wallet policy
