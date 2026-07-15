import assert from "node:assert/strict";
import test from "node:test";

import { Interface } from "ethers";
import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

import { WdkEvmWalletService } from "../src/wdk_evm_wallet.js";

const VALID_MNEMONIC =
  "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const DEFAULT_ADDRESS = "0x1111111111111111111111111111111111111111";
const STETH = "0xae7ab96520de3a18e5e111b5eaab095312d7fe84";
const WSTETH = "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0";
const REFERRAL_STAKER = "0xa88f0329c2c4ce51ba3fc619bbf44efe7120dd0d";
const WITHDRAWAL_QUEUE = "0x889edc2edab5f40e902b864ad4d7ade8e412f9b1";

const WSTETH_INTERFACE = new Interface([
  "function getWstETHByStETH(uint256 _stETHAmount) view returns (uint256)",
  "function getStETHByWstETH(uint256 _wstETHAmount) view returns (uint256)",
  "function wrap(uint256 _stETHAmount) returns (uint256)",
  "function unwrap(uint256 _wstETHAmount) returns (uint256)",
]);
const STAKER_INTERFACE = new Interface([
  "function stakeETH(address _referral) payable returns (uint256)",
]);
const WITHDRAWAL_QUEUE_INTERFACE = new Interface([
  "function requestWithdrawals(uint256[] _amounts, address _owner) returns (uint256[] requestIds)",
  "function requestWithdrawalsWstETH(uint256[] _amounts, address _owner) returns (uint256[] requestIds)",
  "function getWithdrawalRequests(address _owner) view returns (uint256[] requestIds)",
  "function getWithdrawalStatus(uint256[] _requestIds) view returns ((uint256 amountOfStETH,uint256 amountOfShares,address owner,uint256 timestamp,bool isFinalized,bool isClaimed)[] statuses)",
  "function claimWithdrawal(uint256 _requestId)",
]);

function createHarness(options = {}) {
  const state = {
    allowance: BigInt(options.initialAllowance ?? 0n),
    approveCalls: [],
    sendCalls: [],
    withdrawalRequestIds: [101n, 102n],
  };
  const config = {
    network: "ethereum",
    approvalFee: BigInt(options.approvalFee ?? 3n),
    operationFee: BigInt(options.operationFee ?? 7n),
    nativeBalance: BigInt(options.nativeBalance ?? 2n * 10n ** 18n),
    stEthBalance: BigInt(options.stEthBalance ?? 2n * 10n ** 18n),
    wstEthBalance: BigInt(options.wstEthBalance ?? 1n * 10n ** 18n),
  };

  const fakeProvider = {
    async request({ method, params }) {
      if (method === "eth_chainId") {
        return "0x1";
      }
      if (method === "net_version") {
        return "1";
      }
      if (method === "eth_blockNumber") {
        return "0x1";
      }
      if (method === "eth_getTransactionReceipt") {
        return { status: "0x1" };
      }
      if (method === "eth_estimateGas") {
        return "0x64";
      }
      if (method === "eth_gasPrice" || method === "eth_maxPriorityFeePerGas") {
        return "0x1";
      }
      if (method === "eth_feeHistory") {
        return { baseFeePerGas: ["0x1"] };
      }
      if (method === "eth_call") {
        const tx = params?.[0] || {};
        const to = String(tx.to || "").toLowerCase();
        const data = String(tx.data || "");
        if (to === WSTETH) {
          if (data.startsWith(WSTETH_INTERFACE.getFunction("getWstETHByStETH").selector)) {
            return WSTETH_INTERFACE.encodeFunctionResult("getWstETHByStETH", [950000000000000000n]);
          }
          if (data.startsWith(WSTETH_INTERFACE.getFunction("getStETHByWstETH").selector)) {
            return WSTETH_INTERFACE.encodeFunctionResult("getStETHByWstETH", [1100000000000000000n]);
          }
          if (data.startsWith(WSTETH_INTERFACE.getFunction("wrap").selector)) {
            return WSTETH_INTERFACE.encodeFunctionResult("wrap", [950000000000000000n]);
          }
          if (data.startsWith(WSTETH_INTERFACE.getFunction("unwrap").selector)) {
            return WSTETH_INTERFACE.encodeFunctionResult("unwrap", [1100000000000000000n]);
          }
        }
        if (to === REFERRAL_STAKER && data.startsWith(STAKER_INTERFACE.getFunction("stakeETH").selector)) {
          return STAKER_INTERFACE.encodeFunctionResult("stakeETH", [950000000000000000n]);
        }
        if (to === WITHDRAWAL_QUEUE) {
          if (data.startsWith(WITHDRAWAL_QUEUE_INTERFACE.getFunction("getWithdrawalRequests").selector)) {
            return WITHDRAWAL_QUEUE_INTERFACE.encodeFunctionResult("getWithdrawalRequests", [
              state.withdrawalRequestIds,
            ]);
          }
          if (data.startsWith(WITHDRAWAL_QUEUE_INTERFACE.getFunction("getWithdrawalStatus").selector)) {
            const decoded = WITHDRAWAL_QUEUE_INTERFACE.decodeFunctionData("getWithdrawalStatus", data);
            const requestIds = Array.from(decoded[0] || []).map((value) => BigInt(value));
            return WITHDRAWAL_QUEUE_INTERFACE.encodeFunctionResult("getWithdrawalStatus", [
              requestIds.map((requestId) =>
                requestId === 102n
                  ? {
                      amountOfStETH: 2000000000000000000n,
                      amountOfShares: 2000000000000000000n,
                      owner: DEFAULT_ADDRESS,
                      timestamp: 1710000100n,
                      isFinalized: true,
                      isClaimed: false,
                    }
                  : {
                      amountOfStETH: 1000000000000000000n,
                      amountOfShares: 1000000000000000000n,
                      owner: DEFAULT_ADDRESS,
                      timestamp: 1710000000n,
                      isFinalized: false,
                      isClaimed: false,
                    }
              ),
            ]);
          }
          if (
            data.startsWith(WITHDRAWAL_QUEUE_INTERFACE.getFunction("requestWithdrawals").selector) ||
            data.startsWith(WITHDRAWAL_QUEUE_INTERFACE.getFunction("requestWithdrawalsWstETH").selector)
          ) {
            return WITHDRAWAL_QUEUE_INTERFACE.encodeFunctionResult(
              data.startsWith(WITHDRAWAL_QUEUE_INTERFACE.getFunction("requestWithdrawals").selector)
                ? "requestWithdrawals"
                : "requestWithdrawalsWstETH",
              [[103n]]
            );
          }
        }
        return "0x";
      }
      throw new Error(`Unsupported provider method: ${method}`);
    },
  };

  const originals = {
    getAccount: WalletManagerEvm.prototype.getAccount,
    disposeWallet: WalletManagerEvm.prototype.dispose,
    fetch: globalThis.fetch,
  };

  const fakeAccount = {
    _config: { provider: fakeProvider },
    async getAddress() {
      return DEFAULT_ADDRESS;
    },
    async getBalance() {
      return config.nativeBalance.toString();
    },
    async getTokenBalance(tokenAddress) {
      const normalized = String(tokenAddress || "").toLowerCase();
      if (normalized === STETH) {
        return config.stEthBalance;
      }
      if (normalized === WSTETH) {
        return config.wstEthBalance;
      }
      return 0n;
    },
    async getAllowance() {
      return state.allowance;
    },
    async quoteSendTransaction(tx) {
      const isApprove = String(tx?.to || "").toLowerCase() === STETH;
      return { fee: isApprove ? config.approvalFee : config.operationFee };
    },
    async approve({ amount }) {
      state.allowance = BigInt(amount);
      state.approveCalls.push(String(amount));
      return {
        hash: `0x${String(state.approveCalls.length).padStart(64, "a")}`,
        fee: config.approvalFee,
      };
    },
    async sendTransaction(tx) {
      state.sendCalls.push({
        to: String(tx?.to || "").toLowerCase(),
        value: BigInt(tx?.value || 0).toString(),
        data: String(tx?.data || ""),
        gasLimit: BigInt(tx?.gasLimit || 0).toString(),
      });
      return {
        hash: `0x${String(state.sendCalls.length).padStart(64, "b")}`,
        fee: config.operationFee,
      };
    },
  };

  WalletManagerEvm.prototype.getAccount = async function getAccount() {
    return fakeAccount;
  };
  WalletManagerEvm.prototype.dispose = function dispose() {};
  globalThis.fetch = async function fetch(url, options = {}) {
    const normalizedUrl = String(url || "");
    if (normalizedUrl === "https://eth-api.lido.fi/v1/protocol/steth/apr/last") {
      return new Response(
        JSON.stringify({
          data: {
            timeUnix: 1776687767,
            apr: 2.829,
          },
          meta: {
            symbol: "stETH",
            address: STETH,
            chainId: 1,
          },
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        }
      );
    }
    if (normalizedUrl === "https://eth-api.lido.fi/v1/protocol/steth/apr/sma") {
      return new Response(
        JSON.stringify({
          data: {
            aprs: [
              { timeUnix: 1776687767, apr: 2.829 },
              { timeUnix: 1776860531, apr: 2.586 },
            ],
            smaApr: 2.54475,
          },
          meta: {
            symbol: "stETH",
            address: STETH,
            chainId: 1,
          },
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        }
      );
    }
    const payload = JSON.parse(String(options.body || "{}"));
    const result = await fakeProvider.request({
      method: payload.method,
      params: payload.params,
    });
    return new Response(
      JSON.stringify({
        jsonrpc: "2.0",
        id: payload.id ?? 1,
        result,
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      }
    );
  };

  const service = new WdkEvmWalletService({
    network: "ethereum",
    networkProfiles: {
      ethereum: {
        chainId: 1,
        providerUrl: "http://fake-rpc.local",
        nativeSymbol: "ETH",
      },
    },
    transferMaxFeeWei: null,
    lidoReferralAddress: "",
  });

  return {
    service,
    state,
    restore() {
      WalletManagerEvm.prototype.getAccount = originals.getAccount;
      WalletManagerEvm.prototype.dispose = originals.disposeWallet;
      globalThis.fetch = originals.fetch;
    },
  };
}

test("lido overview exposes contracts and sample rates", async () => {
  const harness = createHarness();
  try {
    const result = await harness.service.getLidoOverview({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
    });
    assert.equal(result.protocol, "lido");
    assert.equal(result.preferredPositionToken, "wstETH");
    assert.equal(result.contracts.wstETH.toLowerCase(), WSTETH);
    assert.equal(result.sampleRates.wstEthPerStEthRaw, "950000000000000000");
    assert.equal(result.sampleRates.stEthPerWstEthRaw, "1100000000000000000");
    assert.equal(result.stakingApr.lastApr, 2.829);
    assert.equal(result.stakingApr.smaApr, 2.54475);
  } finally {
    harness.restore();
  }
});

test("lido positions expose steth and wsteth balances", async () => {
  const harness = createHarness();
  try {
    const result = await harness.service.getLidoPositions({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
    });
    assert.equal(result.protocol, "lido");
    assert.equal(result.positionCount, 2);
    assert.equal(result.positions[0].asset, "stETH");
    assert.equal(result.positions[1].asset, "wstETH");
    assert.equal(result.stEthEquivalentTotalRaw, "3100000000000000000");
  } finally {
    harness.restore();
  }
});

test("lido wrap preview requires approval when allowance is missing", async () => {
  const harness = createHarness({ initialAllowance: 0n });
  try {
    const result = await harness.service.quoteLidoOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "wrap_steth",
      amount: "1000000000000000000",
    });
    assert.equal(result.operation, "wrap_steth");
    assert.equal(result.expectedOutputAmountRaw, "950000000000000000");
    assert.equal(result.allowance.approvalRequired, true);
  } finally {
    harness.restore();
  }
});

test("lido wrap send performs approval and sends transaction", async () => {
  const harness = createHarness({ initialAllowance: 0n });
  try {
    const preview = await harness.service.quoteLidoOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "wrap_steth",
      amount: "1000000000000000000",
    });
    const result = await harness.service.sendLidoOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "wrap_steth",
      amount: "1000000000000000000",
      expectedQuoteFingerprint: preview.quoteFingerprint,
    });
    assert.equal(harness.state.approveCalls.length, 1);
    assert.equal(harness.state.sendCalls.length, 1);
    assert.equal(result.result.approveHash.startsWith("0x"), true);
    assert.equal(result.result.hash.startsWith("0x"), true);
    assert.equal(harness.state.sendCalls[0].gasLimit, "130");
    assert.equal(result.confirmed, true);
  } finally {
    harness.restore();
  }
});

test("lido stake preview and send use payable referral staker transaction", async () => {
  const harness = createHarness();
  try {
    const preview = await harness.service.quoteLidoOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "stake_eth_for_wsteth",
      amount: "1000000000000000000",
    });
    assert.equal(preview.expectedOutputAmountRaw, "950000000000000000");
    assert.equal(preview.allowance.approvalRequired, false);

    await harness.service.sendLidoOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "stake_eth_for_wsteth",
      amount: "1000000000000000000",
      expectedQuoteFingerprint: preview.quoteFingerprint,
    });
    assert.equal(harness.state.sendCalls.length, 1);
    assert.equal(harness.state.sendCalls[0].to, REFERRAL_STAKER);
    assert.equal(harness.state.sendCalls[0].value, "1000000000000000000");
  } finally {
    harness.restore();
  }
});

test("lido withdrawal requests expose queue status", async () => {
  const harness = createHarness();
  try {
    const result = await harness.service.getLidoWithdrawalRequests({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
    });
    assert.equal(result.requestCount, 2);
    assert.equal(result.claimableCount, 1);
    assert.equal(result.requests[0].requestId, "101");
    assert.equal(result.requests[1].claimable, true);
  } finally {
    harness.restore();
  }
});

test("lido withdrawal request preview requires approval and send performs it", async () => {
  const harness = createHarness({ initialAllowance: 0n });
  try {
    const preview = await harness.service.quoteLidoWithdrawalOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "request_withdrawal_steth",
      amount: "1000000000000000000",
    });
    assert.equal(preview.operation, "request_withdrawal_steth");
    assert.equal(preview.allowance.approvalRequired, true);
    assert.equal(preview.queuedStEthAmountRaw, "1000000000000000000");

    const result = await harness.service.sendLidoWithdrawalOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "request_withdrawal_steth",
      amount: "1000000000000000000",
      expectedQuoteFingerprint: preview.quoteFingerprint,
    });
    assert.equal(harness.state.approveCalls.length, 1);
    assert.equal(harness.state.sendCalls.length, 1);
    assert.equal(harness.state.sendCalls[0].to, WITHDRAWAL_QUEUE);
    assert.equal(result.result.approveHash.startsWith("0x"), true);
  } finally {
    harness.restore();
  }
});

test("lido claim preview and send use withdrawal queue transaction without approval", async () => {
  const harness = createHarness();
  try {
    const preview = await harness.service.quoteLidoWithdrawalOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "claim_withdrawal",
      requestId: "102",
    });
    assert.equal(preview.operation, "claim_withdrawal");
    assert.equal(preview.allowance.approvalRequired, false);
    assert.equal(preview.withdrawalRequest.requestId, "102");
    assert.equal(preview.withdrawalRequest.claimable, true);

    const result = await harness.service.sendLidoWithdrawalOperation({
      seedPhrase: VALID_MNEMONIC,
      accountIndex: 0,
      network: "ethereum",
      operation: "claim_withdrawal",
      requestId: "102",
      expectedQuoteFingerprint: preview.quoteFingerprint,
    });
    assert.equal(harness.state.approveCalls.length, 0);
    assert.equal(harness.state.sendCalls.length, 1);
    assert.equal(harness.state.sendCalls[0].to, WITHDRAWAL_QUEUE);
    assert.equal(result.result.approveHash, undefined);
  } finally {
    harness.restore();
  }
});
