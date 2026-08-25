# AgentLayer read-only connector template

This is a minimal TypeScript connector suitable for an isolated Railway
service. It exposes `GET /healthz` and `POST /invoke` through the AgentLayer
Connector SDK.

## Customize

1. Change the connector identity, publisher, deployment URL, allowed upstream
   hosts, tools, and schemas in `connector.json`.
2. Replace the example handler in `src/connector.ts`.
3. Keep every community tool read-only and keep `transaction_intents: false`.
4. Add tests for normalization and every declared output shape.

From the repository's `connectors/` directory:

```bash
npm install
npm run check --workspace @agentlayer.tech/read-only-connector-template
npm run start --workspace @agentlayer.tech/read-only-connector-template
```

After deployment, replace `transport.url`, run the conformance suite, then
install the manifest locally with:

```bash
wallet connectors install ./connector.json --enable
```

Never put upstream credentials in `connector.json`. Configure them as Railway
service variables and keep `permissions.network_hosts` limited to exact public
HTTPS hosts.
