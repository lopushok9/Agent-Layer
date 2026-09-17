import assert from "node:assert/strict";
import test from "node:test";

import { __testables } from "../src/wdk_evm_wallet.js";

const { assertValidNetwork } = __testables;

test("assertValidNetwork accepts every supported network plus aliases", () => {
  assert.equal(assertValidNetwork("ethereum"), "ethereum");
  assert.equal(assertValidNetwork("sepolia"), "sepolia");
  assert.equal(assertValidNetwork("base"), "base");
  assert.equal(assertValidNetwork("base-sepolia"), "base-sepolia");
  assert.equal(assertValidNetwork("robinhood"), "robinhood");
  assert.equal(assertValidNetwork("robinhood-mainnet"), "robinhood");
});

test("assertValidNetwork treats blank input as unset", () => {
  assert.equal(assertValidNetwork(undefined), null);
  assert.equal(assertValidNetwork(null), null);
  assert.equal(assertValidNetwork(""), null);
});

test("assertValidNetwork rejects unsupported networks", () => {
  assert.throws(
    () => assertValidNetwork("polygon"),
    /ethereum, sepolia, base, base-sepolia, robinhood/
  );
});
