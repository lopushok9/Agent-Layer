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

## Current implementation status

The first executable slice supports remote HTTPS read-only connectors:

- install a local manifest file into an immutable local registry
- enable, disable, inspect, validate, and remove installed versions
- dynamically expose enabled read tools in OpenClaw and Codex
- validate request and response JSON Schemas
- reject redirects, private/local endpoints, oversized responses, stale
  responses, and connector identity mismatches

`verified_write` manifests and EVM unsigned intents can be validated by the
wallet policy module, but write tools are intentionally withheld from agent
hosts until gateway attestation, local simulation, preview/approval binding,
and execution orchestration are complete. Solana intent execution is also not
enabled yet.

## User lifecycle

Install and enable a connector manifest:

```bash
wallet connectors install ./connector.json --enable
wallet connectors list
wallet connectors info com.example.protocol
wallet connectors doctor
```

Disable it without deleting the pinned manifest:

```bash
wallet connectors disable com.example.protocol
```

Removal is explicit and only allowed while disabled:

```bash
wallet connectors remove com.example.protocol --version 1.0.0 --yes
```

Restart the agent host after changing connector state so its registered tool
catalog is rebuilt. Registry state lives under
`$OPENCLAW_HOME/agent-wallet-runtime/connectors` and is not stored inside a
versioned wallet release.

## Minimal read-only connector contract

A publisher hosts the manifest's HTTPS base URL and implements `POST /invoke`.
The endpoint receives the versioned request documented in the protocol spec
and returns a short-lived `read_result` matching the tool's `output_schema`.
Community connector output is always marked as untrusted external data. It
must never contain unsigned transactions, calldata, payment requests, or other
write intents.
