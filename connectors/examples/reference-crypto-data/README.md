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

Before publishing its manifest, replace `transport.url` with the final HTTPS
deployment and run the conformance suite against that exact endpoint.

## Railway deployment

Deploy this directory as one stateless service in a new, isolated Railway
project. Point the service at `railway.toml` while keeping the repository root
as the build context. The service needs no variables, volume, database, wallet
material, or connection to the AgentLayer provider gateway.

After Railway generates the public domain:

1. update `connector.json` to that exact HTTPS URL;
2. redeploy the immutable manifest version;
3. run both live conformance and wallet invocation tests;
4. install the reviewed manifest with `wallet connectors install ... --enable --yes`.
