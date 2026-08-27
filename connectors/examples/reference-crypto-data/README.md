# AgentLayer crypto-data reference connector

This is a neutral, read-only reference implementation for Connector Protocol
v1. It exposes public spot-price and asset-metadata tools. It does not receive a
wallet address, construct transactions, make payments, sign, or broadcast.

The upstream is Coinbase Exchange's public market-data API. The reference uses
the documented public ticker and currency endpoints and requires no API key:

- https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker
- https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/currencies/get-a-currency

Run locally:

```bash
npm ci --prefix connectors
npm run build --workspace @agentlayer.tech/reference-crypto-data-connector --prefix connectors
npm run start --workspace @agentlayer.tech/reference-crypto-data-connector --prefix connectors
```

The reviewed beta deployment is available at
`https://reference-crypto-data-production.up.railway.app`. Its manifest is
already pinned to that exact HTTPS endpoint. Re-run its live conformance check
after any immutable version release:

```bash
cd connectors
node conformance/dist/cli.js \
  --manifest examples/reference-crypto-data/connector.json \
  --fixture examples/reference-crypto-data/conformance.json \
  --endpoint https://reference-crypto-data-production.up.railway.app
```

## Railway deployment

Deploy this directory as one stateless service in a new, isolated Railway
project. Keep the repository root as the Docker build context and point the
service Dockerfile at
`connectors/examples/reference-crypto-data/Dockerfile` (for a root deployment,
set Railway's `RAILWAY_DOCKERFILE_PATH` service variable to that value).
Configure the Railway deployment health-check path as `/healthz` with a
10-second timeout and an `ON_FAILURE` restart policy. The service needs no
application variables, volume, database, wallet material, or connection to the
AgentLayer provider gateway.

After Railway generates the public domain:

1. update `connector.json` to that exact HTTPS URL;
2. redeploy the immutable manifest version;
3. run both live conformance and wallet invocation tests;
4. install the reviewed manifest with `wallet connectors install ... --enable --yes`.
