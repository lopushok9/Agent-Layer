# AGENTS.md

## Scope
These instructions apply to the entire `connectors/` tree.

## Purpose
This subtree owns the public AgentLayer Connector specification, developer SDKs,
templates, conformance fixtures, and examples. Connectors extend the wallet with
optional crypto capabilities without becoming part of the authoritative wallet
backend.

## Boundaries
- Existing built-in wallet integrations, including Aave, Kamino, and Morpho,
  remain built in and must not depend on connectors.
- Connector code never receives wallet private keys, seed material, boot keys,
  approval secrets, approval tokens, or signer objects.
- Connector outputs are untrusted until the authoritative `agent-wallet/`
  policy layer validates them.
- Community connectors are read-only. Write-capable connectors require an
  AgentLayer-verified immutable deployment.
- No connector or AgentLayer-specific referral fee is allowed.

## Protocol rules
- Preserve versioned, JSON-serializable contracts.
- Tool names are local to a connector; hosts add the connector namespace.
- Read-only results must match the declared output schema.
- Write tools return unsigned intents. They never sign or broadcast.
- A connector version is immutable once published.
- Network, target, asset, amount, expiry, and expected effects must be explicit.

## Change discipline
- Update schemas and protocol documentation together.
- Add conformance fixtures for every contract change.
- Treat schema compatibility as a public API decision.
- Do not add wallet execution policy to an SDK or example.
- Keep provider credentials and all secrets out of manifests.

