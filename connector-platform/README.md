# AgentLayer Connector Platform

This subtree contains the hosted infrastructure for optional AgentLayer
Connectors. It is deliberately separate from `provider-gateway/`, whose scope
remains the existing narrow Bags and Solana RPC provider access layer.

## Railway topology

```text
Railway project: agentlayer-connectors-control
├── connector-gateway
├── connector-registry
└── registry-database

Railway project: agentlayer-connector-<id>-<version>
└── connector-runtime
```

Production write connectors use one Railway project per connector. This keeps
their private networks, service variables, deployments, and failure domains
separate. A connector runtime has no volume, database, wallet secret, or access
to the existing finance stack.

## Invocation path

1. The local wallet requests an exact connector ID and version from the
   gateway.
2. The gateway resolves a pinned route from trusted registry state. The request
   cannot supply or override a destination URL.
3. The gateway adds a request ID, nonce, short expiry, artifact digest, and
   signature.
4. The isolated connector returns structured data or an unsigned intent.
5. The gateway validates response identity and signs a response attestation.
6. The local wallet validates and simulates write intents before preview,
   approval, signing, and broadcast.

## Initial services

- `gateway/` provides authenticated routing to immutable connector versions.
- `registry/` will publish signed manifests and emergency-disable state.
- `deployer/` will turn verified artifacts into isolated Railway projects.

The first implementation uses a static, trusted route table at gateway startup.
Database-backed registry synchronization will replace it without changing the
public invocation contract.

