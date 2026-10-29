import assert from "node:assert/strict";
import test from "node:test";
import { publicWalletError, walletErrorDiagnostic } from "../src/wallet-errors.js";

test("provider URLs, credentials and request bodies never become public wallet errors", () => {
  const secret = "RPC failed: https://provider.example/v2/private-api-key request body: signing-secret";
  const safe = publicWalletError(new Error(secret)).message;
  assert.doesNotMatch(safe, /private-api-key|signing-secret|provider.example/);
  assert.equal(publicWalletError(new Error("RPC chain ID mismatch")).message, "RPC chain ID mismatch");
});

test("execution diagnostics retain safe CDP categories and correlation IDs, never provider payloads", () => {
  const error = Object.assign(new Error("AA21 didn't pay prefund https://rpc.example/private-key calldata=0xsecret"), { name: "APIError", statusCode: 400, errorType: "invalid_request", correlationId: "11111111-2222-3333-4444-555555555555", errorMessage: "signing-secret", request: { signature: "private-signature" } });
  assert.deepEqual(walletErrorDiagnostic(error), { error_type: "invalid_request", category: "insufficient_funds", status_code: 400, correlation_id: error.correlationId });
  assert.doesNotMatch(JSON.stringify(walletErrorDiagnostic(error)), /private-key|signing-secret|private-signature|rpc.example|0xsecret/);
  error.errorType = "private-signature"; error.correlationId = "https://rpc.example/private-key";
  assert.deepEqual(walletErrorDiagnostic(error), { error_type: "unexpected_error", category: "insufficient_funds", status_code: 400 });
});

test("asset mismatch and minimum_received messages reach the agent verbatim", () => {
  for (const m of [
    "simulated asset changes differ from preview (0x833589fcd6edb6e08f4c7c32d4f71b54bda02913: previewed 457, minimum 454, now 369); prepare and confirm a new operation",
    "simulated asset changes differ from preview (0x4200000000000000000000000000000000000006: previewed none, now -1); prepare and confirm a new operation",
    "minimum_received for 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 must be a token this batch receives, at most its simulated amount",
  ]) assert.equal(publicWalletError(new Error(m)).message, m);
});
