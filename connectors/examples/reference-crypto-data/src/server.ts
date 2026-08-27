import { startConnectorServer } from "@agentlayer.tech/connector-sdk";

import { connector } from "./connector.js";

const server = await startConnectorServer(connector);
console.log(
  JSON.stringify({
    event: "connector_started",
    connector_id: connector.manifest.id,
    connector_version: connector.manifest.version,
    address: server.address(),
  })
);
