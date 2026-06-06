import { test } from "node:test";
import assert from "node:assert/strict";

import { __testables } from "../src/wdk_evm_wallet.js";

const {
  PERMIT2_ADDRESS,
  UNISWAP_SUPPORTED_CHAIN_IDS,
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
  assert.deepEqual(UNISWAP_SUPPORTED_CHAIN_IDS, { ethereum: 1, base: 8453 });
});

test("permitData strips EIP712Domain and maps values to message", () => {
  const permitData = {
    domain: { name: "Permit2", chainId: 1, verifyingContract: PERMIT2_ADDRESS },
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "chainId", type: "uint256" },
        { name: "verifyingContract", type: "address" },
      ],
      PermitTransferFrom: [{ name: "permitted", type: "TokenPermissions" }],
      TokenPermissions: [{ name: "token", type: "address" }],
    },
    values: { permitted: { token: "0xabc" } },
  };
  const out = normalizeUniswapPermitData(permitData, { chainId: 1 });
  assert.equal(out.types.EIP712Domain, undefined);
  assert.ok(out.types.PermitTransferFrom);
  assert.ok(out.types.TokenPermissions);
  assert.deepEqual(out.message, { permitted: { token: "0xabc" } });
  assert.equal(out.domain.chainId, 1);
});

test("permitData rejects chainId mismatch", () => {
  const permitData = {
    domain: { chainId: 8453 },
    types: { X: [{ name: "a", type: "uint256" }] },
    values: {},
  };
  assert.throws(() => normalizeUniswapPermitData(permitData, { chainId: 1 }));
});

test("permitData rejects when only EIP712Domain present", () => {
  const permitData = {
    domain: { chainId: 1 },
    types: { EIP712Domain: [{ name: "name", type: "string" }] },
    values: {},
  };
  assert.throws(() => normalizeUniswapPermitData(permitData, { chainId: 1 }));
});
