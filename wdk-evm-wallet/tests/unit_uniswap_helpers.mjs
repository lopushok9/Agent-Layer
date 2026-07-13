import { test } from "node:test";
import assert from "node:assert/strict";

import { __testables } from "../src/wdk_evm_wallet.js";

const {
  PERMIT2_ADDRESS,
  UNISWAP_SUPPORTED_CHAIN_IDS,
  UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK,
  normalizeUniswapTokenAddress,
  assertUniswapSupportedNetwork,
  uniswapSlippagePercentFromBps,
  normalizeUniswapPermitData,
} = __testables;

test("native aliases normalize to the zero address", () => {
  const zero = "0x0000000000000000000000000000000000000000";
  assert.equal(normalizeUniswapTokenAddress("native", "tokenIn"), zero);
  assert.equal(normalizeUniswapTokenAddress("ETH", "tokenIn"), zero);
  assert.equal(normalizeUniswapTokenAddress(zero, "tokenIn"), zero);
});

test("erc20 address is validated and lowercased", () => {
  assert.equal(
    normalizeUniswapTokenAddress("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "tokenOut"),
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
  );
  assert.throws(() => normalizeUniswapTokenAddress("not-an-address", "tokenOut"));
});

test("supported network assertion returns chain id", () => {
  assert.equal(assertUniswapSupportedNetwork("ethereum"), 1);
  assert.equal(assertUniswapSupportedNetwork("base"), 8453);
  assert.equal(assertUniswapSupportedNetwork("robinhood"), 4663);
  assert.throws(() => assertUniswapSupportedNetwork("sepolia"));
  assert.throws(() => assertUniswapSupportedNetwork("base-sepolia"));
});

test("slippage bps converts to percent", () => {
  assert.equal(uniswapSlippagePercentFromBps(50), 0.5);
  assert.equal(uniswapSlippagePercentFromBps(100), 1);
  assert.equal(uniswapSlippagePercentFromBps(0), 0);
  assert.throws(() => uniswapSlippagePercentFromBps(-1));
  assert.throws(() => uniswapSlippagePercentFromBps(6000));
  assert.throws(() => uniswapSlippagePercentFromBps(1.5));
});

test("exports constants", () => {
  assert.equal(PERMIT2_ADDRESS, "0x000000000022D473030F116dDEE9F6B43aC78BA3");
  assert.deepEqual(UNISWAP_SUPPORTED_CHAIN_IDS, { ethereum: 1, base: 8453, robinhood: 4663 });
});

test("universal router allow-list has the expected addresses per network", () => {
  assert.deepEqual(UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK, {
    ethereum: "0x66a9893cc07d91d95644aedd05d03f95e1dba8af",
    base: "0x6ff5693b99212da76ad316178a184ab56d299b43",
    robinhood: "0x8876789976decbfcbbbe364623c63652db8c0904",
  });
});
