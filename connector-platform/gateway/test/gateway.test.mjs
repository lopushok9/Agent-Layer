import assert from "node:assert/strict";
import crypto from "node:crypto";
import test from "node:test";
import { createGateway, GatewayError, verifyPayload } from "../src/gateway.mjs";

const CONNECTOR_ID = "com.example.lending";
const VERSION = "1.0.0";
const ARTIFACT = `sha256:${"a".repeat(64)}`;

function fixture({ enabled = true, readOnly = false } = {}) {
  const { privateKey, publicKey } = crypto.generateKeyPairSync("ed25519");
  const routes = {
    [`${CONNECTOR_ID}@${VERSION}`]: {
      connector_id: CONNECTOR_ID,
      version: VERSION,
      artifact_digest: ARTIFACT,
      trust: readOnly ? "verified_read_only" : "verified_write",
      enabled,
      endpoint: "https://connector.example.com/v1/invoke",
      tools: {
        [readOnly ? "get_markets" : "supply"]: { read_only: readOnly },
      },
    },
  };
  return { privateKey, publicKey, routes };
}

test("gateway pins the route, signs invocation, and attests the response", async () => {
  const { privateKey, publicKey, routes } = fixture();
  let receivedEnvelope;
  const gateway = createGateway({
    routes,
    privateKey,
    keyId: "gateway-test-key",
    clock: () => new Date("2026-08-25T12:00:00.000Z"),
    fetchImpl: async (url, options) => {
      assert.equal(url, "https://connector.example.com/v1/invoke");
      assert.equal(options.redirect, "manual");
      receivedEnvelope = JSON.parse(options.body);
      const { gateway_attestation: attestation, ...unsigned } = receivedEnvelope;
      assert.equal(verifyPayload(unsigned, attestation, publicKey), true);
      return new Response(
        JSON.stringify({
          protocol_version: 1,
          request_id: receivedEnvelope.request_id,
          connector: {
            id: CONNECTOR_ID,
            version: VERSION,
            artifact_digest: ARTIFACT,
          },
          tool: "supply",
          kind: "evm_transaction_intent",
          intent: { unsigned: true },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  });
  const result = await gateway.invoke({
    connectorId: CONNECTOR_ID,
    version: VERSION,
    body: {
      artifact_digest: ARTIFACT,
      tool: "supply",
      arguments: { amount_raw: "1000" },
      context: { chain: "evm", chain_id: 8453, wallet_address: `0x${"1".repeat(40)}` },
    },
  });
  const { gateway_attestation: responseAttestation, ...unsignedResponse } = result;
  assert.equal(verifyPayload(unsignedResponse, responseAttestation, publicKey), true);
  assert.equal(receivedEnvelope.connector.artifact_digest, ARTIFACT);
  assert.equal(receivedEnvelope.expires_at, "2026-08-25T12:00:30.000Z");
});

test("gateway rejects disabled and mismatched artifacts before transport", async () => {
  const { privateKey, routes } = fixture({ enabled: false });
  let called = false;
  const gateway = createGateway({
    routes,
    privateKey,
    keyId: "key",
    fetchImpl: async () => {
      called = true;
      return new Response("{}", { status: 200 });
    },
  });
  await assert.rejects(
    gateway.invoke({
      connectorId: CONNECTOR_ID,
      version: VERSION,
      body: { artifact_digest: ARTIFACT, tool: "supply", arguments: {} },
    }),
    (error) => error instanceof GatewayError && error.code === "connector_unavailable",
  );
  assert.equal(called, false);

  const enabledGateway = createGateway({
    routes: fixture().routes,
    privateKey,
    keyId: "key",
    fetchImpl: async () => {
      called = true;
      return new Response("{}", { status: 200 });
    },
  });
  await assert.rejects(
    enabledGateway.invoke({
      connectorId: CONNECTOR_ID,
      version: VERSION,
      body: { artifact_digest: `sha256:${"b".repeat(64)}`, tool: "supply", arguments: {} },
    }),
    /artifact digest/,
  );
  assert.equal(called, false);
});

test("read-only routes cannot relay transaction intents", async () => {
  const { privateKey, routes } = fixture({ readOnly: true });
  const gateway = createGateway({
    routes,
    privateKey,
    keyId: "key",
    fetchImpl: async (_url, options) => {
      const request = JSON.parse(options.body);
      return new Response(
        JSON.stringify({
          protocol_version: 1,
          request_id: request.request_id,
          connector: { id: CONNECTOR_ID, version: VERSION, artifact_digest: ARTIFACT },
          tool: "get_markets",
          kind: "evm_transaction_intent",
        }),
        { status: 200 },
      );
    },
  });
  await assert.rejects(
    gateway.invoke({
      connectorId: CONNECTOR_ID,
      version: VERSION,
      body: { artifact_digest: ARTIFACT, tool: "get_markets", arguments: {} },
    }),
    /kind is not allowed/,
  );
});

