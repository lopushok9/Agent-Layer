# Read-only connector beta contract

This file defines the release gate for the first public AgentLayer Connector
SDK. It deliberately excludes transaction construction, signing, broadcasting,
x402 payments, and write-capable connector tools.

## Supported

- `community_read_only` and `verified_read_only` manifests
- publisher-hosted public HTTPS endpoints
- `GET /healthz` and `POST /invoke`
- JSON Schema validated tool arguments and results
- optional, explicitly permitted wallet address context
- local install, enable, disable, inspect, doctor, and remove lifecycle
- OpenClaw, Codex, Claude Code, and Hermes host discovery

## Not supported

- transaction or payment intents
- signer, approval token, seed, key, or wallet-file access
- automatic execution based on connector output
- mutable artifacts under an existing `(id, version)`
- local arbitrary code installation in normal user mode
- public marketplace discovery in the initial beta

## Release gates

The beta may be published only when:

1. SDK and conformance tarballs install and run outside this monorepo.
2. Connector CI is required and green on Node.js 24.
3. Connect-time SSRF protection covers DNS rebinding and non-public IP ranges.
4. Installation displays endpoint and permissions before enabling a connector.
5. One neutral crypto-data reference connector is healthy on Railway.
6. The live endpoint passes conformance and wallet invocation tests.
7. All supported hosts discover and invoke the installed read-only tool.
8. npm beta packages are published with reproducible contents.
9. Stable publication uses GitHub OIDC trusted publishing and provenance.

## Compatibility policy

Protocol v1 required fields and security semantics are frozen. Additive
optional fields are permitted only when older connectors can safely ignore
them. Manifest or tool-schema changes require a new immutable connector
version. Breaking wire changes require Protocol v2.
