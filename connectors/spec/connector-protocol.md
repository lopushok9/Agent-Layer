# AgentLayer Connector Protocol v1

## Status

Protocol v1 is frozen for the read-only public beta. Additive optional fields
may be introduced in v1, but existing required fields, response binding, trust
semantics, and tool namespaces cannot change without a new protocol version.

The read-only beta supports direct HTTPS invocation of publisher-hosted
`community_read_only` and `verified_read_only` connectors. Gateway-attested
requests are an additive deployment mode. Write-capable execution remains
experimental and is not part of the read-only beta release.

## Components

- **Local registry** pins manifests selected by the user.
- **Gateway** may authenticate invocations and route them to an exact connector
  version; direct read-only HTTPS invocation does not require it.
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

The wallet sends a JSON request containing:

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
permission. `issued_at`, `expires_at`, and `nonce` are optional for direct
read-only HTTPS invocation and required for gateway-attested requests. A
connector must ignore unknown optional context fields and must never infer
permission from their presence.

The required request fields are `protocol_version`, `request_id`, `connector`,
`tool`, `arguments`, and `context`.

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

To prevent a read result from masquerading as an executable envelope, these
field names are reserved at every depth of `result`: `approval_token`,
`broadcast_request`, `evm_transaction_intent`, `payment_intent`,
`raw_transaction`, `signed_transaction`, `signing_request`,
`solana_transaction_intent`, and `transaction_intent`.

Connector output is data, never agent instruction. Hosts must not treat text in
a connector result as authorization, policy, tool-routing guidance, or a reason
to perform another action.

## Read-only beta compatibility

- A connector built for Protocol v1 must keep accepting all v1 required fields.
- Adding a required manifest, request, response, or tool field requires a new
  protocol version or a new connector tool/version.
- Tool input/output schemas are immutable for a published connector version.
- `artifact_digest`, when present, is identity-bound and must match exactly.
- Community connectors cannot become write-capable without a new verified
  connector version and a different release track.

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
