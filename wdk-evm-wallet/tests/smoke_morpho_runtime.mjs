import assert from "node:assert/strict";
import test from "node:test";

import MorphoProtocolEvm from "@morpho-org/wdk-protocol-lending-morpho-evm";
import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

import { WdkEvmWalletService } from "../src/wdk_evm_wallet.js";

const DEFAULT_ADDRESS = "0x1111111111111111111111111111111111111111";
const DEFAULT_MARKET_ID =
  "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836";
const DEFAULT_VAULT_ADDRESS = "0xb576765fB15505433aF24FEe2c0325895C559FB2";
const DEFAULT_TOKEN = "0x2222222222222222222222222222222222222222";
const APPROVAL_SPENDER = "0x3333333333333333333333333333333333333333";
const MORPHO_CORE = "0x4444444444444444444444444444444444444444";
const GENERAL_ADAPTER = "0x5555555555555555555555555555555555555555";
const APPROVAL_DATA = "0xaaaaaaaa";
const AUTHORIZATION_DATA = "0xbbbbbbbb";

function createService() {
  return new WdkEvmWalletService({
    network: "base",
    morphoApiBaseUrl: "https://morpho-api.test/graphql",
    networkProfiles: {
      ethereum: {
        chainId: 1,
        providerUrl: "http://fake-rpc.local",
        nativeSymbol: "ETH",
      },
      base: {
        chainId: 8453,
        providerUrl: "http://fake-rpc.local",
        nativeSymbol: "ETH",
      },
    },
  });
}

function withMockedFetch(handler, callback) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return Promise.resolve()
    .then(callback)
    .finally(() => {
      globalThis.fetch = original;
    });
}

function createMorphoHarness(options = {}) {
  const state = {
    allowance: BigInt(options.initialAllowance ?? 0n),
    approvalSatisfied: Boolean(options.initialApprovalSatisfied),
    authorizationSatisfied: Boolean(options.initialAuthorizationSatisfied),
    quoteCalls: [],
    protocolCalls: [],
    sentTransactions: [],
  };

  const fakeAccount = {
    _config: {
      provider: {
        async request({ method }) {
          if (method === "eth_chainId") {
            return "0x2105";
          }
          if (method === "net_version") {
            return "8453";
          }
          return "0x1";
        },
      },
    },
    async getAddress() {
      return DEFAULT_ADDRESS;
    },
    async getAllowance() {
      return state.allowance;
    },
    async quoteSendTransaction(tx) {
      state.quoteCalls.push(tx);
      if (String(tx?.data || "") === AUTHORIZATION_DATA) {
        return { fee: BigInt(options.authorizationFee ?? 5n) };
      }
      return { fee: BigInt(options.approvalFee ?? 3n) };
    },
    async sendTransaction(tx) {
      state.sentTransactions.push(tx);
      if (String(tx?.data || "") === APPROVAL_DATA) {
        state.approvalSatisfied = true;
        state.allowance = BigInt(options.requiredAmount ?? 1_000_000n);
      }
      if (String(tx?.data || "") === AUTHORIZATION_DATA) {
        state.authorizationSatisfied = true;
      }
      return {
        hash: `0x${String(state.sentTransactions.length).padStart(64, "a")}`,
        fee:
          String(tx?.data || "") === AUTHORIZATION_DATA
            ? BigInt(options.authorizationFee ?? 5n)
            : BigInt(options.approvalFee ?? 3n),
      };
    },
  };

  const originals = {
    getAccount: WalletManagerEvm.prototype.getAccount,
    disposeWallet: WalletManagerEvm.prototype.dispose,
    getVaultAddress: MorphoProtocolEvm.prototype.getVaultAddress,
    getBorrowMarketId: MorphoProtocolEvm.prototype.getBorrowMarketId,
    getSupplyRequirements: MorphoProtocolEvm.prototype.getSupplyRequirements,
    quoteSupply: MorphoProtocolEvm.prototype.quoteSupply,
    supply: MorphoProtocolEvm.prototype.supply,
    getBorrowRequirements: MorphoProtocolEvm.prototype.getBorrowRequirements,
    quoteBorrow: MorphoProtocolEvm.prototype.quoteBorrow,
    borrow: MorphoProtocolEvm.prototype.borrow,
    fetch: globalThis.fetch,
  };

  WalletManagerEvm.prototype.getAccount = async function getAccount() {
    return fakeAccount;
  };
  WalletManagerEvm.prototype.dispose = function dispose() {};

  MorphoProtocolEvm.prototype.getVaultAddress = function getVaultAddress() {
    return DEFAULT_VAULT_ADDRESS;
  };
  MorphoProtocolEvm.prototype.getBorrowMarketId = function getBorrowMarketId() {
    return DEFAULT_MARKET_ID;
  };
  MorphoProtocolEvm.prototype.getSupplyRequirements = async function getSupplyRequirements() {
    state.protocolCalls.push({ name: "getSupplyRequirements" });
    if (state.approvalSatisfied) {
      return [];
    }
    return [
      {
        to: APPROVAL_SPENDER,
        value: 0n,
        data: APPROVAL_DATA,
        action: {
          type: "erc20Approval",
          args: {
            spender: APPROVAL_SPENDER,
            amount: BigInt(options.requiredAmount ?? 1_000_000n),
          },
        },
      },
    ];
  };
  MorphoProtocolEvm.prototype.quoteSupply = async function quoteSupply(params) {
    state.protocolCalls.push({ name: "quoteSupply", params });
    return { fee: BigInt(options.operationFee ?? 7n) };
  };
  MorphoProtocolEvm.prototype.supply = async function supply(params) {
    state.protocolCalls.push({ name: "supply", params });
    return {
      hash: `0x${"d".repeat(64)}`,
      fee: BigInt(options.operationFee ?? 7n),
    };
  };
  MorphoProtocolEvm.prototype.getBorrowRequirements = async function getBorrowRequirements() {
    state.protocolCalls.push({ name: "getBorrowRequirements" });
    if (state.authorizationSatisfied) {
      return [];
    }
    return [
      {
        to: MORPHO_CORE,
        value: 0n,
        data: AUTHORIZATION_DATA,
        action: {
          type: "morphoAuthorization",
          args: {
            authorized: GENERAL_ADAPTER,
            isAuthorized: true,
          },
        },
      },
    ];
  };
  MorphoProtocolEvm.prototype.quoteBorrow = async function quoteBorrow(params) {
    state.protocolCalls.push({ name: "quoteBorrow", params });
    return { fee: BigInt(options.operationFee ?? 9n) };
  };
  MorphoProtocolEvm.prototype.borrow = async function borrow(params) {
    state.protocolCalls.push({ name: "borrow", params });
    return {
      hash: `0x${"e".repeat(64)}`,
      fee: BigInt(options.operationFee ?? 9n),
    };
  };
  globalThis.fetch = async (url, request) => {
    if (String(url).startsWith("http://fake-rpc.local")) {
      return {
        ok: true,
        status: 200,
        async json() {
          const body = JSON.parse(String(request?.body || "{}"));
          if (body.method === "eth_getTransactionReceipt") {
            return {
              result: {
                status: "0x1",
                transactionHash: body.params?.[0] || `0x${"f".repeat(64)}`,
              },
            };
          }
          return { result: "0x1" };
        },
      };
    }
    throw new Error(`Unexpected fetch URL: ${String(url)}`);
  };

  return {
    state,
    restore() {
      WalletManagerEvm.prototype.getAccount = originals.getAccount;
      WalletManagerEvm.prototype.dispose = originals.disposeWallet;
      MorphoProtocolEvm.prototype.getVaultAddress = originals.getVaultAddress;
      MorphoProtocolEvm.prototype.getBorrowMarketId = originals.getBorrowMarketId;
      MorphoProtocolEvm.prototype.getSupplyRequirements = originals.getSupplyRequirements;
      MorphoProtocolEvm.prototype.quoteSupply = originals.quoteSupply;
      MorphoProtocolEvm.prototype.supply = originals.supply;
      MorphoProtocolEvm.prototype.getBorrowRequirements = originals.getBorrowRequirements;
      MorphoProtocolEvm.prototype.quoteBorrow = originals.quoteBorrow;
      MorphoProtocolEvm.prototype.borrow = originals.borrow;
      globalThis.fetch = originals.fetch;
    },
  };
}

test("morpho vault list returns discovery payload", async () => {
  const service = createService();
  const calls = [];

  await withMockedFetch(async (_url, options) => {
    const body = JSON.parse(String(options?.body || "{}"));
    calls.push(body);
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          data: {
            vaultV2s: {
              items: [
                {
                  address: DEFAULT_VAULT_ADDRESS,
                  symbol: "pyUSDm",
                  name: "Paypal USD Main",
                  listed: true,
                  asset: {
                    address: "0x0000000000000000000000000000000000000002",
                    symbol: "PYUSD",
                    decimals: 6,
                    name: "PayPal USD",
                    priceUsd: 1,
                    yield: { apr: 0, lookback: 86400 },
                  },
                  chain: { id: 8453, network: "base" },
                },
              ],
            },
          },
        };
      },
    };
  }, async () => {
    const result = await service.getMorphoVaults({ network: "base" });
    assert.equal(result.protocol, "morpho");
    assert.equal(result.vaultCount, 1);
    assert.equal(result.vaults[0].address, DEFAULT_VAULT_ADDRESS);
    assert.equal(result.listedOnly, true);
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].operationName, "MorphoVaultV2List");
  assert.deepEqual(calls[0].variables.where, { chainId_in: [8453], listed: true });
});

test("morpho market by id returns detailed payload", async () => {
  const service = createService();

  await withMockedFetch(async (_url, options) => {
    const body = JSON.parse(String(options?.body || "{}"));
    assert.equal(body.operationName, "MorphoMarketById");
    assert.equal(body.variables.marketId, DEFAULT_MARKET_ID);
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          data: {
            marketById: {
              marketId: DEFAULT_MARKET_ID,
              lltv: "860000000000000000",
              loanAsset: { address: "0xloan", symbol: "USDC", decimals: 6, name: "USD Coin" },
              collateralAsset: {
                address: "0xcollateral",
                symbol: "cbBTC",
                decimals: 8,
                name: "Coinbase Wrapped BTC",
              },
              supplyingVaultV2s: [
                { address: "0xvault1", name: "Steakhouse USDC", symbol: "steakUSDC" },
              ],
            },
          },
        };
      },
    };
  }, async () => {
    const result = await service.getMorphoMarkets({
      network: "base",
      marketId: DEFAULT_MARKET_ID,
    });
    assert.equal(result.protocol, "morpho");
    assert.equal(result.found, true);
    assert.equal(result.market.marketId, DEFAULT_MARKET_ID);
    assert.equal(result.market.supplyingVaultV2s.length, 1);
  });
});

test("morpho positions returns user overview from explicit address", async () => {
  const service = createService();

  await withMockedFetch(async (_url, options) => {
    const body = JSON.parse(String(options?.body || "{}"));
    assert.equal(body.operationName, "MorphoUserByAddress");
    assert.equal(body.variables.address, DEFAULT_ADDRESS);
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          data: {
            userByAddress: {
              address: DEFAULT_ADDRESS,
              marketPositions: [
                {
                  market: {
                    marketId: DEFAULT_MARKET_ID,
                    loanAsset: { address: "0xloan", symbol: "USDC", decimals: 6, name: "USD Coin" },
                    collateralAsset: {
                      address: "0xcollateral",
                      symbol: "cbBTC",
                      decimals: 8,
                      name: "Coinbase Wrapped BTC",
                    },
                  },
                  state: {
                    supplyShares: "10",
                    supplyAssets: "1000000",
                    supplyAssetsUsd: 1,
                    borrowShares: "0",
                    borrowAssets: "0",
                    borrowAssetsUsd: 0,
                    collateral: "0",
                    collateralUsd: 0,
                  },
                },
              ],
              vaultV2Positions: [
                {
                  vault: {
                    address: DEFAULT_VAULT_ADDRESS,
                    name: "Paypal USD Main",
                    symbol: "pyUSDm",
                    asset: {
                      address: "0xasset",
                      symbol: "PYUSD",
                      decimals: 6,
                      name: "PayPal USD",
                    },
                  },
                  shares: "5",
                  assets: "5000000",
                  assetsUsd: 5,
                },
              ],
            },
          },
        };
      },
    };
  }, async () => {
    const result = await service.getMorphoPositions({
      network: "base",
      address: DEFAULT_ADDRESS,
    });
    assert.equal(result.protocol, "morpho");
    assert.equal(result.marketPositionCount, 1);
    assert.equal(result.vaultPositionCount, 1);
    assert.equal(result.address, DEFAULT_ADDRESS);
  });
});

test("morpho api graphql errors are shaped", async () => {
  const service = createService();

  await withMockedFetch(async () => ({
    ok: true,
    status: 200,
    async json() {
      return {
        errors: [{ message: "bad query" }],
      };
    },
  }), async () => {
    await assert.rejects(
      () => service.getMorphoVaults({ network: "base" }),
      (error) => error?.errorCode === "morpho_api_failed" && /bad query/.test(error.message)
    );
  });
});

test("morpho vault supply quote reports approval requirements and send executes them", async () => {
  const service = createService();
  const harness = createMorphoHarness({
    requiredAmount: 2_500_000n,
    approvalFee: 3n,
    operationFee: 7n,
  });

  try {
    const quote = await service.quoteMorphoVaultOperation({
      seedPhrase:
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
      network: "base",
      vaultAddress: DEFAULT_VAULT_ADDRESS,
      token: DEFAULT_TOKEN,
      amount: "2500000",
      operation: "supply",
    });
    assert.equal(quote.protocol, "morpho");
    assert.equal(quote.surface, "vault");
    assert.equal(quote.requirements.required, true);
    assert.equal(quote.requirements.approvalRequired, true);
    assert.equal(quote.requirements.requirementCount, 1);
    assert.equal(quote.estimatedRequirementsFeeWei, "3");
    assert.equal(quote.estimatedOperationFeeWei, "7");

    const sent = await service.sendMorphoVaultOperation({
      seedPhrase:
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
      network: "base",
      vaultAddress: DEFAULT_VAULT_ADDRESS,
      token: DEFAULT_TOKEN,
      amount: "2500000",
      operation: "supply",
      expectedQuoteFingerprint: quote.quoteFingerprint,
    });
    assert.equal(sent.result.requirements.length, 1);
    assert.equal(sent.result.requirements[0].type, "approval");
    assert.equal(sent.result.requirementsFee, "3");
    assert.equal(sent.result.totalFee, "10");
    assert.equal(harness.state.sentTransactions.length, 1);
    assert.equal(harness.state.sentTransactions[0].data, APPROVAL_DATA);
    assert.ok(harness.state.protocolCalls.some((entry) => entry.name === "supply"));
  } finally {
    harness.restore();
  }
});

test("morpho market borrow quote reports authorization requirements and send executes them", async () => {
  const service = createService();
  const harness = createMorphoHarness({
    authorizationFee: 5n,
    operationFee: 9n,
  });

  try {
    const quote = await service.quoteMorphoMarketOperation({
      seedPhrase:
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
      network: "base",
      marketId: DEFAULT_MARKET_ID,
      token: DEFAULT_TOKEN,
      amount: "1000000",
      operation: "borrow",
    });
    assert.equal(quote.protocol, "morpho");
    assert.equal(quote.surface, "market");
    assert.equal(quote.requirements.required, true);
    assert.equal(quote.requirements.authorizationRequired, true);
    assert.equal(quote.requirements.sequence[0].authorized, GENERAL_ADAPTER.toLowerCase());

    const sent = await service.sendMorphoMarketOperation({
      seedPhrase:
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
      network: "base",
      marketId: DEFAULT_MARKET_ID,
      token: DEFAULT_TOKEN,
      amount: "1000000",
      operation: "borrow",
      expectedQuoteFingerprint: quote.quoteFingerprint,
    });
    assert.equal(sent.result.requirements.length, 1);
    assert.equal(sent.result.requirements[0].type, "authorization");
    assert.equal(sent.result.requirementsFee, "5");
    assert.equal(sent.result.totalFee, "14");
    assert.equal(harness.state.sentTransactions.length, 1);
    assert.equal(harness.state.sentTransactions[0].data, AUTHORIZATION_DATA);
    assert.ok(harness.state.protocolCalls.some((entry) => entry.name === "borrow"));
  } finally {
    harness.restore();
  }
});

test("morpho send rejects a changed quote fingerprint", async () => {
  const service = createService();
  const harness = createMorphoHarness();

  try {
    await assert.rejects(
      () =>
        service.sendMorphoVaultOperation({
          seedPhrase:
            "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
          network: "base",
          vaultAddress: DEFAULT_VAULT_ADDRESS,
          token: DEFAULT_TOKEN,
          amount: "1000",
          operation: "supply",
          expectedQuoteFingerprint: "stale",
        }),
      (error) => error?.errorCode === "morpho_quote_changed"
    );
  } finally {
    harness.restore();
  }
});
