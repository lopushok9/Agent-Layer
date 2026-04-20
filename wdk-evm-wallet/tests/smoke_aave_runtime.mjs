import assert from "node:assert/strict";
import test from "node:test";

import AaveProtocolEvm from "@tetherto/wdk-protocol-lending-aave-evm";
import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

import { WdkEvmWalletService } from "../src/wdk_evm_wallet.js";

const VALID_MNEMONIC =
  "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const DEFAULT_ADDRESS = "0x1111111111111111111111111111111111111111";
const DEFAULT_TOKEN = "0x2222222222222222222222222222222222222222";
const AAVE_POOL = "0x3333333333333333333333333333333333333333";
const APPROVE_SELECTOR = "0x095ea7b3";

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

  const originals = {
    getAccount: WalletManagerEvm.prototype.getAccount,
    disposeWallet: WalletManagerEvm.prototype.dispose,
    getPoolContract: AaveProtocolEvm.prototype._getPoolContract,
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
    _config: { provider: config.networkProfiles.ethereum.providerUrl },
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
    return { target: AAVE_POOL };
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

  globalThis.fetch = async () => ({
    ok: true,
    async json() {
      return {
        jsonrpc: "2.0",
        id: 1,
        result: "0x",
      };
    },
  });

  const service = new WdkEvmWalletService(config);
  return {
    service,
    state,
    config,
    restore() {
      WalletManagerEvm.prototype.getAccount = originals.getAccount;
      WalletManagerEvm.prototype.dispose = originals.disposeWallet;
      AaveProtocolEvm.prototype._getPoolContract = originals.getPoolContract;
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
