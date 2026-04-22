import assert from "node:assert/strict";
import test from "node:test";

import { AbiCoder, id } from "ethers";
import AaveProtocolEvm from "@tetherto/wdk-protocol-lending-aave-evm";
import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

import { WdkEvmWalletService } from "../src/wdk_evm_wallet.js";

const VALID_MNEMONIC =
  "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const DEFAULT_ADDRESS = "0x1111111111111111111111111111111111111111";
const DEFAULT_TOKEN = "0x2222222222222222222222222222222222222222";
const AAVE_POOL = "0x3333333333333333333333333333333333333333";
const AAVE_UI_POOL_DATA_PROVIDER = "0x4444444444444444444444444444444444444444";
const AAVE_POOL_ADDRESSES_PROVIDER = "0x5555555555555555555555555555555555555555";
const AAVE_PRICE_ORACLE = "0x6666666666666666666666666666666666666666";
const DEFAULT_A_TOKEN = "0x7777777777777777777777777777777777777777";
const DEFAULT_VARIABLE_DEBT_TOKEN = "0x8888888888888888888888888888888888888888";
const DEFAULT_STRATEGY = "0x9999999999999999999999999999999999999999";
const AAVE_PROTOCOL_DATA_PROVIDER = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const APPROVE_SELECTOR = "0x095ea7b3";
const GET_USER_RESERVE_DATA_SELECTOR = id("getUserReserveData(address,address)").slice(0, 10);

function createHarness(options = {}) {
  const state = {
    allowance: BigInt(options.initialAllowance ?? 0n),
    approveCalls: [],
    quoteCalls: [],
    protocolCalls: [],
  };
  const config = {
    network: options.network ?? "ethereum",
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
    transferMaxFeeWei: null,
    operationFee: BigInt(options.operationFee ?? 7n),
    approvalFee: BigInt(options.approvalFee ?? 3n),
    failOperation: Boolean(options.failOperation),
  };
  const fakeProvider = {
    async request({ method, params }) {
      if (method === "eth_chainId") {
        return config.network === "base" ? "0x2105" : "0x1";
      }
      if (method === "net_version") {
        return config.network === "base" ? "8453" : "1";
      }
      if (method === "eth_blockNumber") {
        return "0x1";
      }
      if (method === "eth_call") {
        const data = String(params?.[0]?.data || "");
        if (data.startsWith(GET_USER_RESERVE_DATA_SELECTOR)) {
          const coder = AbiCoder.defaultAbiCoder();
          return coder.encode(
            ["uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint256", "uint40", "bool"],
            [1_000_000n, 0n, 250_000n, 0n, 250_000n, 0n, 5n * 10n ** 25n, 0n, true]
          );
        }
        return "0x";
      }
      throw new Error(`Unsupported provider method: ${method}`);
    },
  };

  const originals = {
    getAccount: WalletManagerEvm.prototype.getAccount,
    disposeWallet: WalletManagerEvm.prototype.dispose,
    getPoolContract: AaveProtocolEvm.prototype._getPoolContract,
    getAddressMap: AaveProtocolEvm.prototype._getAddressMap,
    getUiPoolDataProviderContract: AaveProtocolEvm.prototype._getUiPoolDataProviderContract,
    quoteSupply: AaveProtocolEvm.prototype.quoteSupply,
    quoteWithdraw: AaveProtocolEvm.prototype.quoteWithdraw,
    quoteBorrow: AaveProtocolEvm.prototype.quoteBorrow,
    quoteRepay: AaveProtocolEvm.prototype.quoteRepay,
    supply: AaveProtocolEvm.prototype.supply,
    withdraw: AaveProtocolEvm.prototype.withdraw,
    borrow: AaveProtocolEvm.prototype.borrow,
    repay: AaveProtocolEvm.prototype.repay,
    getAccountData: AaveProtocolEvm.prototype.getAccountData,
    fetch: globalThis.fetch,
  };

  const fakeAccount = {
    _config: { provider: fakeProvider },
    async getAddress() {
      return DEFAULT_ADDRESS;
    },
    async getAllowance() {
      return state.allowance;
    },
    async quoteSendTransaction(tx) {
      const isApprove = String(tx?.data || "").startsWith(APPROVE_SELECTOR);
      state.quoteCalls.push(isApprove ? "approve" : "operation");
      return {
        fee: isApprove ? config.approvalFee : config.operationFee,
      };
    },
    async approve({ token, spender, amount }) {
      state.allowance = BigInt(amount);
      state.approveCalls.push({ token, spender, amount: String(amount) });
      return {
        hash: `0x${String(state.approveCalls.length).padStart(64, "a")}`,
        fee: config.approvalFee,
      };
    },
  };

  WalletManagerEvm.prototype.getAccount = async function getAccount() {
    return fakeAccount;
  };
  WalletManagerEvm.prototype.dispose = function dispose() {};

  AaveProtocolEvm.prototype._getPoolContract = async function getPoolContract() {
    return {
      target: AAVE_POOL,
      async getUserEMode() {
        return 0n;
      },
    };
  };
  AaveProtocolEvm.prototype._getAddressMap = async function getAddressMap() {
    return {
      pool: AAVE_POOL,
      uiPoolDataProvider: AAVE_UI_POOL_DATA_PROVIDER,
      poolAddressesProvider: AAVE_POOL_ADDRESSES_PROVIDER,
      priceOracle: AAVE_PRICE_ORACLE,
      aaveProtocolDataProvider: AAVE_PROTOCOL_DATA_PROVIDER,
    };
  };
  AaveProtocolEvm.prototype._getUiPoolDataProviderContract = async function getUiPoolDataProviderContract() {
    return {
      async getReservesData() {
        return [
          [
            {
              underlyingAsset: DEFAULT_TOKEN,
              name: "USD Coin",
              symbol: "USDC",
              decimals: 6,
              baseLTVasCollateral: 7500n,
              reserveLiquidationThreshold: 8000n,
              reserveLiquidationBonus: 10500n,
              reserveFactor: 1000n,
              usageAsCollateralEnabled: true,
              borrowingEnabled: true,
              isActive: true,
              isFrozen: false,
              liquidityIndex: 10n ** 27n,
              variableBorrowIndex: 10n ** 27n,
              liquidityRate: 5n * 10n ** 25n,
              variableBorrowRate: 7n * 10n ** 25n,
              lastUpdateTimestamp: 1700000000n,
              aTokenAddress: DEFAULT_A_TOKEN,
              variableDebtTokenAddress: DEFAULT_VARIABLE_DEBT_TOKEN,
              interestRateStrategyAddress: DEFAULT_STRATEGY,
              availableLiquidity: 5_000_000n,
              totalScaledVariableDebt: 2_000_000n,
              priceInMarketReferenceCurrency: 100_000_000n,
              priceOracle: AAVE_PRICE_ORACLE,
              variableRateSlope1: 0n,
              variableRateSlope2: 0n,
              baseVariableBorrowRate: 0n,
              optimalUsageRatio: 0n,
              isPaused: false,
              isSiloedBorrowing: false,
              accruedToTreasury: 0n,
              unbacked: 0n,
              isolationModeTotalDebt: 0n,
              flashLoanEnabled: true,
              debtCeiling: 0n,
              debtCeilingDecimals: 2n,
              borrowCap: 0n,
              supplyCap: 0n,
              borrowableInIsolation: true,
              virtualAccActive: false,
              virtualUnderlyingBalance: 0n,
            },
          ],
          {
            marketReferenceCurrencyUnit: 100_000_000n,
            marketReferenceCurrencyPriceInUsd: 100_000_000n,
            networkBaseTokenPriceInUsd: 3_500_000_000_00n,
            networkBaseTokenPriceDecimals: 8,
          },
        ];
      },
      async getUserReservesData() {
        return [
          [
            {
              underlyingAsset: DEFAULT_TOKEN,
              scaledATokenBalance: 1_000_000n,
              usageAsCollateralEnabledOnUser: true,
              stableBorrowRate: 0n,
              scaledVariableDebt: 250_000n,
              principalStableDebt: 0n,
              stableBorrowLastUpdateTimestamp: 0n,
            },
          ],
          0,
        ];
      },
    };
  };
  for (const name of ["quoteSupply", "quoteWithdraw", "quoteBorrow", "quoteRepay"]) {
    AaveProtocolEvm.prototype[name] = async function quoteOperation(options) {
      state.protocolCalls.push({ name, options });
      return { fee: config.operationFee };
    };
  }
  for (const name of ["supply", "withdraw", "borrow", "repay"]) {
    AaveProtocolEvm.prototype[name] = async function operation(options) {
      state.protocolCalls.push({ name, options });
      if (config.failOperation) {
        throw new Error(`${name} failed`);
      }
      return {
        hash: `0x${"d".repeat(64)}`,
        fee: config.operationFee,
      };
    };
  }
  AaveProtocolEvm.prototype.getAccountData = async function getAccountData() {
    return {
      totalCollateralBase: 1n,
      totalDebtBase: 2n,
      availableBorrowsBase: 3n,
      currentLiquidationThreshold: 4n,
      ltv: 5n,
      healthFactor: 6n,
    };
  };

  globalThis.fetch = async () => {
    return {
      ok: true,
      async json() {
        return {
          jsonrpc: "2.0",
          id: 1,
          result: "0x",
        };
      },
    };
  };

  const service = new WdkEvmWalletService(config);
  return {
    service,
    state,
    config,
    restore() {
      WalletManagerEvm.prototype.getAccount = originals.getAccount;
      WalletManagerEvm.prototype.dispose = originals.disposeWallet;
      AaveProtocolEvm.prototype._getPoolContract = originals.getPoolContract;
      AaveProtocolEvm.prototype._getAddressMap = originals.getAddressMap;
      AaveProtocolEvm.prototype._getUiPoolDataProviderContract = originals.getUiPoolDataProviderContract;
      AaveProtocolEvm.prototype.quoteSupply = originals.quoteSupply;
      AaveProtocolEvm.prototype.quoteWithdraw = originals.quoteWithdraw;
      AaveProtocolEvm.prototype.quoteBorrow = originals.quoteBorrow;
      AaveProtocolEvm.prototype.quoteRepay = originals.quoteRepay;
      AaveProtocolEvm.prototype.supply = originals.supply;
      AaveProtocolEvm.prototype.withdraw = originals.withdraw;
      AaveProtocolEvm.prototype.borrow = originals.borrow;
      AaveProtocolEvm.prototype.repay = originals.repay;
      AaveProtocolEvm.prototype.getAccountData = originals.getAccountData;
      globalThis.fetch = originals.fetch;
    },
  };
}

async function withHarness(options, callback) {
  const harness = createHarness(options);
  try {
    await callback(harness);
  } finally {
    harness.restore();
  }
}

test("Aave account data is exposed as JSON-safe strings", async () => {
  await withHarness({}, async ({ service }) => {
    const result = await service.getAaveAccountData({
      seedPhrase: VALID_MNEMONIC,
      network: "ethereum",
    });
    assert.equal(result.protocol, "aave-v3");
    assert.deepEqual(result.accountData, {
      totalCollateralBase: "1",
      totalDebtBase: "2",
      availableBorrowsBase: "3",
      currentLiquidationThreshold: "4",
      ltv: "5",
      healthFactor: "6",
    });
  });
});

test("Aave supply quote reports pool approval requirement", async () => {
  await withHarness({}, async ({ service, state }) => {
    const result = await service.quoteAaveOperation({
      seedPhrase: VALID_MNEMONIC,
      operation: "supply",
      tokenAddress: DEFAULT_TOKEN,
      amount: "100",
      network: "ethereum",
    });
    assert.equal(result.allowance.approvalRequired, true);
    assert.deepEqual(
      result.allowance.approvalSequence.map((step) => step.type),
      ["approve"]
    );
    assert.equal(result.estimatedApprovalFeeWei, "3");
    assert.equal(result.estimatedOperationFeeWei, null);
    assert.deepEqual(state.quoteCalls, ["approve"]);
  });
});

test("Aave reserves catalog is exposed with formatted reserve metadata", async () => {
  await withHarness({}, async ({ service }) => {
    const result = await service.getAaveReserves({
      seedPhrase: VALID_MNEMONIC,
      network: "ethereum",
    });
    assert.equal(result.protocol, "aave-v3");
    assert.equal(result.reserveCount, 1);
    assert.equal(result.pool, AAVE_POOL);
    assert.equal(result.reserves[0].symbol, "USDC");
    assert.equal(result.reserves[0].priceInUsdFormatted, "1");
    assert.equal(result.reserves[0].liquidityAprPercent, "5");
  });
});

test("Aave user positions are exposed with merged reserve context", async () => {
  await withHarness({}, async ({ service }) => {
    const result = await service.getAavePositions({
      seedPhrase: VALID_MNEMONIC,
      network: "ethereum",
    });
    assert.equal(result.protocol, "aave-v3");
    assert.equal(result.positionCount, 1);
    assert.equal(result.positions[0].symbol, "USDC");
    assert.equal(result.positions[0].suppliedBalanceRaw, "1000000");
    assert.equal(result.positions[0].variableDebtRaw, "250000");
    assert.equal(result.positions[0].collateralEnabled, true);
    assert.equal(result.positions[0].reserve.priceInUsdFormatted, "1");
  });
});

test("Aave borrow quote does not require token approval", async () => {
  await withHarness({}, async ({ service, state }) => {
    const result = await service.quoteAaveOperation({
      seedPhrase: VALID_MNEMONIC,
      operation: "borrow",
      tokenAddress: DEFAULT_TOKEN,
      amount: "100",
      network: "ethereum",
    });
    assert.equal(result.allowance.approvalRequired, false);
    assert.equal(result.estimatedOperationFeeWei, "7");
    assert.deepEqual(state.quoteCalls, []);
    assert.deepEqual(
      state.protocolCalls.map((call) => call.name),
      ["quoteBorrow"]
    );
  });
});

test("Aave supply send approves the pool and then supplies", async () => {
  await withHarness({}, async ({ service, state }) => {
    const result = await service.sendAaveOperation({
      seedPhrase: VALID_MNEMONIC,
      operation: "supply",
      tokenAddress: DEFAULT_TOKEN,
      amount: "100",
      network: "ethereum",
    });
    assert.equal(result.result.hash, `0x${"d".repeat(64)}`);
    assert.equal(result.result.approvalFee, "3");
    assert.equal(result.result.totalFee, "10");
    assert.deepEqual(state.approveCalls, [
      { token: DEFAULT_TOKEN, spender: AAVE_POOL, amount: "100" },
    ]);
    assert.deepEqual(
      state.protocolCalls.map((call) => call.name),
      ["quoteSupply", "supply"]
    );
  });
});

test("Aave failure after approval restores original allowance", async () => {
  await withHarness({ failOperation: true }, async ({ service, state }) => {
    await assert.rejects(
      () =>
        service.sendAaveOperation({
          seedPhrase: VALID_MNEMONIC,
          operation: "supply",
          tokenAddress: DEFAULT_TOKEN,
          amount: "100",
          network: "ethereum",
        }),
      /supply failed/
    );
    assert.equal(state.allowance, 0n);
    assert.deepEqual(state.approveCalls, [
      { token: DEFAULT_TOKEN, spender: AAVE_POOL, amount: "100" },
      { token: DEFAULT_TOKEN, spender: AAVE_POOL, amount: "0" },
    ]);
  });
});
