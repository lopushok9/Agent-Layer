import assert from "node:assert/strict";
import test from "node:test";
import { publicWalletError } from "../src/wallet-errors.js";

test("provider URLs, credentials and request bodies never become public wallet errors", () => {
  const secret = "RPC failed: https://provider.example/v2/private-api-key request body: signing-secret";
  const safe = publicWalletError(new Error(secret)).message;
  assert.doesNotMatch(safe, /private-api-key|signing-secret|provider.example/);
  assert.equal(publicWalletError(new Error("RPC chain ID mismatch")).message, "RPC chain ID mismatch");
});
