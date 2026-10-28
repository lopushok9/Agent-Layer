import assert from "node:assert/strict";
import test from "node:test";
import { assetChangesWithinPreview } from "../src/asset-changes.js";

const usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", weth = "0x4200000000000000000000000000000000000006";
const change = (address: string, pre: string, post: string, diff: string) => ({ token: { address, decimals: 6, symbol: "T" }, value: { pre, post, diff } });

test("unrelated balance drift between preview and execution does not block signing", () => {
  const preview = [change(usdc, "5000000", "4000000", "-1000000"), change(weth, "0", "300", "300")];
  // An incoming transfer and an x402 payment moved absolute balances; deltas are unchanged.
  const fresh = [change(weth, "7", "307", "300"), change(usdc.toLowerCase(), "4900000", "3900000", "-1000000")];
  assert.equal(assetChangesWithinPreview(preview, fresh), true);
});

test("worse deltas, changed token sets and malformed simulations block signing", () => {
  const preview = [change(usdc, "5", "4", "-1000000"), change(weth, "0", "300", "300")];
  assert.equal(assetChangesWithinPreview(preview, [change(usdc, "5", "4", "-1000001"), change(weth, "0", "300", "300")]), false, "larger outflow");
  assert.equal(assetChangesWithinPreview(preview, [change(usdc, "5", "4", "-1000000"), change(weth, "0", "299", "299")]), false, "smaller inflow");
  assert.equal(assetChangesWithinPreview(preview, [change(usdc, "5", "4", "-1000000")]), false, "missing token");
  assert.equal(assetChangesWithinPreview(preview, [...preview, change("0x0000000000000000000000000000000000000001", "1", "0", "-1")]), false, "new token");
  assert.equal(assetChangesWithinPreview(preview, [change(usdc, "5", "4", "-1000000"), change(usdc, "5", "4", "-1000000")]), false, "duplicate token");
  assert.equal(assetChangesWithinPreview(preview, ["changed"]), false);
  assert.equal(assetChangesWithinPreview(preview, [change(usdc, "5", "4", "1.5"), change(weth, "0", "300", "300")]), false);
});

test("a better outcome for the wallet passes; empty simulations stay comparable", () => {
  const preview = [change(weth, "0", "300", "300")];
  assert.equal(assetChangesWithinPreview(preview, [change(weth, "0", "301", "301")]), true);
  assert.equal(assetChangesWithinPreview(undefined, undefined), true);
  assert.equal(assetChangesWithinPreview([], []), true);
});
