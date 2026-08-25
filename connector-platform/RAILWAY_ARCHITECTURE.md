# Railway Connector Deployment Baseline

## Control-plane project

The `agentlayer-connectors-control` Railway project contains trusted AgentLayer
services only. Production and staging use separate Railway environments and
separate variables.

The gateway is the only publicly reachable control-plane service. Registry and
database services use Railway private networking.

## Connector projects

Each verified write-capable connector version is deployed into a dedicated
Railway project with:

- one stateless service
- no volume or database
- no shared variables
- no wallet or control-plane secrets
- an immutable AgentLayer-built image version
- a minimal public HTTPS invocation endpoint
- CPU and memory replica limits
- request timeout and response-size enforcement
- production autodeploy disabled

The connector receives only a gateway verification key and any narrowly scoped
protocol-provider credential approved during verification.

## Network contract

Railway private networking is project-scoped, so gateway-to-connector traffic
crosses authenticated public HTTPS. Connector endpoints accept only signed,
short-lived AgentLayer invocation envelopes.

Static outbound IPs may be used when an upstream protocol API supports source
allowlisting. Static IPs are not treated as an outbound firewall. Verified code,
dependency review, restricted credentials, and local wallet validation remain
mandatory.

## Deployment identity

The registry pins:

```text
connector_id
connector_version
artifact_digest
image_reference
source_commit
gateway_endpoint
verification_status
enabled
```

Mutable tags are prohibited. Rebuilding or changing a connector creates a new
version and a new deployment identity.

