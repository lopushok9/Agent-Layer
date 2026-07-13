# AGENTS.md

## Scope
These instructions apply to the entire `wdk-evm-wallet/` tree.

## Purpose
`wdk-evm-wallet` is the separate local EVM wallet runtime for AgentLayer.

It exists to provide:

- local encrypted EVM wallet storage
- localhost-only wallet operations for trusted local callers
- ordinary EVM account support through Tether WDK
- narrow transfer-oriented capabilities for OpenClaw and `agent-wallet`

It does **not** own agent policy, approval-token issuance, or OpenClaw-facing tool semantics.
Those remain in `agent-wallet/`.

## Current Product Boundary

This service is intentionally narrow.

Supported now:

- wallet create / import / unlock / lock
- address derivation
- native balance lookup
- ERC-20 balance lookup
- fee-rate lookup
- read-only Velora swap quotes for supported ERC-20 pairs
- native transfer quote / send
- ERC-20 transfer quote / send
- Aave V3 account data, quote, and send flows for narrow lending operations
- transaction receipt lookup
- network switching across supported EVM chains

Not supported now:

- ERC-4337
- arbitrary calldata execution
- generic token approval endpoints
- generic contract calls
- deposits, lending, or bridge flows outside explicitly supported protocol modules
- exposing seed phrases to the agent path

## Supported Networks

- `ethereum`
- `sepolia`
- `base`
- `base-sepolia`
- `robinhood`

Use these names consistently across config, tests, and host integrations.

`robinhood` (Robinhood Chain, chain id 4663) is gateway-enforced like
`ethereum`/`base` — RPC always routes through the provider-gateway's Alchemy
key, never a direct URL. Uniswap Trading API is the only DeFi integration
available on `robinhood`; Aave, Velora, LI.FI, Morpho, and Lido remain
`ethereum`/`base`-only because none of those protocols are deployed on
Robinhood Chain.

## Architecture Map

### Main entrypoints

- `src/server.js` - localhost HTTP API and request routing
- `src/wdk_evm_wallet.js` - WDK-backed EVM wallet operations
- `src/local_vault.js` - encrypted seed vault and unlocked in-memory state
- `src/network_state.js` - persistent active-network selection
- `src/config.js` - runtime config, auth token, RPC profile loading
- `src/json.js` - JSON request/response helpers

### Runtime model

- `server.js` owns HTTP-only behavior
- `wdk_evm_wallet.js` owns chain operations and WDK integration
- `local_vault.js` owns encrypted seed storage and password-gated unlock
- `network_state.js` owns active network persistence

Keep those responsibilities separate.

## Security Invariants

- Bind to `127.0.0.1` by default and keep the service localhost-only.
- Require bearer-token auth on every route except `/health`.
- Never accept or expose remote service URLs through higher-level integrations.
- Keep seed phrases encrypted at rest.
- Keep unlocked seed phrases only in process memory.
- `lock` and process restart must clear unlocked in-memory state.
- Do not expose seed reveal through agent-facing paths.
- Do not add arbitrary calldata execution to the public API.
- Do not add generic approval-style token operations like `approve`; approvals must stay protocol-scoped and safety-reviewed.
- Do not move secrets into repo config files or plugin manifests.

## WDK Boundary

This subtree is the WDK runtime boundary for ordinary EVM accounts.

- Use `@tetherto/wdk`
- Use `@tetherto/wdk-wallet-evm`
- Keep `ERC-4337` out of this subtree unless the service is intentionally expanded
- Prefer documented WDK surfaces only

When changing behavior, align with the official WDK docs:

- Node quickstart
- wallet-evm overview
- wallet-evm configuration
- wallet-evm API reference

## API Discipline

Routes live under `/v1/evm/...`.

Keep the route surface explicit and predictable. Prefer adding narrow wallet primitives over generic execution endpoints.

Return JSON in the existing shape:

- success: `{ "ok": true, "data": ... }`
- failure: `{ "ok": false, "error": "..." }`

Convert `bigint` values into JSON-safe strings before returning responses.

## Config Discipline

Keep config centralized in `src/config.js`.

Current config areas:

- host / port
- active default network
- per-network RPC URLs and chain ids
- local auth token path / value
- transfer fee guardrail config
- vault data directory
- unlock timeout

Do not duplicate environment parsing in other files unless there is a strong reason.

## Vault Rules

`src/local_vault.js` is sensitive code.

- Preserve password-gated decryption.
- Preserve authenticated encryption semantics.
- Preserve wallet metadata registry behavior.
- Keep unlocked state ephemeral and in-memory only.
- Keep file permissions restrictive.

Any change here should be treated as security-sensitive.

## Integration Boundary

This service is consumed by `agent-wallet/` through a localhost client.

That means:

- do not embed OpenClaw-specific policy here
- do not issue approval tokens here
- do not add agent-language instructions here
- do not assume this service is the UX layer

`agent-wallet/` is the policy layer.
`wdk-evm-wallet/` is the custody/runtime layer.

## Update Discipline

When changing the HTTP contract, keep these in sync:

- `wdk-evm-wallet/src/server.js`
- `wdk-evm-wallet/src/wdk_evm_wallet.js`
- `agent-wallet/agent_wallet/providers/wdk_evm_local.py`
- `agent-wallet/agent_wallet/wallet_layer/wdk_evm.py`
- `agent-wallet/agent_wallet/evm_user_wallets.py`
- relevant OpenClaw plugin docs/tests

When changing network naming, keep these in sync:

- `src/config.js`
- `src/network_state.js`
- Python EVM binding/backend normalization
- plugin config documentation

## Validation

Prefer fast, targeted checks first:

- `npm run check`

Then run the relevant Python smoke tests in `agent-wallet/tests/`:

- `smoke_wdk_evm_local_security.py`
- `smoke_openclaw_evm_adapter.py`
- `smoke_openclaw_evm_runtime.py`
- `smoke_openclaw_evm_cli.py`

If changing live RPC behavior, test on `sepolia` or `base-sepolia` before touching mainnet.

## Working Rule

Keep this service narrow, local, and custody-focused.

If a change starts looking like:

- host policy
- agent UX
- approval orchestration
- multi-chain abstraction above the wallet runtime

then it probably belongs in `agent-wallet/`, not here.
