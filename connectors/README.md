# AgentLayer Connectors

AgentLayer Connectors are optional capabilities installed and enabled by a
wallet user. They let third-party developers add DeFi discovery, analytics,
agent marketplaces, x402 discovery, and verified transaction construction
without adding those integrations to the core wallet repository.

Connectors are additive. Existing first-party wallet integrations such as Aave,
Kamino, and Morpho remain part of the wallet and do not depend on this system.

## Trust model

There are three supported trust classes:

1. `community_read_only` connectors may be hosted by their publisher. They can
   return structured data but cannot return transaction or payment intents.
2. `verified_read_only` connectors have an AgentLayer-reviewed identity and
   artifact. They remain read-only.
3. `verified_write` connectors are built from reviewed source and hosted by
   AgentLayer as immutable, isolated deployments. They may return unsigned
   transaction intents for local verification.

Local connectors are a development feature. They are testnet-only by default
and never receive verified status.

## Safety boundary

The connector prepares data. The local wallet decides whether it is safe:

```text
connector -> unsigned intent -> local validation -> simulation
          -> preview -> user confirmation -> fresh intent
          -> repeated validation -> local signing -> broadcast
```

A connector never receives:

- private keys or seeds
- the AgentLayer boot key
- approval secrets or approval tokens
- signer objects
- wallet files

## Repository layout

```text
connectors/
├── spec/          # Public versioned protocol and JSON Schemas
├── sdk-typescript # TypeScript SDK (planned)
├── conformance/   # Cross-implementation contract tests (planned)
├── templates/     # Developer starter templates (planned)
└── examples/      # Reference read-only connectors (planned)
```

The hosted control plane and execution services belong in the separate
`connector-platform/` subtree. Local registry, policy, simulation, approval,
signing, and broadcast remain in `agent-wallet/`.

## Version 1 scope

Version 1 establishes:

- signed connector manifests
- install, enable, disable, update, and remove lifecycle
- remote HTTPS invocation
- schema-validated read-only tools
- verified EVM and Solana unsigned transaction intents
- exact version and artifact digest pinning

See [the protocol specification](spec/connector-protocol.md) for the wire
contract and security invariants.

