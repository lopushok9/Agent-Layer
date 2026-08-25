# AGENTS.md

## Scope
These instructions apply to the entire `connector-platform/` tree.

## Purpose
This subtree owns the hosted AgentLayer Connector control plane: registry,
gateway, verification pipeline contracts, deployment automation, and runtime
adapters for isolated Railway connector projects.

## Railway isolation model
- The trusted gateway and registry run in a dedicated control-plane project.
- Each production write-capable connector runs in its own Railway project.
- Staging and verification environments are separate from production.
- Connector projects never receive wallet secrets or control-plane database
  credentials.
- Cross-project calls use authenticated HTTPS because Railway private networks
  do not cross project boundaries.

## Security boundaries
- Never execute connector source inside the gateway process.
- Never accept a connector destination URL from an invocation request.
- Route only to a registry-pinned connector ID, version, artifact digest, and
  endpoint.
- Sign short-lived invocation envelopes and bind responses to request IDs.
- Keep connector code stateless and without persistent volumes.
- Do not share Railway variables between the control plane and connector
  projects.
- Do not put wallet signing, approval, or execution logic in this subtree.

## Deployment discipline
- Production connectors deploy only from AgentLayer-built immutable images.
- Do not use mutable image tags such as `latest`, `main`, or `stable`.
- Disable developer-repository autodeploy for production connector services.
- Apply CPU, memory, timeout, and response-size limits.
- A connector version is immutable; changes require a new version.
- Emergency disable must fail closed at the gateway.

## Change discipline
- Keep gateway, registry, and connector runtimes independently deployable.
- Add tests for request binding, route pinning, expiry, and response identity.
- Keep logs free of wallet addresses, full arguments, and connector responses.
- Do not add referral, builder, connector, or AgentLayer integration fees.

