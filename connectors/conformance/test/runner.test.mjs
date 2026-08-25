import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import test from "node:test";

import {
  createConnectorHttpHandler,
  defineReadOnlyConnector,
} from "@agentlayer.tech/connector-sdk";
import { runConformance } from "../dist/index.js";

const manifest = JSON.parse(
  await readFile(new URL("../../templates/read-only/connector.json", import.meta.url), "utf8")
);
const fixture = { schema_version: 1, tools: { get_pools: { arguments: { chain: "base" } } } };
const invalidIdentityResponse = JSON.parse(
  await readFile(new URL("./fixtures/invalid-response-identity.json", import.meta.url), "utf8")
);
const missingToolFixture = JSON.parse(
  await readFile(new URL("./fixtures/missing-tool-fixture.json", import.meta.url), "utf8")
);

function response(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function conformingFetch(url, options = {}) {
  if (String(url).endsWith("/healthz")) {
    return Promise.resolve(
      response(200, { ok: true, connector: { id: manifest.id, version: manifest.version } })
    );
  }
  const request = JSON.parse(options.body);
  if (request.connector.id !== manifest.id || request.tool === "__conformance_unknown_tool__") {
    return Promise.resolve(response(409, { ok: false }));
  }
  return Promise.resolve(
    response(200, {
      protocol_version: 1,
      request_id: request.request_id,
      connector: request.connector,
      tool: request.tool,
      kind: "read_result",
      result: { pools: [] },
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    })
  );
}

test("passes a conforming read-only endpoint", async () => {
  const report = await runConformance({
    manifest,
    fixture,
    endpoint: "https://connector.example.com",
    fetchImpl: conformingFetch,
  });
  assert.equal(report.ok, true, JSON.stringify(report.checks));
  assert.ok(report.checks.length >= 6);
});

test("reports response identity drift", async () => {
  const report = await runConformance({
    manifest,
    fixture,
    endpoint: "https://connector.example.com",
    fetchImpl: async (url, options = {}) => {
      const result = await conformingFetch(url, options);
      if (!String(url).endsWith("/invoke") || result.status !== 200) return result;
      const payload = await result.json();
      return response(200, {
        ...invalidIdentityResponse,
        request_id: payload.request_id,
        expires_at: payload.expires_at,
      });
    },
  });
  assert.equal(report.ok, false);
  assert.equal(report.checks.find((check) => check.name === "tool:get_pools:invoke")?.ok, false);
});

test("fails when a declared tool has no fixture", async () => {
  const report = await runConformance({
    manifest,
    fixture: missingToolFixture,
    endpoint: "https://connector.example.com",
    fetchImpl: conformingFetch,
  });
  assert.equal(report.ok, false);
  assert.equal(report.checks.find((check) => check.name === "fixture_coverage")?.ok, false);
});

test("passes against the real SDK HTTP wire contract", async (context) => {
  const connector = defineReadOnlyConnector({
    manifest,
    handlers: { get_pools: () => ({ pools: [] }) },
  });
  const handler = createConnectorHttpHandler(connector);
  const server = createServer((request, response_) => void handler(request, response_));
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  context.after(() => new Promise((resolve) => server.close(resolve)));
  const address = server.address();
  assert.ok(address && typeof address === "object");

  const report = await runConformance({
    manifest,
    fixture,
    endpoint: `http://127.0.0.1:${address.port}`,
  });
  assert.equal(report.ok, true, JSON.stringify(report.checks));
});
