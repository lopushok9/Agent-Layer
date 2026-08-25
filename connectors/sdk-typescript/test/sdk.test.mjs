import assert from "node:assert/strict";
import { Readable } from "node:stream";
import test from "node:test";

import {
  ConnectorSdkError,
  createConnectorHttpHandler,
  defineReadOnlyConnector,
} from "../dist/index.js";

function manifest(overrides = {}) {
  return {
    schema_version: 1,
    id: "com.example.markets",
    name: "Example Markets",
    version: "1.0.0",
    artifact_digest: `sha256:${"a".repeat(64)}`,
    publisher: { id: "example", name: "Example" },
    agentlayer: { protocol_version: 1, runtime_range: ">=0.1.101" },
    trust: "community_read_only",
    transport: { type: "https", url: "https://connector.example.com/v1" },
    permissions: {
      wallet_address: false,
      transaction_intents: false,
      network_hosts: ["api.example.com"],
    },
    tools: [
      {
        name: "get_markets",
        description: "Get markets.",
        read_only: true,
        risk_level: "low",
        input_schema: {
          type: "object",
          properties: { limit: { type: "integer", minimum: 1, maximum: 10 } },
          required: ["limit"],
          additionalProperties: false,
        },
        output_schema: {
          type: "object",
          properties: { markets: { type: "array", items: { type: "string" } } },
          required: ["markets"],
          additionalProperties: false,
        },
      },
    ],
    ...overrides,
  };
}

function request(overrides = {}) {
  return {
    protocol_version: 1,
    request_id: "request-123",
    connector: {
      id: "com.example.markets",
      version: "1.0.0",
      artifact_digest: `sha256:${"a".repeat(64)}`,
    },
    tool: "get_markets",
    arguments: { limit: 2 },
    context: { chain: "evm", network: "base" },
    ...overrides,
  };
}

test("builds a short-lived identity-bound read result", async () => {
  const connector = defineReadOnlyConnector({
    manifest: manifest(),
    handlers: { get_markets: ({ limit }) => ({ markets: Array(limit).fill("USDC") }) },
  });
  const result = await connector.invoke(request());
  assert.equal(result.kind, "read_result");
  assert.deepEqual(result.result, { markets: ["USDC", "USDC"] });
  assert.equal(result.connector.artifact_digest, `sha256:${"a".repeat(64)}`);
  assert.ok(Date.parse(result.expires_at) > Date.now());
});

test("rejects identity mismatch and invalid arguments", async () => {
  const connector = defineReadOnlyConnector({
    manifest: manifest(),
    handlers: { get_markets: () => ({ markets: [] }) },
  });
  await assert.rejects(
    connector.invoke(request({ connector: { id: "com.attacker", version: "1.0.0" } })),
    (error) => error instanceof ConnectorSdkError && error.code === "identity_mismatch"
  );
  await assert.rejects(
    connector.invoke(request({ arguments: { limit: 100 } })),
    (error) => error instanceof ConnectorSdkError && error.code === "invalid_arguments"
  );
});

test("rejects handler output that violates the public schema", async () => {
  const connector = defineReadOnlyConnector({
    manifest: manifest(),
    handlers: { get_markets: () => ({ markets: "not-an-array" }) },
  });
  await assert.rejects(
    connector.invoke(request()),
    (error) => error instanceof ConnectorSdkError && error.code === "invalid_result"
  );
});

test("refuses write-capable manifests and undeclared handlers", () => {
  assert.throws(
    () =>
      defineReadOnlyConnector({
        manifest: manifest({ trust: "verified_write" }),
        handlers: { get_markets: () => ({ markets: [] }) },
      }),
    (error) => error instanceof ConnectorSdkError && error.code === "write_not_supported"
  );
  assert.throws(
    () =>
      defineReadOnlyConnector({
        manifest: manifest(),
        handlers: {
          get_markets: () => ({ markets: [] }),
          hidden_write: () => ({ transaction: "0x" }),
        },
      }),
    (error) => error instanceof ConnectorSdkError && error.code === "unknown_handler"
  );
});

test("serves only health and JSON invoke routes", async () => {
  const connector = defineReadOnlyConnector({
    manifest: manifest(),
    handlers: { get_markets: () => ({ markets: ["USDC"] }) },
  });
  const handler = createConnectorHttpHandler(connector);
  const body = JSON.stringify(request());
  const incoming = Object.assign(Readable.from([body]), {
    method: "POST",
    url: "/invoke",
    headers: { "content-type": "application/json", "content-length": String(Buffer.byteLength(body)) },
  });
  const captured = { statusCode: 0, headers: {}, body: "" };
  const response = {
    writeHead(statusCode, headers) {
      captured.statusCode = statusCode;
      captured.headers = headers;
    },
    end(value) {
      captured.body = String(value ?? "");
    },
  };
  await handler(incoming, response);
  assert.equal(captured.statusCode, 200);
  assert.equal(JSON.parse(captured.body).kind, "read_result");
  assert.equal(captured.headers["cache-control"], "no-store");
});
