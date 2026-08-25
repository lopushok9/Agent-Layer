# AgentLayer Connector SDK

TypeScript types and runtime helpers for AgentLayer Connector Protocol v1.

The initial SDK supports read-only connectors only. It does not expose wallet
signing, transaction execution, approval tokens, or private wallet material.

```bash
npm install @agentlayer.tech/connector-sdk
```

Node.js 24 or newer is required.

## Example

```ts
import { readFileSync } from "node:fs";
import {
  defineReadOnlyConnector,
  startConnectorServer,
  type ConnectorManifest,
} from "@agentlayer.tech/connector-sdk";

const manifest = JSON.parse(
  readFileSync(new URL("./connector.json", import.meta.url), "utf8")
) as ConnectorManifest;

const connector = defineReadOnlyConnector({
  manifest,
  handlers: {
    async get_pools(arguments_, context) {
      return { pools: [] };
    },
  },
});

await startConnectorServer(connector);
```

`defineReadOnlyConnector` rejects write-capable manifests, undeclared handlers,
identity drift, invalid arguments, invalid handler output, non-JSON values, and
response TTLs longer than five minutes. `startConnectorServer` exposes only
`GET /healthz` and `POST /invoke`, limits request bodies, and returns generic
errors for unexpected failures.

Use the complete starter in `../templates/read-only` rather than beginning from
the abbreviated snippet above.
