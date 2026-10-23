# Provider Gateway

`provider-gateway` is a small shared infrastructure service for OpenClaw.

It is intended to solve two onboarding problems:

- users should not need to bring their own Bags API key to get started
- users should not need to bring their own Helius/Alchemy key to get a reasonable default RPC path

This service is deliberately narrow:

- shared Bags trade + claim relay
- shared Bags token launch relay
- shared Jupiter Earn relay
- shared Solana RPC gateway with method allowlist
- shared EVM RPC gateway for ethereum/base/robinhood with method allowlist
- no wallet custody
- no transaction signing

Signing stays on the user machine in `agent-wallet`.

## Shared Kernel browsers (opt-in)

The browser broker provisions resources; it is not a browser/JavaScript proxy.
Card fields and Playwright requests go directly from the local wallet backend
to Kernel. The gateway never receives PAN/CVV, wallet keys or checkout plans.

- `GET /v1/kernel/capabilities` — public version and availability, no secrets.
- `POST /v1/kernel/browser-sessions` — signed `{ "lease_id": "<32 hex>" }`;
  creates one profile-free headless browser and returns its expiring, scoped key.
- `POST /v1/kernel/browser-sessions/{lease_id}/close` — signed empty object;
  checks ownership, deletes the browser and revokes the key. Returns `202` while
  cleanup is pending. There is no cross-user session listing or raw relay.

### Operator configuration and rollout

Set `KERNEL_API_KEY`, `KERNEL_PROJECT_ID`, and `KERNEL_BROKER_DB_PATH` through the
deployment's secret/environment settings. Use an isolated production project
and an unrestricted project-scoped operator key capable of creating scoped keys.
Never put a real key in this repository or in a plugin manifest.
The SQLite path must live on a persistent writable volume; retain that database
across deployments, including when rolling the plugin back. Run one gateway
deployment against that database; separate replicas/databases would not share
ownership, replay tracking or quotas. Do not deploy it on ephemeral per-replica
storage. A cleanup task runs every 15 seconds in the application lifespan.
Absolute expiry is enforced by that worker, so keep the gateway running and
restore it promptly after outages. Kernel's inactivity timeout is a separate
fallback; an active CDP connection can keep it alive. Key expiry alone is not a
hard browser shutdown. Operators needing a deletion deadline during a gateway
outage must also run cleanup independently against the same durable lease data.

Deploy with `KERNEL_SHARED_ENABLED=false`, verify the provider accepts the exact
scoped policy and the isolation/upgrade gates, then enable it and release the
new plugin. Disabling the flag stops new allocations while close and cleanup
continue as long as the operator credential, project and database remain set.
Old RPC/provider endpoints keep their existing behavior and authentication.
Users with personal Kernel keys retain direct connections; users without keys
use the shared capability automatically after updating and restarting the host.

Defaults: 900-second absolute leases, 300-second browser inactivity timeout,
10 active leases globally, 2 per installation, 100 allocations per rolling day,
10 per installation and 20 per source IP. `KERNEL_MAX_*` and
`KERNEL_SESSION_TTL_SECONDS` configure these bounded limits. Ensure proxy trust
is configured correctly for `request.client.host`; never accept arbitrary
forwarded IP headers. Installation quotas alone are not Sybil resistance, so
retain the global caps. Provider outages can delay deletion; keys expire and
the durable cleanup worker retries. Do not enable public access before checking
these settings against the service budget.

### Installation authentication

Browser routes always require Ed25519 proof, independently of
`REQUIRE_BEARER_AUTH` and the legacy common bearer. An installation generates its
own key automatically, stores it encrypted, and proves possession on each POST.
No separate account-registration step is needed. The authenticated identity is
SHA-256 of its public key, never a caller-supplied user ID.

Headers: `X-AgentLayer-Client-Key` (32-byte public key, hex),
`X-AgentLayer-Timestamp` (Unix seconds), `X-AgentLayer-Nonce` (32 hex), and
`X-AgentLayer-Signature` (64-byte Ed25519 signature, hex). Sign UTF-8 bytes of:

```text
agentlayer-kernel-v1\nMETHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256_OF_EXACT_BODY
```

The timestamp window is 90 seconds past / 30 seconds future; nonces are stored
transactionally and cannot be reused. Bodies are capped at 1 KiB. Allocation IDs
are durable and never automatically replay an upstream create. A lost response
is cleaned up through the same lease and deterministic Kernel browser name.
SQLite stores ownership, resource/key IDs, expiry and cleanup state, never the
temporary plaintext key. Responses containing keys use `Cache-Control: no-store`;
do not enable HTTP body logging at the deployment proxy.

The scoped key grants only `browsers:use` on
`projects/<project>/browsers/<session_id>`. The server validates the returned
policy, project and expiry before sending it to a client, failing closed if an
older upstream ignores the restriction. Clients receive neither browser-create
nor key-management permissions. Cleanup deletes the browser, since revoking a
key alone does not invalidate previously issued connection URLs.

Shared RPC mode is intentionally mainnet-only. Devnet and testnet should use direct public RPC endpoints instead of the gateway.

## Current scope

Implemented endpoints:

- `GET /health` — public health and capability snapshot
- `GET /v1/status` — authenticated status and provider capabilities
- `POST /v1/rpc` — authenticated Solana JSON-RPC proxy with method allowlist
- `POST /v1/evm/rpc/{network}` — authenticated raw EVM JSON-RPC proxy for `ethereum` / `base` / `robinhood`
- `GET /v1/evm/transfers/{network}` — bounded Alchemy transfer history for `ethereum` / `base` / `robinhood`
- `GET /v1/bags/trade/quote` — authenticated Bags trade quote
- `POST /v1/bags/trade/swap` — authenticated Bags swap transaction creation
- `POST /v1/bags/launch/token-info` — authenticated Bags token metadata creation
- `POST /v1/bags/launch/fee-share-config` — authenticated Bags fee-share config creation
- `POST /v1/bags/launch/transaction` — authenticated Bags launch transaction creation
- `GET /v1/bags/claim/positions` — authenticated Bags claimable positions
- `POST /v1/bags/claim/transactions` — authenticated Bags claim transaction generation
- `GET /v1/bags/fees/lifetime` — authenticated Bags lifetime fee analytics
- `GET /v1/bags/fees/claim-stats` — authenticated Bags claimer analytics
- `GET /v1/bags/fees/claim-events` — authenticated Bags claim event feed / history
- `GET /v1/jupiter/earn/tokens` — authenticated Jupiter Earn token catalog
- `GET /v1/jupiter/earn/positions` — authenticated Jupiter Earn positions
- `GET /v1/jupiter/earn/earnings` — authenticated Jupiter Earn earnings
- `POST /v1/jupiter/earn/deposit` — authenticated Jupiter Earn deposit transaction build
- `POST /v1/jupiter/earn/withdraw` — authenticated Jupiter Earn withdraw transaction build
- `GET /v1/houdini/tokens` — authenticated Houdini token catalog relay
- `GET /v1/houdini/quotes/private` — authenticated Houdini private quote relay
- `POST /v1/houdini/exchanges` — authenticated Houdini single-order private exchange creation
- `GET /v1/houdini/orders/{houdiniId}` — authenticated Houdini single-order status
- `POST /v1/houdini/exchanges/multi` — authenticated Houdini multi-order creation
- `GET /v1/houdini/exchanges/multi/{multiId}` — authenticated Houdini multi-order status
- `GET /v1/houdini/exchanges/multi/{multiId}/tx` — authenticated Houdini Solana prebuilt transaction fetch
- `POST /v1/telemetry` — **public** anonymous wallet telemetry ingest (no auth, rate-limited)
- `GET /v1/telemetry/stats` — authenticated telemetry dashboard and adoption metrics

### Telemetry

The wallet emits one fire-and-forget, anonymous event per tool invocation
so we can measure adoption across hosts (Claude Code / Codex / Cursor / Hermes /
OpenClaw / universal MCP) without any PII. MCP hosts record in the shared bridge
(`codex/plugins/agent-wallet/server.py`), which also emits `session_start` when a
host launches it; Hermes and OpenClaw record in `openclaw_cli invoke`. The ingest route is intentionally unauthenticated (events arrive
from every install) and validated against a strict allowlist in
`telemetry_store.py`: only `event`, `install_id` (a random local UUID),
`host`, `tool` (registered tool name), `backend`, `plugin_version`, `ok`, `ts`,
`mode` (`preview`/`execute`/`intent_*` for write tools) and a coarse
`error_class` for failed calls are accepted. Any extra field — and anything address-like in `tool` — is rejected
(`422`). No wallet addresses, balances, amounts, tx hashes, tool arguments, or
secrets are ever stored. x402 lifecycle events add only coarse, allowlisted
dimensions: network, scheme, asset family, USD amount bucket, settlement status,
and error class. They never include the request URL, recipient, raw amount,
transaction hash, response body, or payment payload. The x402 dashboard funnel
keeps `x402_pay_request` call volume separate from payment success; a payment is
successful only after an `x402_payment_settled` event.

Config:

- `TELEMETRY_ENABLED` — server-side kill switch (default `true`)
- `TELEMETRY_DB_PATH` — SQLite path (default `./telemetry.db`; point at a mounted
  volume on Railway for durable history — the default file resets on redeploy)
- `TELEMETRY_RATE_LIMIT_PER_MIN` — per-IP ingest cap (default `120`)
- `TELEMETRY_EXCLUDE_INSTALL_IDS` — comma-separated install ids (our own dev and
  test machines, from `~/.openclaw/telemetry_id`) hidden from every stat

`GET /v1/telemetry/stats?window_days=30` is gated by the same bearer/machine
token as `/v1/status` so raw numbers are not world-readable. In a browser
(`Accept: text/html`) it renders a lightweight analytics dashboard. In addition
to overall active installs, the stats payload now exposes wallet-specific
install activity:

- `wallet_active_installs` — unique `install_id` values with at least one
  `tool_invoke` during the selected window
- `wallet_dau` — unique `install_id` values with at least one `tool_invoke`
  during the last 24 hours
- `wallet_by_host` — wallet-specific breakdown by host/plugin
- `hosts` — per framework: plugin installs → launched (`session_start`) →
  wallet users → returning users (tool calls on 2+ UTC days), calls and success
- `users` — wallet users, new / returning / executing users, 7-day actives,
  calls-per-user buckets and the install → wired → launched → used → returned funnel
- `tools` — every tool with calls, installs, success rate, preview/execute split
- `host_tools`, `tool_errors` — tool × host matrix and failures by error class
- `by_backend_tool` — tool calls grouped by their recorded wallet backend

For raw machine-readable JSON use:

```text
/v1/telemetry/stats?window_days=30&format=json
```

Clients opt out by setting `AGENT_WALLET_NO_TELEMETRY=1`.

Not implemented yet:

- admin fee-share endpoints
- user-aware rate limiting / quotas
- request signing / replay protection

## Security model

- `BAGS_API_KEY` lives only in this service
- shared Helius/Alchemy credentials live only in this service
- users authenticate to this service with a separate bearer token
- user wallets sign locally; this service never sees private keys

Do not expose this service publicly without inbound auth and outer rate limiting.

## Environment

Copy `.env.example` to `.env`.

Configure the surfaces you want to expose:

- shared Solana RPC:
  - `SHARED_SOLANA_RPC_URL`, or
  - `HELIUS_API_KEY`, or
  - `ALCHEMY_API_KEY`
- shared EVM RPC:
  - `SHARED_EVM_ETHEREUM_RPC_URL` / `SHARED_EVM_BASE_RPC_URL` / `SHARED_EVM_ROBINHOOD_RPC_URL`, or
  - `ALCHEMY_ETHEREUM_RPC_URL` / `ALCHEMY_BASE_RPC_URL` / `ALCHEMY_ROBINHOOD_RPC_URL`, or
  - `ALCHEMY_API_KEY`
- Bags relay:
  - `BAGS_API_KEY`
- Jupiter Earn relay:
  - `JUPITER_API_KEY`
- Houdini private swap relay:
  - `HOUDINI_API_KEY`
  - `HOUDINI_API_SECRET`
  - optional `HOUDINI_API_BASE_URL`
  - optional `HOUDINI_USER_AGENT`
  - optional `HOUDINI_USER_TIMEZONE`

Optional:

- `PROVIDER_GATEWAY_BEARER_TOKEN` when `REQUIRE_BEARER_AUTH=true`
- `JUPITER_LEND_API_BASE_URL`

## Run locally

```bash
cd provider-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Example requests

Health:

```bash
curl http://localhost:8000/health
```

Status:

```bash
curl http://localhost:8000/v1/status
```

Shared RPC:

```bash
curl http://localhost:8000/v1/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "auto",
    "method": "getLatestBlockhash",
    "params": [{"commitment":"confirmed"}]
  }'
```

Shared EVM RPC:

```bash
curl "http://localhost:8000/v1/evm/rpc/ethereum?provider=alchemy" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_chainId",
    "params": []
  }'
```

EVM transfer history uses `address=0x...`, `direction=outgoing|incoming`,
`page_size=1..100` (default 20), `include_nfts=1` (optional), and the optional
opaque `page_key` returned by Alchemy. Each call fetches one page only and returns
compact transfer objects. `value` is Alchemy's display float; use `raw_value`
(exact integer string) with `decimals` for accounting. ERC-1155 transfers carry an
`erc1155` list of `{token_id, value}`. It includes native, internal (not on Robinhood), and
ERC-20 movements, plus ERC-721/ERC-1155 with `include_nfts=1`. Zero-value
transfers (mostly address-poisoning spam) are excluded. It is not a complete index
of contract calls or failed transactions. The gateway does not persist wallet
addresses or transfers.

Each Alchemy call costs about 150 CU and shares the key with balances and
broadcasts, so the route is bounded by an in-memory budget per gateway process.
Identical requests are served from cache and do not count:

| Env var | Default | Purpose |
|---|---|---|
| `EVM_TRANSFERS_CACHE_TTL_SECONDS` | `60` | Page cache lifetime |
| `EVM_TRANSFERS_PER_ADDRESS_PER_MIN` | `20` | Stops a runaway loop on one wallet |
| `EVM_TRANSFERS_MAX_PER_MIN` | `120` | Burst cap across all addresses |
| `EVM_TRANSFERS_MAX_PER_DAY` | `20000` | Hard daily cap (~3M CU) across all addresses |

Over a limit the route returns `429` with `Retry-After`. The counters are per
process and reset on restart; with several replicas the effective caps multiply.

For machine JSON-RPC clients that cannot set a bearer header, the protected EVM RPC route also accepts `?token=<PROVIDER_GATEWAY_BEARER_TOKEN>`.

Bags quote:

```bash
curl "http://localhost:8000/v1/bags/trade/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000" \
  -H "Accept: application/json"
```

Bags launch token info:

```bash
curl http://localhost:8000/v1/bags/launch/token-info \
  -H "Content-Type: application/json" \
  -d '{
    "name": "OpenClaw",
    "symbol": "CLAW",
    "description": "OpenClaw launch test token",
    "imageUrl": "https://example.com/token.png",
    "twitter": "openclaw_xyz",
    "website": "https://openclaw.ai"
  }'
```

Bags fee analytics:

```bash
curl "http://localhost:8000/v1/bags/fees/claim-stats?tokenMint=YOUR_TOKEN_MINT"
```

Jupiter Earn tokens:

```bash
curl "http://localhost:8000/v1/jupiter/earn/tokens"
```

If you switch back to protected mode with `REQUIRE_BEARER_AUTH=true`, add:

```bash
-H "Authorization: Bearer YOUR_PROVIDER_GATEWAY_BEARER_TOKEN"
```

Houdini private quotes:

```bash
curl "http://localhost:8000/v1/houdini/quotes/private?from=sol-token-id&to=sol-token-id&amount=0.1" \
  -H "Authorization: Bearer YOUR_PROVIDER_GATEWAY_BEARER_TOKEN"
```

## Design notes

- simplicity first: one process, one app file, narrow endpoint surface
- security first: no raw generic Bags proxy, no raw unrestricted RPC passthrough
- user friendly: good default shared mode, with production EVM mainnet routing expected to stay on the gateway path
- launch flow stays non-custodial: gateway prepares metadata/config/launch tx, user wallet still signs and broadcasts
- EVM shared RPC remains allowlisted. It is intended for wallet reads, simulation, fee estimation, and raw tx broadcast from the local signer, not as a generic public Ethereum proxy.
- Houdini private swap routing stays non-custodial: the gateway owns partner secrets and compliance headers, but the local wallet still constructs the exact funding transfer locally, signs it, and broadcasts it.
- Houdini `x-user-ip` is derived at the gateway from ingress headers such as `cf-connecting-ip`, `x-real-ip`, or `x-forwarded-for`; the client does not supply the authoritative IP.

## Agent-wallet mode

`agent-wallet` can now use this service in two ways:

- shared RPC mode via `PROVIDER_GATEWAY_URL` for onboarding-friendly defaults
- explicit Bags launch / fees mode via the gateway-backed Bags client
- explicit Jupiter Earn mode via the gateway-backed Earn client
- explicit Houdini mode via the gateway-backed private payout client
- `wdk-evm-wallet` uses this service as its upstream RPC transport for `ethereum` / `base` / `robinhood` mainnet

Default Jupiter swap routing stays direct regardless of whether RPC is shared or user-owned. The gateway is used here for Bags launch/fees and Jupiter Earn, not for ordinary swaps.

Houdini routing is different: for production it is expected to go through this gateway so partner credentials and compliance headers are centralized server-side, while `agent-wallet` keeps local signing and approval policy.

## Railway

This repo is a monorepo, so deploy `provider-gateway/` as its own Railway service.

Recommended setup:

1. Create a new Railway project or open an existing one.
2. Add a new service from your GitHub repo.
3. In the service settings, set the root directory to `provider-gateway`.
4. In the service variables tab, define:
   - `REQUIRE_BEARER_AUTH=false` for the current public beta mode
   - `BAGS_API_KEY`
   - one RPC source for shared Solana RPC:
     - `SHARED_SOLANA_RPC_URL`, or
     - `HELIUS_API_KEY`, or
     - `ALCHEMY_API_KEY`
   - optional shared EVM RPC:
     - `SHARED_EVM_ETHEREUM_RPC_URL`
     - `SHARED_EVM_BASE_RPC_URL`
     - `SHARED_EVM_ROBINHOOD_RPC_URL`
     - `ALCHEMY_ETHEREUM_RPC_URL`
     - `ALCHEMY_BASE_RPC_URL`
     - `ALCHEMY_ROBINHOOD_RPC_URL`
     - or reuse `ALCHEMY_API_KEY`
   - optional:
     - `PROVIDER_GATEWAY_BEARER_TOKEN`
     - `BAGS_API_BASE_URL`
     - `HOUDINI_API_KEY`
     - `HOUDINI_API_SECRET`
     - `HOUDINI_API_BASE_URL`
     - `ALLOWED_ORIGINS`
     - `HTTP_TIMEOUT_SECONDS`
5. Set the start command below.
6. Deploy and verify `/health`, then `/v1/status`, then one Bags route and one safe RPC route such as `getLatestBlockhash`.

Recommended start command:

```bash
uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
```

Notes:

- Railway injects `PORT`; the command above already respects it.
- Keep `PROVIDER_GATEWAY_BEARER_TOKEN`, `BAGS_API_KEY`, and any RPC API keys as Railway service variables or sealed variables, not in repo files.
- Keep `HOUDINI_API_KEY` and `HOUDINI_API_SECRET` in Railway service variables only.
- Public beta mode can run with `REQUIRE_BEARER_AUTH=false`, but rate limiting / edge protection is still strongly recommended.
- For a Bags-only deployment, you can omit all RPC variables.
- For a shared-RPC deployment, you can omit `BAGS_API_KEY` only if you do not need any Bags endpoints.
- For Houdini-enabled deployment, add both Houdini partner secrets and keep the gateway behind auth or edge controls.

Example production variable sets:

1. Bags-only gateway
   - `REQUIRE_BEARER_AUTH=false`
   - `BAGS_API_KEY=...`

2. Bags + Jupiter Earn gateway
   - `REQUIRE_BEARER_AUTH=false`
   - `BAGS_API_KEY=...`
   - `JUPITER_API_KEY=...`

3. Bags + shared Solana RPC gateway
   - `REQUIRE_BEARER_AUTH=false`
   - `BAGS_API_KEY=...`
   - plus one of:
     - `SHARED_SOLANA_RPC_URL=...`
     - `HELIUS_API_KEY=...`
     - `ALCHEMY_API_KEY=...`

4. Houdini + shared Solana RPC gateway
   - `REQUIRE_BEARER_AUTH=true`
   - `PROVIDER_GATEWAY_BEARER_TOKEN=...`
   - `HOUDINI_API_KEY=...`
   - `HOUDINI_API_SECRET=...`
   - plus one of:
     - `SHARED_SOLANA_RPC_URL=...`
     - `HELIUS_API_KEY=...`
     - `ALCHEMY_API_KEY=...`

4. Shared EVM RPC gateway
   - `REQUIRE_BEARER_AUTH=true`
   - `PROVIDER_GATEWAY_BEARER_TOKEN=...`
   - plus one of:
     - `SHARED_EVM_ETHEREUM_RPC_URL=...`
     - `SHARED_EVM_BASE_RPC_URL=...`
     - `SHARED_EVM_ROBINHOOD_RPC_URL=...`
     - `ALCHEMY_ETHEREUM_RPC_URL=...`
     - `ALCHEMY_BASE_RPC_URL=...`
     - `ALCHEMY_ROBINHOOD_RPC_URL=...`
     - `ALCHEMY_API_KEY=...`

5. Protected gateway
   - `REQUIRE_BEARER_AUTH=true`
   - `PROVIDER_GATEWAY_BEARER_TOKEN=...`
   - `BAGS_API_KEY=...`
   - optionally `JUPITER_API_KEY=...`
   - optionally one shared RPC source
