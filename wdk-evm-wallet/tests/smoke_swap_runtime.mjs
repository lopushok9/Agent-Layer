import assert from "node:assert/strict";
import test from "node:test";

import WDK from "@tetherto/wdk";
import VeloraProtocolEvm from "@tetherto/wdk-protocol-swap-velora-evm";
import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

import { WdkEvmWalletService } from "../src/wdk_evm_wallet.js";

const VALID_MNEMONIC =
  "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const DEFAULT_TOKEN_IN = "0x2222222222222222222222222222222222222222";
const DEFAULT_TOKEN_OUT = "0x3333333333333333333333333333333333333333";
const DEFAULT_ROUTER = "0x4444444444444444444444444444444444444444";
const DEFAULT_SPENDER = "0x5555555555555555555555555555555555555555";
const DEFAULT_ADDRESS = "0x1111111111111111111111111111111111111111";
const USDT_MAINNET = "0xdac17f958d2ee523a2206206994597c13d831ec7";
const NAME_SELECTOR = "0x06fdde03";
const SYMBOL_SELECTOR = "0x95d89b41";
const DECIMALS_SELECTOR = "0x313ce567";

function encodeAbiString(value) {
  const data = Buffer.from(value, "utf8").toString("hex");
  const offset = "20".padStart(64, "0");
  const length = (data.length / 2).toString(16).padStart(64, "0");
  return `0x${offset}${length}${data.padEnd(Math.ceil(data.length / 64) * 64, "0")}`;
}

function createRuntimeHarness(options = {}) {
  const state = {
    allowance: BigInt(options.initialAllowance ?? 0n),
    approveCalls: [],
    sendCalls: [],
    quoteCalls: [],
    metadataCalls: [],
    routeCalls: 0,
    buildTxCalls: 0,
    receiptPolls: 0,
    swapReceiptStatus: options.swapReceiptStatus ?? "0x1",
  };
  const config = {
    network: options.network ?? "ethereum",
    chainId: options.chainId ?? 1,
    providerUrl: options.providerUrl ?? "http://fake-rpc.local",
    nativeSymbol: "ETH",
    tokenIn: options.tokenIn ?? DEFAULT_TOKEN_IN,
    tokenOut: options.tokenOut ?? DEFAULT_TOKEN_OUT,
    spender: options.spender ?? DEFAULT_SPENDER,
    router: options.router ?? DEFAULT_ROUTER,
    amountIn: String(options.amountIn ?? "1000000"),
    baseDestAmount: String(options.destAmount ?? "995000"),
    tokenName: options.tokenName ?? "USD Coin",
    tokenSymbol: options.tokenSymbol ?? "USDC",
    tokenDecimals: options.tokenDecimals ?? 6,
    approvalFee: BigInt(options.approvalFee ?? 2n),
    swapFee: BigInt(options.swapFee ?? 3n),
    failSimulationAfterApproval: Boolean(options.failSimulationAfterApproval),
    failSwapFeeQuote: Boolean(options.failSwapFeeQuote),
    failSwapSend: Boolean(options.failSwapSend),
    failCleanupApprove: Boolean(options.failCleanupApprove),
    quoteDestAmounts: Array.isArray(options.quoteDestAmounts)
      ? options.quoteDestAmounts.map((value) => String(value))
      : null,
    receiptReturnsNull: Boolean(options.receiptReturnsNull),
  };

  const originals = {
    getAccount: WalletManagerEvm.prototype.getAccount,
    disposeWallet: WalletManagerEvm.prototype.dispose,
    protocolDispose: VeloraProtocolEvm.prototype.dispose,
    getVeloraSdk: VeloraProtocolEvm.prototype._getVeloraSdk,
    fetch: globalThis.fetch,
  };

  const fakeAccount = {
    _config: { provider: config.providerUrl },
    async getAddress() {
      return DEFAULT_ADDRESS;
    },
    async getAllowance() {
      return state.allowance;
    },
    async quoteSendTransaction(tx) {
      const isApprove = String(tx?.data || "").startsWith("0x095ea7b3");
      state.quoteCalls.push({
        kind: isApprove ? "approve" : "swap",
        to: tx?.to ? String(tx.to) : null,
      });
      if (config.failSwapFeeQuote && !isApprove) {
        throw Object.assign(new Error("execution reverted: preview gas unavailable"), {
          code: "CALL_EXCEPTION",
        });
      }
      return { fee: isApprove ? config.approvalFee : config.swapFee };
    },
    async approve({ amount }) {
      if (config.failCleanupApprove && state.approveCalls.length >= 1) {
        throw Object.assign(new Error("cleanup approve failed"), {
          errorCode: "swap_cleanup_failed",
        });
      }
      state.allowance = BigInt(amount);
      state.approveCalls.push(String(amount));
      return {
        hash: `0x${String(state.approveCalls.length).padStart(64, "a")}`,
        fee: config.approvalFee,
      };
    },
    async sendTransaction(tx) {
      state.sendCalls.push({
        to: String(tx?.to || ""),
        value: String(tx?.value || "0"),
      });
      if (config.failSwapSend) {
        throw new Error("swap send failed");
      }
      return {
        hash: `0x${"d".repeat(64)}`,
        fee: config.swapFee,
      };
    },
  };

  WalletManagerEvm.prototype.getAccount = async function getAccount() {
    return fakeAccount;
  };
  WalletManagerEvm.prototype.dispose = function dispose() {};
  VeloraProtocolEvm.prototype.dispose = function dispose() {};
  VeloraProtocolEvm.prototype._getVeloraSdk = async function getVeloraSdk() {
    return {
      swap: {
        async getRate() {
          const index = state.routeCalls;
          state.routeCalls += 1;
          const destAmount =
            config.quoteDestAmounts && config.quoteDestAmounts[index] !== undefined
              ? config.quoteDestAmounts[index]
              : config.baseDestAmount;
          return {
            srcToken: config.tokenIn,
            destToken: config.tokenOut,
            srcAmount: config.amountIn,
            destAmount,
          };
        },
        async buildTx() {
          state.buildTxCalls += 1;
          return {
            to: config.router,
            value: "0",
            data: "0xdeadbeef",
          };
        },
        async getSpender() {
          return config.spender;
        },
        async getContracts() {
          return { AugustusSwapper: config.router };
        },
      },
    };
  };

  globalThis.fetch = async (_url, init) => {
    const body = JSON.parse(String(init.body || "{}"));
    const method = body.method;
    const ok = (result) => ({
      ok: true,
      json: async () => ({ jsonrpc: "2.0", id: 1, result }),
    });
    const rpcError = (message, code = 3) => ({
      ok: true,
      json: async () => ({
        jsonrpc: "2.0",
        id: 1,
        error: { message, code },
      }),
    });

    if (method === "eth_call") {
      const data = String(body.params?.[0]?.data || "");
      if (data === NAME_SELECTOR) {
        state.metadataCalls.push("name");
        return ok(encodeAbiString(config.tokenName));
      }
      if (data === SYMBOL_SELECTOR) {
        state.metadataCalls.push("symbol");
        return ok(encodeAbiString(config.tokenSymbol));
      }
      if (data === DECIMALS_SELECTOR) {
        state.metadataCalls.push("decimals");
        return ok(`0x${config.tokenDecimals.toString(16).padStart(64, "0")}`);
      }
      if (config.failSimulationAfterApproval && state.allowance >= BigInt(config.amountIn)) {
        return rpcError("execution reverted: simulated swap failure");
      }
      return ok("0x");
    }

    if (method === "eth_getTransactionReceipt") {
      state.receiptPolls += 1;
      if (config.receiptReturnsNull) {
        return ok(null);
      }
      return ok({ status: config.swapReceiptStatus });
    }

    throw new Error(`unexpected rpc method: ${method}`);
  };

  const service = new WdkEvmWalletService({
    network: config.network,
    transferMaxFeeWei: null,
    networkProfiles: {
      [config.network]: {
        chainId: config.chainId,
        providerUrl: config.providerUrl,
        nativeSymbol: config.nativeSymbol,
      },
    },
  });

  function restore() {
    WalletManagerEvm.prototype.getAccount = originals.getAccount;
    WalletManagerEvm.prototype.dispose = originals.disposeWallet;
    VeloraProtocolEvm.prototype.dispose = originals.protocolDispose;
    VeloraProtocolEvm.prototype._getVeloraSdk = originals.getVeloraSdk;
    globalThis.fetch = originals.fetch;
  }

  return { config, state, service, restore };
}

async function withHarness(options, run) {
  const harness = createRuntimeHarness(options);
  try {
    return await run(harness);
  } finally {
    harness.restore();
  }
}

test("quoteSwap returns approval and fingerprint details", async () => {
  await withHarness({}, async ({ service, state, config }) => {
    const quote = await service.quoteSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: config.tokenIn,
      tokenOut: config.tokenOut,
      tokenInAmount: config.amountIn,
      network: config.network,
    });
    assert.equal(quote.allowance.approvalRequired, true);
    assert.equal(quote.allowance.spender, config.spender);
    assert.equal(quote.simulation.skipped, true);
    assert.match(quote.quoteFingerprint, /^[0-9a-f]{64}$/);
    assert.equal(state.metadataCalls.length, 6);
  });
});

test("swap succeeds without approval when allowance is already sufficient", async () => {
  await withHarness({ initialAllowance: 1000000n }, async ({ service, state, config }) => {
    const result = await service.swap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: config.tokenIn,
      tokenOut: config.tokenOut,
      tokenInAmount: config.amountIn,
      network: config.network,
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
    assert.equal(state.approveCalls.length, 0);
    assert.equal(state.sendCalls.length, 1);
    assert.equal(result.simulation.ok, true);
  });
});

test("quoteSwap degrades gracefully when swap gas estimate is unavailable before approval", async () => {
  await withHarness(
    {
      failSwapFeeQuote: true,
    },
    async ({ service, state, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(quote.allowance.approvalRequired, true);
      assert.equal(quote.estimatedSwapFeeWei, null);
      assert.equal(quote.estimatedFeeWei, null);
      assert.equal(quote.feeEstimateAvailable, false);
      assert.match(String(quote.feeEstimateError?.message || ""), /preview gas unavailable/);
      assert.equal(state.sendCalls.length, 0);
    }
  );
});

test("swap failure after approval restores original allowance", async () => {
  await withHarness({ failSwapSend: true }, async ({ service, state, config }) => {
    await assert.rejects(
      () =>
        service.swap({
          seedPhrase: VALID_MNEMONIC,
          tokenIn: config.tokenIn,
          tokenOut: config.tokenOut,
          tokenInAmount: config.amountIn,
          network: config.network,
        }),
      /swap send failed/
    );
    assert.equal(state.allowance, 0n);
    assert.deepEqual(state.approveCalls, [config.amountIn, "0"]);
  });
});

test("quote mismatch after approval triggers restore and blocks execute", async () => {
  await withHarness(
    {
      quoteDestAmounts: ["995000", "995000", "990000"],
    },
    async ({ service, state, config }) => {
      const preview = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      await assert.rejects(
        () =>
          service.swap({
            seedPhrase: VALID_MNEMONIC,
            tokenIn: config.tokenIn,
            tokenOut: config.tokenOut,
            tokenInAmount: config.amountIn,
            network: config.network,
            expectedQuoteFingerprint: preview.quoteFingerprint,
          }),
        /Swap quote changed since preview/
      );
      assert.equal(state.allowance, 0n);
      assert.deepEqual(state.approveCalls, [config.amountIn, "0"]);
      assert.equal(state.sendCalls.length, 0);
    }
  );
});

test("simulation failure after approval restores original allowance", async () => {
  await withHarness(
    {
      failSimulationAfterApproval: true,
    },
    async ({ service, state, config }) => {
      await assert.rejects(
        () =>
          service.swap({
            seedPhrase: VALID_MNEMONIC,
            tokenIn: config.tokenIn,
            tokenOut: config.tokenOut,
            tokenInAmount: config.amountIn,
            network: config.network,
          }),
        /Swap simulation failed/
      );
      assert.equal(state.allowance, 0n);
      assert.deepEqual(state.approveCalls, [config.amountIn, "0"]);
      assert.equal(state.sendCalls.length, 0);
    }
  );
});

test("cleanup failure is surfaced as swap_cleanup_failed", async () => {
  await withHarness(
    {
      failSwapSend: true,
      failCleanupApprove: true,
    },
    async ({ service, state, config }) => {
      await assert.rejects(
        () =>
          service.swap({
            seedPhrase: VALID_MNEMONIC,
            tokenIn: config.tokenIn,
            tokenOut: config.tokenOut,
            tokenInAmount: config.amountIn,
            network: config.network,
          }),
        (error) =>
          error?.errorCode === "swap_cleanup_failed" &&
          error?.errorDetails?.cleanup?.attempted === true &&
          state.allowance === BigInt(config.amountIn)
      );
    }
  );
});

test("USDT reset-to-zero approval and restore sequence follows Ethereum rules", async () => {
  await withHarness(
    {
      tokenIn: USDT_MAINNET,
      initialAllowance: 5n,
      amountIn: "10",
      failSwapSend: true,
    },
    async ({ service, state, config }) => {
      const preview = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.deepEqual(
        preview.allowance.approvalSequence.map((item) => item.type),
        ["reset_allowance", "approve"]
      );
      await assert.rejects(
        () =>
          service.swap({
            seedPhrase: VALID_MNEMONIC,
            tokenIn: config.tokenIn,
            tokenOut: config.tokenOut,
            tokenInAmount: config.amountIn,
            network: config.network,
          }),
        /swap send failed/
      );
      assert.equal(state.allowance, 5n);
      assert.deepEqual(state.approveCalls, ["0", "10", "0", "5"]);
    }
  );
});

test("repeated failed swaps do not leak allowance state", async () => {
  for (let index = 0; index < 25; index += 1) {
    await withHarness({ failSwapSend: true }, async ({ service, state, config }) => {
      await assert.rejects(
        () =>
          service.swap({
            seedPhrase: VALID_MNEMONIC,
            tokenIn: config.tokenIn,
            tokenOut: config.tokenOut,
            tokenInAmount: config.amountIn,
            network: config.network,
          }),
        /swap send failed/
      );
      assert.equal(state.allowance, 0n);
      assert.deepEqual(state.approveCalls, [config.amountIn, "0"]);
    });
  }
});
