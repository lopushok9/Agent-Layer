# Agent Wallet Plan

## Goal

Build a plugin-friendly wallet layer for OpenClaw agents that is:

- simple to connect
- safe by default
- low on external API dependencies
- usable outside MCP, but easy to expose through MCP tools later

## Architecture Choice

### Chosen first step

Start with a separate wallet package at `agent-wallet/` and keep MCP as only one possible adapter on top of it.

Why:

- OpenClaw already has a clean `tools -> providers -> models` architecture in `mcp-server`
- wallet execution should be a backend capability first, not an MCP contract first
- the public MCP API can stay stable while the wallet implementation evolves

## Technology Notes

### Solana Agent Kit

Useful for:

- wallet abstraction ideas
- local keypair signer shape
- transaction execution flow
- plugin-style capability registration

Not ideal to embed whole:

- it expects its own `SolanaAgentKit` runtime object
- its plugin/action model is different from OpenClaw MCP contracts
- pulling it in directly would mix two agent abstractions

### SolClaw

Useful for:

- product integration ideas
- how wallet actions are framed for an agent
- deciding which Solana operations matter first

Not ideal as a backend source of truth:

- more CLI-centric
- more product-specific
- weaker abstraction boundary than Solana Agent Kit

### Other technologies considered

#### Solana Wallet Standard / Wallet Adapter

Very useful for client-side or user-attached wallets, but not the best first dependency for headless agent execution. It fits browser or embedded app flows better than server-side agent infrastructure.

#### Embedded or custodial providers

Examples: Turnkey, Privy, Crossmint.

These are useful later for mass consumer onboarding, policy enforcement, and non-technical users. They are not the best first step if the priority is minimizing external APIs and operational dependencies.

#### Raw RPC + local signer

This is the simplest first production path:

- one RPC dependency
- one local signing dependency
- no mandatory third-party wallet API
- easy to wrap as plugin or internal backend

## Initial Implementation Scope

### Phase 1

- Solana RPC provider
- wallet backend abstraction
- local keypair signer
- read-only mode with public key only
- message signing primitive
- capability discovery

### Phase 2

- transaction builder / signer bridge
- native SOL transfer
- SPL token transfer
- sign-only mode for external approval flows

### Phase 3

- optional embedded/custodial signer adapters
- policy layer
- approval hooks
- MCP tools on top of the backend

## Security Defaults

- read-only mode is allowed with public key only
- signing is opt-in through private key or keypair file
- no custodial provider is required in the first version
- transaction sending is not enabled until the signing and policy path is explicit

## Current Files

- `agent_wallet/config.py`
- `agent_wallet/exceptions.py`
- `agent_wallet/models.py`
- `agent_wallet/validation.py`
- `agent_wallet/providers/solana_rpc.py`
- `agent_wallet/wallet_layer/base.py`
- `agent_wallet/wallet_layer/base58.py`
- `agent_wallet/wallet_layer/solana.py`
- `agent_wallet/wallet_layer/factory.py`

These files establish the wallet backend boundary without forcing a public tool API too early.
