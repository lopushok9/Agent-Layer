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
const DEFAULT_TOKEN_OUT_MIXED_CASE = "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48";
const DEFAULT_TOKEN_OUT_MIXED_CASE_LOWER = DEFAULT_TOKEN_OUT_MIXED_CASE.toLowerCase();
const BASE_USDC_CHECKSUMMED = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const BASE_USDC_LOWER = BASE_USDC_CHECKSUMMED.toLowerCase();
const DEFAULT_ROUTER = "0x4444444444444444444444444444444444444444";
const DEFAULT_SPENDER = "0x5555555555555555555555555555555555555555";
const DEFAULT_ADDRESS = "0x1111111111111111111111111111111111111111";
const USDT_MAINNET = "0xdac17f958d2ee523a2206206994597c13d831ec7";
const NATIVE_ETH = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
const NAME_SELECTOR = "0x06fdde03";
const SYMBOL_SELECTOR = "0x95d89b41";
const DECIMALS_SELECTOR = "0x313ce567";
const BALANCE_OF_SELECTOR = "0x70a08231";

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
    allowanceReadCalls: 0,
    directBalanceReadCalls: 0,
    tokenTransferQuoteCalls: 0,
    tokenTransferSendCalls: 0,
    lifiQuoteUrls: [],
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
    routeGasCost: String(options.routeGasCost ?? "995000"),
    tokenName: options.tokenName ?? "USD Coin",
    tokenSymbol: options.tokenSymbol ?? "USDC",
    tokenDecimals: options.tokenDecimals ?? 6,
    approvalFee: BigInt(options.approvalFee ?? 2n),
    swapFee: BigInt(options.swapFee ?? 3n),
    failSimulationAfterApproval: Boolean(options.failSimulationAfterApproval),
    failSwapFeeQuote: Boolean(options.failSwapFeeQuote),
    failSwapFeeQuoteInsufficientFunds: Boolean(options.failSwapFeeQuoteInsufficientFunds),
    failRpcEstimateGas: Boolean(options.failRpcEstimateGas),
    failAllowanceRead: Boolean(options.failAllowanceRead),
    disallowAllowanceRead: Boolean(options.disallowAllowanceRead),
    failDecimalsMetadata: Boolean(options.failDecimalsMetadata),
    failSwapSend: Boolean(options.failSwapSend),
    failCleanupApprove: Boolean(options.failCleanupApprove),
    quoteDestAmounts: Array.isArray(options.quoteDestAmounts)
      ? options.quoteDestAmounts.map((value) => String(value))
      : null,
    receiptReturnsNull: Boolean(options.receiptReturnsNull),
    swapTxValue: String(options.swapTxValue ?? "0"),
    failOnMixedCaseDestToken: Boolean(options.failOnMixedCaseDestToken),
    failOnMixedCaseLifiToken: Boolean(options.failOnMixedCaseLifiToken),
    tokenBalance: BigInt(options.tokenBalance ?? 5529342504n),
    failTokenBalanceRead: Boolean(options.failTokenBalanceRead),
    emptyBalanceResponse: Boolean(options.emptyBalanceResponse),
    failTokenMetadata: Boolean(options.failTokenMetadata),
    failTokenTransferEstimate: Boolean(options.failTokenTransferEstimate),
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
      state.allowanceReadCalls += 1;
      if (config.disallowAllowanceRead) {
        throw new Error("native token allowance should not be queried");
      }
      if (config.failAllowanceRead) {
        throw Object.assign(
          new Error('could not decode result data (value="0x", method="allowance(address,address)")'),
          { code: "BAD_DATA" }
        );
      }
      return state.allowance;
    },
    async getTokenBalance() {
      if (config.failTokenBalanceRead) {
        throw Object.assign(new Error("missing revert data"), {
          code: "CALL_EXCEPTION",
        });
      }
      return config.tokenBalance;
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
      if (config.failSwapFeeQuoteInsufficientFunds && !isApprove) {
        throw Object.assign(
          new Error(
            "insufficient funds for gas * price + value: have 1000000000000000 want 2440000000000000"
          ),
          {
            code: "INSUFFICIENT_FUNDS",
          }
        );
      }
      return { fee: isApprove ? config.approvalFee : config.swapFee };
    },
    async quoteTransfer() {
      state.tokenTransferQuoteCalls += 1;
      if (config.failTokenTransferEstimate) {
        throw Object.assign(new Error("missing revert data"), {
          code: "CALL_EXCEPTION",
        });
      }
      return { fee: config.swapFee };
    },
    async transfer() {
      state.tokenTransferSendCalls += 1;
      if (config.failTokenTransferEstimate) {
        throw Object.assign(new Error("missing revert data"), {
          code: "CALL_EXCEPTION",
        });
      }
      return {
        hash: `0x${"e".repeat(64)}`,
        fee: config.swapFee,
      };
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
        gasLimit: BigInt(tx?.gasLimit || 0).toString(),
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
          if (
            config.failOnMixedCaseDestToken &&
            /[A-F]/.test(String(arguments[0]?.destToken || "").slice(2))
          ) {
            throw new Error('Validation failed: "destToken" does not match any of the allowed types');
          }
          const index = state.routeCalls;
          state.routeCalls += 1;
          const destAmount =
            config.quoteDestAmounts && config.quoteDestAmounts[index] !== undefined
              ? config.quoteDestAmounts[index]
              : config.baseDestAmount;
          return {
            srcToken: config.tokenIn,
            srcDecimals: config.tokenDecimals,
            destToken: config.tokenOut,
            destDecimals: config.tokenDecimals,
            srcAmount: config.amountIn,
            destAmount,
            gasCost: config.routeGasCost,
          };
        },
        async buildTx() {
          state.buildTxCalls += 1;
          return {
            to: config.router,
            value: config.swapTxValue,
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

  globalThis.fetch = async (_url, init = {}) => {
    const requestUrl = String(_url || "");
    if (requestUrl.includes("/quote?")) {
      state.lifiQuoteUrls.push(requestUrl);
      const quoteUrl = new URL(requestUrl);
      const fromToken = quoteUrl.searchParams.get("fromToken") || "";
      const toToken = quoteUrl.searchParams.get("toToken") || "";
      if (
        config.failOnMixedCaseLifiToken &&
        [fromToken, toToken].some((token) => /^0x[a-fA-F0-9]{40}$/.test(token) && /[A-F]/.test(token.slice(2)))
      ) {
        return {
          ok: false,
          status: 400,
          json: async () => ({
            message: 'Validation failed: "fromToken/toToken" does not match any of the allowed types',
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: "lifi-quote-1",
          type: "lifi",
          tool: "across",
          action: {
            fromToken: {
              address: fromToken,
              name: "USD Coin",
              symbol: "USDC",
              decimals: config.tokenDecimals,
              tags: ["stablecoin"],
            },
            toToken: {
              address: toToken,
              name: "USD Coin",
              symbol: "USDC",
              decimals: config.tokenDecimals,
              tags: ["stablecoin"],
            },
            slippage: Number(quoteUrl.searchParams.get("slippage") || "0.005"),
          },
          estimate: {
            fromAmount: quoteUrl.searchParams.get("fromAmount") || config.amountIn,
            toAmount: config.baseDestAmount,
            toAmountMin: config.baseDestAmount,
            approvalAddress: config.spender,
          },
          transactionRequest: {
            to: config.router,
            data: "0xdeadbeef",
            value: "0x0",
            gasLimit: "0x5208",
          },
        }),
      };
    }
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
        if (config.failTokenMetadata) {
          return ok("0x");
        }
        return ok(encodeAbiString(config.tokenName));
      }
      if (data === SYMBOL_SELECTOR) {
        state.metadataCalls.push("symbol");
        if (config.failTokenMetadata) {
          return ok("0x");
        }
        return ok(encodeAbiString(config.tokenSymbol));
      }
      if (data === DECIMALS_SELECTOR) {
        state.metadataCalls.push("decimals");
        if (config.failDecimalsMetadata || config.failTokenMetadata) {
          return ok("0x");
        }
        return ok(`0x${config.tokenDecimals.toString(16).padStart(64, "0")}`);
      }
      if (data.startsWith(BALANCE_OF_SELECTOR)) {
        state.directBalanceReadCalls += 1;
        if (config.emptyBalanceResponse) {
          return ok("0x");
        }
        return ok(`0x${config.tokenBalance.toString(16).padStart(64, "0")}`);
      }
      if (config.failSimulationAfterApproval && state.allowance >= BigInt(config.amountIn)) {
        return rpcError("execution reverted: simulated swap failure");
      }
      return ok("0x");
    }

    if (method === "eth_getCode") {
      return ok(config.tokenIn ? "0x1234" : "0x");
    }

    if (method === "eth_getBalance") {
      return ok("0x0");
    }

    if (method === "eth_estimateGas") {
      if (config.failRpcEstimateGas) {
        return rpcError("request timeout", "TIMEOUT");
      }
      return ok("0x5208");
    }

    if (method === "eth_gasPrice") {
      return ok("0x1");
    }

    if (method === "eth_maxPriorityFeePerGas") {
      return ok("0x1");
    }

    if (method === "eth_feeHistory") {
      return ok({ baseFeePerGas: ["0x1", "0x1"], gasUsedRatio: [0.5], oldestBlock: "0x1" });
    }

    if (method === "eth_chainId") {
      return ok(`0x${config.chainId.toString(16)}`);
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
    lifiApiBaseUrl: "https://li.quest/v1",
    lifiIntegrator: "openclaw-test",
    lifiDefaultDenyBridges: "mayan",
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

test("getTokenBalance falls back to raw eth_call when WDK balance read throws missing revert data", async () => {
  await withHarness(
    {
      failTokenBalanceRead: true,
      tokenBalance: 5529342504n,
    },
    async ({ service, state, config }) => {
      const result = await service.getTokenBalance({
        seedPhrase: VALID_MNEMONIC,
        tokenAddress: config.tokenIn,
        network: config.network,
      });
      assert.equal(result.balance.toString(), "5529342504");
      assert.equal(result.balanceFormatted, "5529.342504");
      assert.equal(state.directBalanceReadCalls, 1);
    }
  );
});

test("getTokenBalance degrades metadata without failing the balance read", async () => {
  await withHarness(
    {
      failTokenMetadata: true,
      tokenBalance: 1000n,
    },
    async ({ service, config }) => {
      const result = await service.getTokenBalance({
        seedPhrase: VALID_MNEMONIC,
        tokenAddress: config.tokenIn,
        network: config.network,
      });
      assert.equal(result.balance.toString(), "1000");
      assert.equal(result.balanceFormatted, null);
      assert.equal(result.tokenMetadata.source, "erc20-rpc-unavailable");
      assert.equal(result.tokenMetadata.decimals, null);
    }
  );
});

test("getTokenBalance returns token_read_failed when the token exists but balanceOf stays undecodable", async () => {
  await withHarness(
    {
      failTokenBalanceRead: true,
      emptyBalanceResponse: true,
    },
    async ({ service, config }) => {
      await assert.rejects(
        () =>
          service.getTokenBalance({
            seedPhrase: VALID_MNEMONIC,
            tokenAddress: config.tokenIn,
            network: config.network,
          }),
        (error) => {
          assert.equal(error.errorCode, "token_read_failed");
          assert.match(String(error.message || ""), /Token balance could not be read/);
          return true;
        }
      );
    }
  );
});

test("quoteTokenTransfer returns insufficient_funds when token balance is below requested amount", async () => {
  await withHarness(
    {
      tokenBalance: 0n,
    },
    async ({ service, state, config }) => {
      await assert.rejects(
        () =>
          service.quoteTokenTransfer({
            seedPhrase: VALID_MNEMONIC,
            tokenAddress: config.tokenIn,
            recipient: DEFAULT_TOKEN_OUT,
            amount: "1",
            network: config.network,
          }),
        (error) => {
          assert.equal(error.errorCode, "insufficient_funds");
          assert.match(String(error.message || ""), /Insufficient token balance/);
          assert.equal(state.tokenTransferQuoteCalls, 0);
          return true;
        }
      );
    }
  );
});

test("quoteTokenTransfer maps token transfer simulation revert to token_transfer_failed", async () => {
  await withHarness(
    {
      tokenBalance: 5n,
      failTokenTransferEstimate: true,
    },
    async ({ service, config }) => {
      await assert.rejects(
        () =>
          service.quoteTokenTransfer({
            seedPhrase: VALID_MNEMONIC,
            tokenAddress: config.tokenIn,
            recipient: DEFAULT_TOKEN_OUT,
            amount: "1",
            network: config.network,
          }),
        (error) => {
          assert.equal(error.errorCode, "token_transfer_failed");
          assert.match(String(error.message || ""), /could not be simulated/);
          return true;
        }
      );
    }
  );
});

test("sendTokenTransfer returns insufficient_funds when token balance is below requested amount", async () => {
  await withHarness(
    {
      tokenBalance: 0n,
    },
    async ({ service, state, config }) => {
      await assert.rejects(
        () =>
          service.sendTokenTransfer({
            seedPhrase: VALID_MNEMONIC,
            tokenAddress: config.tokenIn,
            recipient: DEFAULT_TOKEN_OUT,
            amount: "1",
            network: config.network,
          }),
        (error) => {
          assert.equal(error.errorCode, "insufficient_funds");
          assert.match(String(error.message || ""), /Insufficient token balance/);
          assert.equal(state.tokenTransferSendCalls, 0);
          return true;
        }
      );
    }
  );
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
    assert.equal(state.sendCalls[0].gasLimit, "27300");
    assert.equal(result.confirmed, true);
  });
});

test("LI.FI source transaction uses a padded final gas limit and waits for receipt", async () => {
  await withHarness({ initialAllowance: 1000000n }, async ({ service, state, config }) => {
    const result = await service.sendLifiSwap({
      seedPhrase: VALID_MNEMONIC,
      tokenIn: config.tokenIn,
      destinationChain: "base",
      outputToken: DEFAULT_TOKEN_OUT,
      destinationAddress: DEFAULT_ADDRESS,
      tokenInAmount: config.amountIn,
      network: config.network,
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
    assert.equal(result.confirmed, true);
    assert.equal(state.sendCalls.length, 1);
    assert.equal(state.sendCalls[0].gasLimit, "27300");
    assert.ok(state.receiptPolls >= 1);
  });
});

test("quoteSwap falls back to route gasCost when swap gas estimate is unavailable before approval", async () => {
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
      assert.equal(quote.estimatedSwapFeeWei, "1990000");
      assert.equal(quote.estimatedFeeWei, "1990002");
      assert.equal(quote.feeEstimateAvailable, true);
      assert.equal(quote.feeEstimateError, null);
      assert.equal(state.sendCalls.length, 0);
    }
  );
});

test("quoteSwap falls back to raw rpc gas estimate when wallet fee quote fails with insufficient funds", async () => {
  await withHarness(
    {
      failSwapFeeQuoteInsufficientFunds: true,
    },
    async ({ service, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(quote.allowance.approvalRequired, true);
      assert.equal(quote.estimatedSwapFeeWei, "42000");
      assert.equal(quote.estimatedFeeWei, "42002");
      assert.equal(quote.feeEstimateAvailable, true);
      assert.equal(quote.feeEstimateError, null);
    }
  );
});

test("quoteSwap falls back to route gasCost when rpc gas estimate is unavailable", async () => {
  await withHarness(
    {
      failSwapFeeQuoteInsufficientFunds: true,
      failRpcEstimateGas: true,
    },
    async ({ service, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(quote.allowance.approvalRequired, true);
      assert.equal(quote.estimatedSwapFeeWei, "1990000");
      assert.equal(quote.estimatedFeeWei, "1990002");
      assert.equal(quote.feeEstimateAvailable, true);
      assert.equal(quote.feeEstimateError, null);
    }
  );
});

test("quoteSwap lowercases token addresses before calling Velora", async () => {
  await withHarness(
    {
      tokenOut: DEFAULT_TOKEN_OUT_MIXED_CASE,
      failOnMixedCaseDestToken: true,
    },
    async ({ service, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(quote.tokenOutMetadata.address, DEFAULT_TOKEN_OUT_MIXED_CASE);
      assert.equal(quote.allowance.approvalRequired, true);
    }
  );
});

test("quoteLifiSwap lowercases EVM token addresses before calling LI.FI", async () => {
  await withHarness(
    {
      tokenIn: DEFAULT_TOKEN_OUT_MIXED_CASE,
      failOnMixedCaseLifiToken: true,
    },
    async ({ service, state, config }) => {
      const quote = await service.quoteLifiSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        destinationChain: "base",
        outputToken: BASE_USDC_CHECKSUMMED,
        destinationAddress: DEFAULT_ADDRESS,
        tokenInAmount: config.amountIn,
        network: config.network,
      });

      assert.equal(state.lifiQuoteUrls.length, 1);
      const url = new URL(state.lifiQuoteUrls[0]);
      assert.equal(url.searchParams.get("fromToken"), DEFAULT_TOKEN_OUT_MIXED_CASE_LOWER);
      assert.equal(url.searchParams.get("toToken"), BASE_USDC_LOWER);
      assert.equal(quote.swapRequest.tokenIn, DEFAULT_TOKEN_OUT_MIXED_CASE_LOWER);
      assert.equal(quote.swapRequest.outputToken, BASE_USDC_LOWER);
      assert.equal(quote.tokenInMetadata.address, DEFAULT_TOKEN_OUT_MIXED_CASE_LOWER);
      assert.equal(quote.outputTokenMetadata.address, BASE_USDC_LOWER);
    }
  );
});

test("quoteSwap falls back to Velora route decimals when ERC-20 metadata decimals is invalid", async () => {
  await withHarness(
    {
      failDecimalsMetadata: true,
    },
    async ({ service, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(quote.tokenInMetadata.decimals, config.tokenDecimals);
      assert.equal(quote.tokenOutMetadata.decimals, config.tokenDecimals);
      assert.equal(quote.tokenInMetadata.source, "swap-route-fallback");
      assert.equal(quote.tokenOutMetadata.source, "swap-route-fallback");
      assert.equal(quote.inputAmountFormatted, "1");
      assert.equal(quote.outputAmountFormatted, "0.995");
      assert.equal(quote.allowance.approvalRequired, true);
    }
  );
});

test("quoteSwap skips allowance and approval for native token input", async () => {
  await withHarness(
    {
      tokenIn: NATIVE_ETH,
      amountIn: "1000000000000000000",
      destAmount: "995000",
      swapTxValue: "1000000000000000000",
      disallowAllowanceRead: true,
    },
    async ({ service, state, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(state.allowanceReadCalls, 0);
      assert.equal(quote.allowance.approvalRequired, false);
      assert.deepEqual(quote.allowance.approvalSequence, []);
      assert.equal(quote.allowance.readError, null);
      assert.equal(quote.tokenInMetadata.symbol, "ETH");
      assert.equal(quote.tokenInMetadata.decimals, 18);
      assert.equal(quote.tokenInMetadata.source, "native-asset");
      assert.equal(quote.inputAmountFormatted, "1");
      assert.equal(quote.swapTransaction.value, config.amountIn);
    }
  );
});

test("quoteSwap accepts eth alias for native token input", async () => {
  await withHarness(
    {
      tokenIn: NATIVE_ETH,
      amountIn: "1000000000000000000",
      destAmount: "995000",
      swapTxValue: "1000000000000000000",
      disallowAllowanceRead: true,
    },
    async ({ service, state, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "eth",
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(state.allowanceReadCalls, 0);
      assert.equal(quote.swapRequest.tokenIn, NATIVE_ETH);
      assert.equal(quote.allowance.approvalRequired, false);
      assert.equal(quote.tokenInMetadata.symbol, "ETH");
      assert.equal(quote.swapTransaction.value, config.amountIn);
    }
  );
});

test("quoteSwap accepts zero address alias for native token input", async () => {
  await withHarness(
    {
      tokenIn: NATIVE_ETH,
      amountIn: "1000000000000000000",
      destAmount: "995000",
      swapTxValue: "1000000000000000000",
      disallowAllowanceRead: true,
    },
    async ({ service, state, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: "0x0000000000000000000000000000000000000000",
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(state.allowanceReadCalls, 0);
      assert.equal(quote.swapRequest.tokenIn, NATIVE_ETH);
      assert.equal(quote.allowance.approvalRequired, false);
      assert.equal(quote.swapTransaction.value, config.amountIn);
    }
  );
});

test("quoteSwap accepts eth alias for native token output", async () => {
  await withHarness(
    {
      tokenOut: NATIVE_ETH,
      amountIn: "1000000",
      destAmount: "995000000000000000",
      swapTxValue: "0",
    },
    async ({ service, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: "eth",
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(quote.swapRequest.tokenOut, NATIVE_ETH);
      assert.equal(quote.tokenOutMetadata.symbol, "ETH");
      assert.equal(quote.tokenOutMetadata.decimals, 18);
      assert.equal(quote.tokenOutMetadata.source, "native-asset");
      assert.equal(quote.allowance.approvalRequired, true);
      assert.equal(quote.swapTransaction.value, "0");
    }
  );
});

test("quoteSwap falls back to route gasCost for native token input when fee estimate is unavailable", async () => {
  await withHarness(
    {
      tokenIn: NATIVE_ETH,
      amountIn: "1000000000000000000",
      destAmount: "995000",
      swapTxValue: "1000000000000000000",
      disallowAllowanceRead: true,
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
      assert.equal(state.allowanceReadCalls, 0);
      assert.equal(quote.allowance.approvalRequired, false);
      assert.equal(quote.estimatedSwapFeeWei, "1990000");
      assert.equal(quote.estimatedFeeWei, "1990000");
      assert.equal(quote.feeEstimateAvailable, true);
      assert.equal(quote.feeEstimateError, null);
    }
  );
});

test("quoteSwap degrades gracefully when allowance read returns empty result data", async () => {
  await withHarness(
    {
      failAllowanceRead: true,
    },
    async ({ service, config }) => {
      const quote = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(quote.allowance.approvalRequired, true);
      assert.equal(quote.allowance.currentAllowance, "0");
      assert.equal(quote.allowance.readError.code, "bad_data");
      assert.match(String(quote.allowance.readError.message || ""), /allowance\(address,address\)/);
    }
  );
});

test("swap succeeds for native token input without approval path", async () => {
  await withHarness(
    {
      tokenIn: NATIVE_ETH,
      amountIn: "1000000000000000000",
      destAmount: "995000",
      swapTxValue: "1000000000000000000",
      disallowAllowanceRead: true,
    },
    async ({ service, state, config }) => {
      const result = await service.swap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(state.allowanceReadCalls, 0);
      assert.equal(state.approveCalls.length, 0);
      assert.equal(state.sendCalls.length, 1);
      assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
      assert.equal(result.allowance.approvalRequired, false);
    }
  );
});

test("swap tolerates refreshed quote drift within slippage window", async () => {
  await withHarness(
    {
      tokenIn: NATIVE_ETH,
      amountIn: "1000000000000000000",
      destAmount: "995000",
      quoteDestAmounts: ["995000", "990500"],
      swapTxValue: "1000000000000000000",
      disallowAllowanceRead: true,
    },
    async ({ service, config }) => {
      const preview = await service.quoteSwap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      const result = await service.swap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
        expectedQuoteFingerprint: preview.quoteFingerprint,
        minimumTokenOutAmount: preview.minimumOutputAmountRaw,
      });
      assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
      assert.equal(result.minimumOutputAmountRaw, "980595");
    }
  );
});

test("swap rejects refreshed quote drift beyond slippage window", async () => {
  await withHarness(
    {
      tokenIn: NATIVE_ETH,
      amountIn: "1000000000000000000",
      destAmount: "995000",
      quoteDestAmounts: ["995000", "980000"],
      swapTxValue: "1000000000000000000",
      disallowAllowanceRead: true,
    },
    async ({ service, config }) => {
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
            minimumTokenOutAmount: preview.minimumOutputAmountRaw,
          }),
        (error) => {
          assert.equal(error.errorCode, "swap_quote_changed");
          return true;
        }
      );
    }
  );
});

test("swap can proceed after approval when allowance read remains undecodable", async () => {
  await withHarness(
    {
      failAllowanceRead: true,
    },
    async ({ service, state, config }) => {
      const result = await service.swap({
        seedPhrase: VALID_MNEMONIC,
        tokenIn: config.tokenIn,
        tokenOut: config.tokenOut,
        tokenInAmount: config.amountIn,
        network: config.network,
      });
      assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
      assert.deepEqual(state.approveCalls, [config.amountIn]);
      assert.equal(result.simulation.ok, true);
      assert.equal(result.allowance.readError.code, "bad_data");
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
      quoteDestAmounts: ["995000", "995000", "980000"],
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
            minimumTokenOutAmount: preview.minimumOutputAmountRaw,
          }),
        /allowed slippage window/
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
