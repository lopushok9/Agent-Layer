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
