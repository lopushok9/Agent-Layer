# Provider Gateway

`provider-gateway` is a small shared infrastructure service for OpenClaw.

It is intended to solve two onboarding problems:

- users should not need to bring their own Bags API key to get started
- users should not need to bring their own Helius/Alchemy key to get a reasonable default RPC path

This service is deliberately narrow:

- shared Bags trade + claim relay
- shared Bags token launch relay
- shared Jupiter Earn relay
- shared Flash Trade perps read relay
- shared Solana RPC gateway with method allowlist
- shared EVM RPC gateway for ethereum/base with method allowlist
- no wallet custody
- no transaction signing

Signing stays on the user machine in `agent-wallet`.

Shared RPC mode is intentionally mainnet-only. Devnet and testnet should use direct public RPC endpoints instead of the gateway.

## Current scope

Implemented endpoints:

- `GET /health` — public health and capability snapshot
- `GET /v1/status` — authenticated status and provider capabilities
- `POST /v1/rpc` — authenticated Solana JSON-RPC proxy with method allowlist
- `POST /v1/evm/rpc/{network}` — authenticated raw EVM JSON-RPC proxy for `ethereum` / `base`
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
- `GET /v1/flash/perps/markets` — authenticated Flash Trade perpetual market relay
- `GET /v1/flash/perps/positions` — authenticated Flash Trade perpetual positions relay
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

The wallet backend emits one fire-and-forget, anonymous event per tool invocation
so we can measure adoption across hosts (Claude Code / Codex / Hermes / OpenClaw)
without any PII. The ingest route is intentionally unauthenticated (events arrive
from every install) and validated against a strict allowlist in
`telemetry_store.py`: only `event`, `install_id` (a random local UUID),
`host`, `tool` (registered tool name), `backend`, `plugin_version`, `ok`, `ts`
are accepted. Any extra field — and anything address-like in `tool` — is rejected
(`422`). No wallet addresses, balances, amounts, tx hashes, tool arguments, or
secrets are ever stored.

Config:

- `TELEMETRY_ENABLED` — server-side kill switch (default `true`)
- `TELEMETRY_DB_PATH` — SQLite path (default `./telemetry.db`; point at a mounted
  volume on Railway for durable history — the default file resets on redeploy)
- `TELEMETRY_RATE_LIMIT_PER_MIN` — per-IP ingest cap (default `120`)

`GET /v1/telemetry/stats?window_days=30` is gated by the same bearer/machine
token as `/v1/status` so raw numbers are not world-readable. In a browser
(`Accept: text/html`) it renders a minimal terminal-style dashboard with
server-side ASCII charts for events, active installs, RPC usage, downloads, and
tool invocations. For raw machine-readable JSON use:

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
  - `SHARED_EVM_ETHEREUM_RPC_URL` / `SHARED_EVM_BASE_RPC_URL`, or
  - `ALCHEMY_ETHEREUM_RPC_URL` / `ALCHEMY_BASE_RPC_URL`, or
  - `ALCHEMY_API_KEY`
- Bags relay:
  - `BAGS_API_KEY`
- Jupiter Earn relay:
  - `JUPITER_API_KEY`
- Flash Trade read relay:
  - `FLASH_API_BASE_URL`
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
- `wdk-evm-wallet` uses this service as its upstream RPC transport for `ethereum` / `base` mainnet

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
     - `ALCHEMY_ETHEREUM_RPC_URL`
     - `ALCHEMY_BASE_RPC_URL`
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
     - `ALCHEMY_ETHEREUM_RPC_URL=...`
     - `ALCHEMY_BASE_RPC_URL=...`
     - `ALCHEMY_API_KEY=...`

5. Protected gateway
   - `REQUIRE_BEARER_AUTH=true`
   - `PROVIDER_GATEWAY_BEARER_TOKEN=...`
   - `BAGS_API_KEY=...`
   - optionally `JUPITER_API_KEY=...`
   - optionally one shared RPC source
