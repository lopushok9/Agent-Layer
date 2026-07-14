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
// Universal Router v2.0 on robinhood (must match UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK).
const ROBINHOOD_ROUTER = "0x8876789976decbfcbbbe364623c63652db8c0904";
const ROBINHOOD_SWAP_ROUTER02 = "0xcaf681a66d020601342297493863e78c959e5cb2";
const ROBINHOOD_WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73";
// Placeholder ERC-20 test double on robinhood — the mocked RPC below returns
// canned metadata for any token address, so this does not need to be a real
// deployed contract.
const ROBINHOOD_TOKEN = "0x3333333333333333333333333333333333333333";

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

function encodeAbiUintWords(values) {
  return `0x${values.map((value) => BigInt(value).toString(16).padStart(64, "0")).join("")}`;
}

// Mirrors the live Trading API shape: Permit2 AllowanceTransfer (PermitSingle),
// domain has no `version`, and `types` does not include an EIP712Domain entry.
function permitDataFixture(chainId, token, spender) {
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
      details: { token, amount: "1000000", expiration: "9999999999", nonce: "0" },
      spender,
      sigDeadline: "9999999999",
    },
  };
}

function createHarness(options = {}) {
  const chainId = options.chainId ?? 8453;
  const network = options.network ?? "base";
  const router = (options.router ?? BASE_ROUTER).toLowerCase();
  const erc20Token = options.erc20Token ?? BASE_USDC;
  const providerUrl = "http://fake-rpc.local";
  const apiBase = "https://uniswap-test.local/v1";
  const state = {
    allowance: BigInt(options.initialAllowance ?? 0n),
    quoteBodies: [],
    swapBodies: [],
    orderBodies: [],
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
      state.sendCalls.push({ to: String(tx.to), value: String(tx.value), data: String(tx.data || "") });
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
        if (
          (options.noQuoteAvailable || options.noQuoteWhenUniswapXRequested) &&
          Array.isArray(body.protocols) &&
          (options.noQuoteAvailable || body.protocols.some((protocol) => String(protocol).startsWith("UNISWAPX_")))
        ) {
          return { ok: false, status: 400, json: async () => ({ message: "No quotes available" }) };
        }
        const routing = options.routing || "CLASSIC";
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
          routing,
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
          permitData: erc20In ? permitDataFixture(chainId, erc20Token, router) : null,
        });
      }
      if (requestUrl.endsWith("/swap")) {
        state.swapBodies.push(body);
        return ok({
          swap: {
            to: options.swapRouter || router,
            data: options.swapData || "0xabcdef",
            value: options.swapValue || "0x0",
          },
        });
      }
      if (requestUrl.endsWith("/order")) {
        state.orderBodies.push(body);
        return ok({
          orderId: options.orderId || `0x${"e".repeat(64)}`,
          orderStatus: "open",
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
      if (options.directV3Quote !== undefined) {
        return ok(encodeAbiUintWords([options.directV3Quote, 0, 0, 95375]));
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
    assert.deepEqual(body.protocols, ["V2", "V3", "V4", "UNISWAPX_V3"]);
    assert.equal(body.type, "EXACT_INPUT");
    assert.equal(body.tokenInChainId, 8453);
    assert.equal(body.slippageTolerance, 0.5);
    assert.equal(body.tokenIn, ZERO);
    assert.equal(h.state.lastHeaders["x-erc20eth-enabled"], "true");
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

test("quote: UniswapX routing is returned as an executable order plan", async () => {
  const h = createHarness({ routing: "DUTCH_V3" });
  try {
    const result = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: BASE_USDC,
      tokenOut: "native",
      tokenInAmount: "1000000",
      network: "base",
    });
    assert.equal(result.routing, "DUTCH_V3");
    assert.equal(result.router, null);
    assert.equal(result.permitRequired, true);
  } finally {
    h.restore();
  }
});

test("quote: falls back to AMM-only when a sub-minimum UniswapX request has no quote", async () => {
  const h = createHarness({ noQuoteWhenUniswapXRequested: true });
  try {
    const result = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: BASE_USDC,
      tokenInAmount: "100000000000000",
      network: "base",
    });
    assert.equal(result.routing, "CLASSIC");
    assert.equal(h.state.quoteBodies.length, 2);
    assert.deepEqual(h.state.quoteBodies[0].protocols, ["V2", "V3", "V4", "UNISWAPX_V3"]);
    assert.deepEqual(h.state.quoteBodies[1].protocols, ["V2", "V3", "V4"]);
  } finally {
    h.restore();
  }
});

test("send: LIMIT_ORDER follows the signed UniswapX /order path", async () => {
  const h = createHarness({ routing: "LIMIT_ORDER", initialAllowance: 10n ** 18n });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: BASE_USDC,
      tokenOut: "native",
      tokenInAmount: "1000000",
      network: "base",
    });
    assert.equal(result.executionKind, "uniswapx");
    assert.equal(result.result.orderStatus, "open");
    assert.equal(h.state.orderBodies.at(-1).routing, "LIMIT_ORDER");
    assert.equal(h.state.sendCalls.length, 0);
  } finally {
    h.restore();
  }
});

test("quote: non-executable bridge routing is rejected before signing", async () => {
  const h = createHarness({ routing: "BRIDGE" });
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
    assert.equal(h.state.signCalls, 0);
    assert.equal(h.state.sendCalls.length, 0);
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
      /supported only on ethereum, base, and robinhood/
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

test("send: UniswapX submits a signed order without broadcasting local calldata", async () => {
  const h = createHarness({ routing: "DUTCH_V3", initialAllowance: 10n ** 18n });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: BASE_USDC,
      tokenOut: "native",
      tokenInAmount: "1000000",
      network: "base",
    });
    assert.equal(result.routing, "DUTCH_V3");
    assert.equal(result.result.orderId, `0x${"e".repeat(64)}`);
    assert.equal(result.result.orderStatus, "open");
    assert.equal(h.state.signCalls, 1);
    assert.equal(h.state.sendCalls.length, 0);
    assert.equal(h.state.swapBodies.length, 0);
    const orderBody = h.state.orderBodies.at(-1);
    assert.equal(orderBody.signature, `0x${"b".repeat(130)}`);
    assert.equal(orderBody.routing, "DUTCH_V3");
    assert.equal(orderBody.quote.output.amount, "990000");
    assert.equal(result.simulation.skipped, true);
    assert.equal(result.simulation.reason, "uniswapx-order");
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
    assert.equal(headers["x-agentlayer-chain-id"], "8453");
    assert.equal(headers["x-agentlayer-uniswap-router-version"], "2.0");
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

test("quote: native ETH -> ERC-20 on robinhood uses chain id 4663 and CLASSIC routing", async () => {
  const h = createHarness({
    network: "robinhood",
    chainId: 4663,
    router: ROBINHOOD_ROUTER,
    erc20Token: ROBINHOOD_TOKEN,
  });
  try {
    const result = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: ROBINHOOD_TOKEN,
      tokenInAmount: "1000000000000000000",
      network: "robinhood",
    });
    assert.equal(result.protocol, "uniswap");
    assert.equal(result.routing, "CLASSIC");
    assert.equal(result.outputAmountFormatted, "0.99");
    const body = h.state.quoteBodies.at(-1);
    assert.equal(body.tokenInChainId, 4663);
    assert.equal(body.tokenOutChainId, 4663);
    assert.deepEqual(body.protocols, ["V3", "UNISWAPX_V3"]);
  } finally {
    h.restore();
  }
});

test("quote: robinhood falls back to a locally quoted V3 direct route when Trading API has no quote", async () => {
  const h = createHarness({
    network: "robinhood",
    chainId: 4663,
    router: ROBINHOOD_ROUTER,
    erc20Token: ROBINHOOD_TOKEN,
    noQuoteAvailable: true,
    directV3Quote: 123456,
  });
  try {
    const result = await h.service.quoteUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: ROBINHOOD_TOKEN,
      tokenInAmount: "100000000000000",
      network: "robinhood",
    });
    assert.equal(result.source, "uniswap-v3-direct-fallback");
    assert.equal(result.executionKind, "v3-direct");
    assert.equal(result.router, ROBINHOOD_SWAP_ROUTER02);
    assert.equal(result.outputAmount, "123456");
    assert.equal(result.minimumOutputAmountRaw, "122839");
    assert.equal(result.allowance.approvalRequired, false);
    assert.equal(h.state.quoteBodies.length, 2);
    assert.deepEqual(h.state.quoteBodies[0].protocols, ["V3", "UNISWAPX_V3"]);
    assert.deepEqual(h.state.quoteBodies[1].protocols, ["V3"]);
  } finally {
    h.restore();
  }
});

test("send: native ETH -> ERC-20 on robinhood broadcasts to the robinhood Universal Router", async () => {
  const h = createHarness({
    network: "robinhood",
    chainId: 4663,
    router: ROBINHOOD_ROUTER,
    erc20Token: ROBINHOOD_TOKEN,
    swapValue: "0xde0b6b3a7640000",
  });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: ROBINHOOD_TOKEN,
      tokenInAmount: "1000000000000000000",
      network: "robinhood",
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
    assert.equal(h.state.sendCalls.length, 1);
    assert.equal(h.state.sendCalls[0].to.toLowerCase(), ROBINHOOD_ROUTER.toLowerCase());
  } finally {
    h.restore();
  }
});

test("send: native ETH -> WETH on robinhood is a local canonical direct-wrap call", async () => {
  const amount = "1000000000000000000";
  const h = createHarness({
    network: "robinhood",
    chainId: 4663,
    router: ROBINHOOD_ROUTER,
    erc20Token: ROBINHOOD_WETH,
    // A local wrap must not require an API key or consume a quote/swap response.
    apiKey: "",
  });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: "native",
      tokenOut: ROBINHOOD_WETH,
      tokenInAmount: amount,
      network: "robinhood",
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
    assert.equal(result.executionKind, "wrap");
    assert.equal(result.source, "canonical-wrapped-native");
    assert.equal(h.state.sendCalls.length, 1);
    assert.equal(h.state.sendCalls[0].to.toLowerCase(), ROBINHOOD_WETH);
    assert.equal(h.state.sendCalls[0].value, amount);
    assert.equal(h.state.sendCalls[0].data, "0xd0e30db0");
    assert.equal(h.state.quoteBodies.length, 0);
    assert.equal(h.state.swapBodies.length, 0);
  } finally {
    h.restore();
  }
});

test("send: WETH -> ETH on robinhood is a local canonical unwrap call", async () => {
  const amount = "1000000000000000000";
  const h = createHarness({
    network: "robinhood",
    chainId: 4663,
    router: ROBINHOOD_ROUTER,
    erc20Token: ROBINHOOD_WETH,
    apiKey: "",
  });
  try {
    const result = await h.service.sendUniswapSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: ROBINHOOD_WETH,
      tokenOut: "native",
      tokenInAmount: amount,
      network: "robinhood",
    });
    assert.equal(result.executionKind, "unwrap");
    assert.equal(h.state.signCalls, 0);
    assert.equal(h.state.sendCalls.length, 1);
    assert.equal(h.state.sendCalls[0].to.toLowerCase(), ROBINHOOD_WETH);
    assert.equal(h.state.sendCalls[0].value, "0");
    assert.equal(h.state.sendCalls[0].data, `0x2e1a7d4d${BigInt(amount).toString(16).padStart(64, "0")}`);
    assert.equal(h.state.quoteBodies.length, 0);
    assert.equal(h.state.swapBodies.length, 0);
  } finally {
    h.restore();
  }
});

test("send: a base-network router address is rejected when the active network is robinhood", async () => {
  // Cross-network regression guard: the Trading API response's `to` must match
  // the *active* network's allow-listed router, not any known router.
  const h = createHarness({
    network: "robinhood",
    chainId: 4663,
    router: ROBINHOOD_ROUTER,
    erc20Token: ROBINHOOD_TOKEN,
    swapRouter: BASE_ROUTER,
  });
  try {
    await assert.rejects(
      h.service.sendUniswapSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "native",
        tokenOut: ROBINHOOD_TOKEN,
        tokenInAmount: "1000000000000000000",
        network: "robinhood",
      }),
      (err) => err.errorCode === "uniswap_unexpected_router"
    );
  } finally {
    h.restore();
  }
});
