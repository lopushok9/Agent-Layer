# Provider Gateway

`provider-gateway` is a small shared infrastructure service for OpenClaw.

It is intended to solve two onboarding problems:

- users should not need to bring their own Bags API key to get started
- users should not need to bring their own Helius/Alchemy key to get a reasonable default RPC path

This service is deliberately narrow:

- shared Bags trade + claim relay
- shared Bags token launch relay
- shared Solana RPC gateway with method allowlist
- no wallet custody
- no transaction signing

Signing stays on the user machine in `agent-wallet`.

Shared RPC mode is intentionally mainnet-only. Devnet and testnet should use direct public RPC endpoints instead of the gateway.

## Current scope

Implemented endpoints:

- `GET /health` — public health and capability snapshot
- `GET /v1/status` — authenticated status and provider capabilities
- `POST /v1/rpc` — authenticated Solana JSON-RPC proxy with method allowlist
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

Not implemented yet:

- partner endpoints
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

Required for a useful deployment:

- one shared RPC source:
  - `SHARED_SOLANA_RPC_URL`, or
  - `HELIUS_API_KEY`, or
  - `ALCHEMY_API_KEY`
- `BAGS_API_KEY`

Optional:

- `PROVIDER_GATEWAY_BEARER_TOKEN` when `REQUIRE_BEARER_AUTH=true`

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

If you switch back to protected mode with `REQUIRE_BEARER_AUTH=true`, add:

```bash
-H "Authorization: Bearer YOUR_PROVIDER_GATEWAY_BEARER_TOKEN"
```

## Design notes

- simplicity first: one process, one app file, narrow endpoint surface
- security first: no raw generic Bags proxy, no raw unrestricted RPC passthrough
- user friendly: good default shared mode, while future `agent-wallet` integration can switch to direct user RPC when user keys are configured
- launch flow stays non-custodial: gateway prepares metadata/config/launch tx, user wallet still signs and broadcasts

## Agent-wallet mode

`agent-wallet` can now use this service in two ways:

- shared RPC mode via `PROVIDER_GATEWAY_URL` for onboarding-friendly defaults
- explicit Bags launch / fees mode via the gateway-backed Bags client

Default swap routing stays on Jupiter regardless of whether RPC is shared or user-owned. Bags is used here for launch, fee claims, and fee analytics flows, not swap routing.

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
   - optional:
     - `PROVIDER_GATEWAY_BEARER_TOKEN`
     - `BAGS_API_BASE_URL`
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
- Public beta mode can run with `REQUIRE_BEARER_AUTH=false`, but rate limiting / edge protection is still strongly recommended.
- For a Bags-only deployment, you can omit all RPC variables.
- For a shared-RPC deployment, you can omit `BAGS_API_KEY` only if you do not need any Bags endpoints.

Example production variable sets:

1. Bags-only gateway
   - `REQUIRE_BEARER_AUTH=false`
   - `BAGS_API_KEY=...`

2. Bags + shared Solana RPC gateway
   - `REQUIRE_BEARER_AUTH=false`
   - `BAGS_API_KEY=...`
   - plus one of:
     - `SHARED_SOLANA_RPC_URL=...`
     - `HELIUS_API_KEY=...`
     - `ALCHEMY_API_KEY=...`

3. Protected gateway
   - `REQUIRE_BEARER_AUTH=true`
   - `PROVIDER_GATEWAY_BEARER_TOKEN=...`
   - `BAGS_API_KEY=...`
   - optionally one shared RPC source
