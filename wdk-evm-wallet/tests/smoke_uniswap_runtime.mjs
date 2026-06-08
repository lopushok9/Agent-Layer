import assert from "node:assert/strict";
import test from "node:test";

import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

import { WdkEvmWalletService } from "../src/wdk_evm_wallet.js";

const VALID_MNEMONIC =
  "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const ADDRESS = "0x1111111111111111111111111111111111111111";
const ZERO = "0x0000000000000000000000000000000000000000";
const PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3";
// Universal Router v2.0 on base (must match UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK).
const BASE_ROUTER = "0x6ff5693b99212da76ad316178a184ab56d299b43";
const BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";

const NAME_SELECTOR = "0x06fdde03";
const SYMBOL_SELECTOR = "0x95d89b41";
const DECIMALS_SELECTOR = "0x313ce567";
const ALLOWANCE_SELECTOR = "0xdd62ed3e";

function encodeAbiString(value) {
  const data = Buffer.from(value, "utf8").toString("hex");
  const offset = "20".padStart(64, "0");
  const length = (data.length / 2).toString(16).padStart(64, "0");
  return `0x${offset}${length}${data.padEnd(Math.ceil(data.length / 64) * 64, "0")}`;
}

// Mirrors the live Trading API shape: Permit2 AllowanceTransfer (PermitSingle),
// domain has no `version`, and `types` does not include an EIP712Domain entry.
function permitDataFixture(chainId) {
  return {
    domain: { name: "Permit2", chainId, verifyingContract: PERMIT2 },
    types: {
      PermitSingle: [
        { name: "details", type: "PermitDetails" },
        { name: "spender", type: "address" },
        { name: "sigDeadline", type: "uint256" },
      ],
      PermitDetails: [
        { name: "token", type: "address" },
        { name: "amount", type: "uint160" },
        { name: "expiration", type: "uint48" },
        { name: "nonce", type: "uint48" },
      ],
    },
    values: {
      details: { token: BASE_USDC, amount: "1000000", expiration: "9999999999", nonce: "0" },
      spender: BASE_ROUTER,
      sigDeadline: "9999999999",
    },
  };
}

function createHarness(options = {}) {
  const chainId = 8453;
  const network = "base";
  const providerUrl = "http://fake-rpc.local";
  const apiBase = "https://uniswap-test.local/v1";
  const state = {
    allowance: BigInt(options.initialAllowance ?? 0n),
    quoteBodies: [],
    swapBodies: [],
    signCalls: 0,
    sendCalls: [],
    approveCalls: [],
  };

  const fakeAccount = {
    async getAddress() {
      return ADDRESS;
    },
    async getAllowance() {
      return state.allowance;
    },
    async quoteSendTransaction() {
      return { fee: "2" };
    },
    async approve({ amount }) {
      state.allowance = BigInt(amount);
      state.approveCalls.push(String(amount));
      return { hash: `0x${"a".repeat(64)}`, fee: "2" };
    },
    async signTypedData() {
      state.signCalls += 1;
      return `0x${"b".repeat(130)}`;
    },
    async sendTransaction(tx) {
      state.sendCalls.push({ to: String(tx.to), value: String(tx.value) });
      return { hash: `0x${"d".repeat(64)}`, fee: "3" };
    },
  };

  const originals = {
    getAccount: WalletManagerEvm.prototype.getAccount,
    dispose: WalletManagerEvm.prototype.dispose,
    fetch: globalThis.fetch,
  };

  WalletManagerEvm.prototype.getAccount = async function getAccount() {
    return fakeAccount;
  };
  WalletManagerEvm.prototype.dispose = function dispose() {};

  globalThis.fetch = async (url, init = {}) => {
    const requestUrl = String(url || "");
    if (requestUrl.startsWith(apiBase)) {
      const body = JSON.parse(String(init.body || "{}"));
      state.lastHeaders = init.headers || {};
      const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });
      if (requestUrl.endsWith("/quote")) {
        state.quoteBodies.push(body);
        const routing = options.routing || "CLASSIC";
        if (routing !== "CLASSIC") {
          return ok({ routing, quote: {} });
        }
        const erc20In = body.tokenIn !== ZERO;
        // Successive /quote calls can return drifting output amounts (preview vs
        // execute re-quote) to exercise quote-drift handling, mirroring the live
        // Trading API where the quoted output moves every block.
        const outputAmount = Array.isArray(options.quoteOutputAmounts)
          ? options.quoteOutputAmounts[
              Math.min(state.quoteBodies.length - 1, options.quoteOutputAmounts.length - 1)
            ]
          : options.outputAmount || "990000";
        return ok({
          routing: "CLASSIC",
          quote: {
            input: { token: body.tokenIn, amount: body.amount },
            output: {
              token: body.tokenOut,
              amount: outputAmount,
              minimumAmount: options.minimumAmount || "985000",
            },
            slippage: body.slippageTolerance,
            gasFee: "5000000000000000",
            gasFeeUSD: "0.01",
          },
          permitData: erc20In ? permitDataFixture(chainId) : null,
        });
      }
      if (requestUrl.endsWith("/swap")) {
        state.swapBodies.push(body);
        return ok({
          swap: {
            to: options.swapRouter || BASE_ROUTER,
            data: options.swapData || "0xabcdef",
            value: options.swapValue || "0x0",
          },
        });
      }
      throw new Error(`unexpected uniswap path: ${requestUrl}`);
    }
    // RPC eth_call mock (token metadata, allowance, simulation).
    const body = JSON.parse(String(init.body || "{}"));
    const ok = (result) => ({ ok: true, json: async () => ({ jsonrpc: "2.0", id: 1, result }) });
    if (body.method === "eth_call") {
      const data = String(body.params?.[0]?.data || "");
      if (data === NAME_SELECTOR) return ok(encodeAbiString("USD Coin"));
      if (data === SYMBOL_SELECTOR) return ok(encodeAbiString("USDC"));
      if (data === DECIMALS_SELECTOR) return ok(`0x${(6).toString(16).padStart(64, "0")}`);
      if (data.startsWith(ALLOWANCE_SELECTOR)) {
        return ok(`0x${state.allowance.toString(16).padStart(64, "0")}`);
      }
      return ok("0x"); // simulation eth_call
    }
    throw new Error(`unexpected rpc method: ${body.method}`);
  };

  const service = new WdkEvmWalletService({
    network,
    transferMaxFeeWei: null,
    uniswapTradingApiBaseUrl: apiBase,
    uniswapApiKey: options.apiKey === undefined ? "test-key" : options.apiKey,
    uniswapViaGateway: Boolean(options.viaGateway),
    providerGatewayToken: options.gatewayToken,
    uniswapRouterVersion: "2.0",
    uniswapDefaultSlippageBps: 50,
    networkProfiles: {
      [network]: { chainId, providerUrl, nativeSymbol: "ETH" },
      // Configured but unsupported by the Uniswap provider — exercises the guard.
      sepolia: { chainId: 11155111, providerUrl, nativeSymbol: "ETH" },
    },
  });

  function restore() {
    WalletManagerEvm.prototype.getAccount = originals.getAccount;
    WalletManagerEvm.prototype.dispose = originals.dispose;
    globalThis.fetch = originals.fetch;
  }

  return { service, state, restore, chainId, network };
}

test("quote: native ETH -> USDC has no permit and CLASSIC routing", async () => {
  const h = createHarness();
  try {
    const result = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "1000000000000000000",
      network: "base",
    });
    assert.equal(result.protocol, "uniswap");
    assert.equal(result.routing, "CLASSIC");
    assert.equal(result.permitRequired, false);
    assert.equal(result.allowance.approvalRequired, false);
    assert.equal(result.outputAmountFormatted, "0.99");
    assert.ok(result.quoteFingerprint);
    // request body assertions
    const body = h.state.quoteBodies.at(-1);
    assert.equal(body.routingPreference, undefined); // live API rejects routingPreference:"CLASSIC"
    assert.deepEqual(body.protocols, ["V2", "V3", "V4"]);
    assert.equal(body.type, "EXACT_INPUT");
    assert.equal(body.tokenInChainId, 8453);
    assert.equal(body.slippageTolerance, 0.5);
    assert.equal(body.tokenIn, ZERO);
  } finally {
    h.restore();
  }
});

test("quote: USDC -> ETH requires permit and reports allowance", async () => {
  const h = createHarness({ initialAllowance: 0n });
  try {
    const result = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: BASE_USDC,
      tokenOut: "native",
      tokenInAmount: "1000000",
      slippageBps: 100,
      network: "base",
    });
    assert.equal(result.permitRequired, true);
    assert.equal(result.allowance.spender, PERMIT2);
    assert.equal(result.allowance.approvalRequired, true);
    assert.equal(result.slippageBps, 100);
  } finally {
    h.restore();
  }
});

test("quote: non-CLASSIC routing is rejected", async () => {
  const h = createHarness({ routing: "DUTCH_V2" });
  try {
    await assert.rejects(
      h.service.quoteUniswapSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "native",
        tokenOut: BASE_USDC,
        tokenInAmount: "1000000000000000000",
        network: "base",
      }),
      (err) => err.errorCode === "uniswap_unsupported_route"
    );
  } finally {
    h.restore();
  }
});

test("quote: missing API key is rejected", async () => {
  const h = createHarness({ apiKey: "" });
  try {
    await assert.rejects(
      h.service.quoteUniswapSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "native",
        tokenOut: BASE_USDC,
        tokenInAmount: "1000000000000000000",
        network: "base",
      }),
      (err) => err.errorCode === "uniswap_api_key_missing"
    );
  } finally {
    h.restore();
  }
});

test("quote: unsupported network is rejected", async () => {
  const h = createHarness();
  try {
    await assert.rejects(
      h.service.quoteUniswapSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "native",
        tokenOut: BASE_USDC,
        tokenInAmount: "1000000000000000000",
        network: "sepolia",
      }),
      /supported only on ethereum and base/
    );
  } finally {
    h.restore();
  }
});

test("send: native ETH -> USDC broadcasts router calldata without signing a permit", async () => {
  const h = createHarness({ swapValue: "0xde0b6b3a7640000" });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "1000000000000000000",
      network: "base",
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
    assert.equal(h.state.signCalls, 0);
    assert.equal(h.state.sendCalls.length, 1);
    assert.equal(h.state.sendCalls[0].to.toLowerCase(), BASE_ROUTER);
    assert.equal(result.simulation.ok, true);
    assert.ok(result.swapTransaction.dataHash);
  } finally {
    h.restore();
  }
});

test("send: USDC -> ETH signs the permit and submits signature to /swap", async () => {
  const h = createHarness({ initialAllowance: 10n ** 18n });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: BASE_USDC,
      tokenOut: "native",
      tokenInAmount: "1000000",
      network: "base",
    });
    assert.equal(h.state.signCalls, 1);
    const swapBody = h.state.swapBodies.at(-1);
    assert.ok(swapBody.signature, "signature must be attached for CLASSIC permit");
    assert.ok(swapBody.permitData, "permitData must be re-attached for CLASSIC");
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
  } finally {
    h.restore();
  }
});

test("send: gateway mode authenticates with bearer and omits the local api key", async () => {
  // No local UNISWAP_API_KEY; the daemon authenticates to the provider gateway
  // with the shared bearer and the gateway injects x-api-key upstream.
  const h = createHarness({
    viaGateway: true,
    gatewayToken: "gw-token",
    apiKey: "",
    swapValue: "0xde0b6b3a7640000",
  });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "1000000000000000000",
      network: "base",
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
    const headers = h.state.lastHeaders;
    assert.equal(headers.Authorization, "Bearer gw-token");
    assert.equal(headers["x-api-key"], undefined);
    assert.equal(headers["x-universal-router-version"], "2.0");
  } finally {
    h.restore();
  }
});

test("send: direct mode sends x-api-key and no bearer", async () => {
  const h = createHarness({ swapValue: "0xde0b6b3a7640000" });
  try {
    await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "1000000000000000000",
      network: "base",
    });
    const headers = h.state.lastHeaders;
    assert.equal(headers["x-api-key"], "test-key");
    assert.equal(headers.Authorization, undefined);
  } finally {
    h.restore();
  }
});

test("send: tolerates refreshed quote drift within the slippage window", async () => {
  // Preview quotes 990000; execute re-quotes a lower-but-still-acceptable
  // 988000 (>= bound minimum 985000). The quote fingerprint must stay stable
  // across the re-quote so the swap proceeds, matching the velora swap contract.
  const h = createHarness({
    quoteOutputAmounts: ["990000", "988000"],
    minimumAmount: "985000",
    swapValue: "0xde0b6b3a7640000",
  });
  try {
    const preview = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "1000000000000000000",
      network: "base",
    });
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "1000000000000000000",
      network: "base",
      expectedQuoteFingerprint: preview.quoteFingerprint,
      minimumTokenOutAmount: preview.minimumOutputAmountRaw,
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
  } finally {
    h.restore();
  }
});

test("send: rejects refreshed quote drift beyond the slippage window", async () => {
  // Execute re-quotes 980000, below the bound minimum 985000 -> rejected via the
  // tolerant minimum-output check (not a spurious fingerprint mismatch).
  const h = createHarness({
    quoteOutputAmounts: ["990000", "980000"],
    minimumAmount: "985000",
    swapValue: "0xde0b6b3a7640000",
  });
  try {
    const preview = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "1000000000000000000",
      network: "base",
    });
    await assert.rejects(
      h.service.sendUniswapSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "native",
        tokenOut: BASE_USDC,
        tokenInAmount: "1000000000000000000",
        network: "base",
        expectedQuoteFingerprint: preview.quoteFingerprint,
        minimumTokenOutAmount: preview.minimumOutputAmountRaw,
      }),
      (err) => err.errorCode === "swap_quote_changed"
    );
  } finally {
    h.restore();
  }
});

test("send: /swap calldata to an unexpected router is rejected", async () => {
  const h = createHarness({ swapRouter: "0x1234567890123456789012345678901234567890" });
  try {
    await assert.rejects(
      h.service.sendUniswapSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "native",
        tokenOut: BASE_USDC,
        tokenInAmount: "1000000000000000000",
        network: "base",
      }),
      (err) => err.errorCode === "uniswap_unexpected_router"
    );
  } finally {
    h.restore();
  }
});
