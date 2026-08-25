# AgentLayer Connector Protocol v1

## Status

This document defines the initial contract between a connector deployment, the
AgentLayer Connector Gateway, and the authoritative local wallet runtime.

## Components

- **Registry** publishes signed manifests and verification status.
- **Gateway** authenticates invocations and routes them to an exact connector
  version.
- **Connector runtime** returns structured read results or unsigned intents.
- **Local wallet** validates schemas, policy, simulation, approval, signing,
  broadcast, and final confirmation.

## Identity and immutability

A connector is identified by `(id, version, artifact_digest)`. Published
versions are immutable. A changed artifact requires a new version. The local
registry pins all three values and refuses a response that names a different
identity.

## Tool namespaces

Tool names in a manifest are connector-local. Hosts expose them as:

```text
connector__<normalized_connector_id>__<tool_name>
```

Normalized names contain lowercase ASCII letters, digits, and underscores.

## Invocation request

The gateway sends a JSON request containing:

```json
{
  "protocol_version": 1,
  "request_id": "uuid",
  "connector": {
    "id": "com.example.protocol",
    "version": "1.0.0",
    "artifact_digest": "sha256:..."
  },
  "tool": "get_markets",
  "arguments": {},
  "context": {
    "chain": "evm",
    "network": "base",
    "chain_id": 8453,
    "wallet_address": "0x..."
  },
  "issued_at": "2026-08-25T12:00:00Z",
  "expires_at": "2026-08-25T12:00:30Z",
  "nonce": "opaque-single-use-value"
}
```

`wallet_address` is omitted unless the installed manifest grants that
permission. Requests are authenticated by the Gateway and expire quickly.

## Invocation response

Every successful response contains the exact connector identity, request ID,
tool name, expiry, and one result kind:

```json
{
  "protocol_version": 1,
  "request_id": "uuid",
  "connector": {
    "id": "com.example.protocol",
    "version": "1.0.0",
    "artifact_digest": "sha256:..."
  },
  "tool": "get_markets",
  "kind": "read_result",
  "result": {},
  "expires_at": "2026-08-25T12:01:00Z"
}
```

Write-capable responses use `evm_transaction_intent` or
`solana_transaction_intent`. They remain unsigned and unbroadcasted.

## Read-only enforcement

Community and verified read-only connectors may return only `read_result`.
Returning any transaction, payment, signature, or broadcast intent is a hard
protocol violation. Read output is untrusted external data and must be checked
against the manifest's output schema before it reaches an agent host.

## Write execution

Only an enabled `verified_write` connector may return a transaction intent.
The local wallet must independently enforce:

- exact connector identity and artifact digest
- supported chain and network
- wallet/from/fee-payer binding
- contract addresses or Solana program IDs
- EVM selectors or Solana instruction constraints
- assets, amounts, recipients, spenders, and native value
- bounded approvals
- intent expiry and replay protection
- successful local simulation
- preview-to-execute binding

The connector never signs or broadcasts. The local wallet refreshes the intent
after confirmation, repeats all checks, then signs and sends it.

## Fees

Connector, referral, builder, and AgentLayer integration fees are prohibited.
Protocol fees, network fees, and x402 service prices must be explicit in the
preview and expected-effects data.

## Failure behavior

Unknown fields required for safe interpretation, schema mismatch, identity
mismatch, stale intent, failed simulation, unknown target, unknown program,
unknown selector, or expanded approval must fail closed.

