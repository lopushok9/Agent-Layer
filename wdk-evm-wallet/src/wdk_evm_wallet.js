import crypto from "node:crypto";

import { Contract } from "ethers";
import WDK from "@tetherto/wdk";
import { AaveV3Base, AaveV3Ethereum } from "@bgd-labs/aave-address-book";
import AaveProtocolEvm from "@tetherto/wdk-protocol-lending-aave-evm";
import VeloraProtocolEvm from "@tetherto/wdk-protocol-swap-velora-evm";
import WalletManagerEvm, { WalletAccountReadOnlyEvm } from "@tetherto/wdk-wallet-evm";

const ERC20_NAME_SELECTOR = "0x06fdde03";
const ERC20_SYMBOL_SELECTOR = "0x95d89b41";
const ERC20_DECIMALS_SELECTOR = "0x313ce567";
const ERC20_BALANCE_OF_SELECTOR = "0x70a08231";
const ERC20_APPROVE_SELECTOR = "0x095ea7b3";
const USDT_MAINNET_ADDRESS = "0xdac17f958d2ee523a2206206994597c13d831ec7";
const ZERO_ADDRESS = "0x0000000000000000000000000000000000000000";
const VELORA_NATIVE_TOKEN_ADDRESS = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
const LIFI_SOLANA_NATIVE_TOKEN_ADDRESS = "11111111111111111111111111111111";
const DEFAULT_SWAP_SLIPPAGE_BPS = 100;
const DEFAULT_LIFI_SLIPPAGE = 0.005;
const ALWAYS_DENIED_LIFI_BRIDGES = ["mayan"];
const AAVE_RAY = 10n ** 27n;
const AAVE_PROTOCOL_DATA_PROVIDER_BY_NETWORK = {
  ethereum: AaveV3Ethereum.AAVE_PROTOCOL_DATA_PROVIDER,
  base: AaveV3Base.AAVE_PROTOCOL_DATA_PROVIDER,
};
const AAVE_PROTOCOL_DATA_PROVIDER_ABI = [
  "function getUserReserveData(address asset, address user) view returns (uint256 currentATokenBalance, uint256 currentStableDebt, uint256 currentVariableDebt, uint256 principalStableDebt, uint256 scaledVariableDebt, uint256 stableBorrowRate, uint256 liquidityRate, uint40 stableRateLastUpdated, bool usageAsCollateralEnabled)",
];
const LIFI_CHAIN_IDS_BY_NETWORK = {
  ethereum: "1",
  base: "8453",
};
const LIFI_CHAIN_ALIASES = {
  eth: "1",
  ethereum: "1",
  mainnet: "1",
  "eth-mainnet": "1",
  base: "8453",
  "base-mainnet": "8453",
  sol: "1151111081099710",
  solana: "1151111081099710",
};

function createTaggedError(message, code, details = {}) {
  const error = new Error(message);
  if (typeof code === "string" && code.trim()) {
    error.errorCode = code.trim();
  }
  if (details && typeof details === "object" && !Array.isArray(details)) {
    error.errorDetails = details;
  }
  return error;
}

function assertNonEmptyString(value, fieldName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${fieldName} is required.`);
  }
  return value.trim();
}

function assertValidSeedPhrase(seedPhrase) {
  const mnemonic = assertNonEmptyString(seedPhrase, "seedPhrase");
  if (!WDK.isValidSeed(mnemonic)) {
    throw new Error("seedPhrase must be a valid BIP-39 seed phrase.");
  }
  return mnemonic;
}

function assertValidNetwork(network, fieldName = "network") {
  if (network === undefined || network === null || network === "") {
    return null;
  }
  const normalized = String(network).trim().toLowerCase();
  const aliases = {
    mainnet: "ethereum",
    eth: "ethereum",
    "base-mainnet": "base",
    base_sepolia: "base-sepolia",
  };
  const effective = aliases[normalized] || normalized;
  if (!["ethereum", "sepolia", "base", "base-sepolia"].includes(effective)) {
    throw new Error(`${fieldName} must be one of: ethereum, sepolia, base, base-sepolia.`);
  }
  return effective;
}

function assertNonNegativeInteger(value, fieldName) {
  if (typeof value === "boolean") {
    throw new Error(`${fieldName} must be a non-negative integer.`);
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${fieldName} must be a non-negative integer.`);
  }
  return parsed;
}

function assertPositiveBigIntString(value, fieldName) {
  const normalized = String(value ?? "").trim();
  if (!/^[0-9]+$/.test(normalized)) {
    throw new Error(`${fieldName} must be a positive base-10 integer string.`);
  }
  const parsed = BigInt(normalized);
  if (parsed <= 0n) {
    throw new Error(`${fieldName} must be greater than zero.`);
  }
  return parsed;
}

function normalizeAddress(value, fieldName) {
  const address = assertNonEmptyString(value, fieldName);
  if (!/^0x[a-fA-F0-9]{40}$/.test(address)) {
    throw new Error(`${fieldName} must be a valid 20-byte hex address.`);
  }
  if (address.toLowerCase() === "0x0000000000000000000000000000000000000000") {
    throw new Error(`${fieldName} must not be the zero address.`);
  }
  return address;
}

function assertDistinctAddresses(left, leftName, right, rightName) {
  if (left.toLowerCase() === right.toLowerCase()) {
    throw new Error(`${leftName} and ${rightName} must be different addresses.`);
  }
}

function assertVeloraSupportedNetwork(network) {
  if (!["ethereum", "base"].includes(network)) {
    throw new Error(
      "Velora swap quotes are currently supported only on ethereum and base mainnet."
    );
  }
}

function assertLifiSupportedNetwork(network) {
  if (!Object.hasOwn(LIFI_CHAIN_IDS_BY_NETWORK, network)) {
    throw new Error(
      "LI.FI EVM-origin swaps are currently supported only on ethereum and base mainnet."
    );
  }
}

function assertAaveSupportedNetwork(network) {
  if (!["ethereum", "base"].includes(network)) {
    throw new Error("Aave V3 is currently supported only on ethereum and base mainnet.");
  }
}

function normalizeAaveOperation(value) {
  const operation = assertNonEmptyString(value, "operation").toLowerCase();
  if (!["supply", "withdraw", "borrow", "repay"].includes(operation)) {
    throw new Error("operation must be one of: supply, withdraw, borrow, repay.");
  }
  return operation;
}

function isVeloraNativeTokenAddress(value) {
  return String(value || "").trim().toLowerCase() === VELORA_NATIVE_TOKEN_ADDRESS;
}

function isZeroAddress(value) {
  return String(value || "").trim().toLowerCase() === ZERO_ADDRESS;
}

function normalizeEvmTokenAddressAllowingNative(value, fieldName) {
  const raw = assertNonEmptyString(value, fieldName);
  const alias = raw.toLowerCase();
  const address = alias === "native" || alias === "eth" ? ZERO_ADDRESS : raw;
  if (isZeroAddress(address)) {
    return ZERO_ADDRESS;
  }
  return normalizeAddress(address, fieldName).toLowerCase();
}

function normalizeLifiOutputTokenAddress(value, destinationChainId, fieldName) {
  const raw = assertNonEmptyString(value, fieldName);
  const alias = raw.toLowerCase();
  if (["1", "8453"].includes(destinationChainId)) {
    return normalizeEvmTokenAddressAllowingNative(raw, fieldName);
  }
  if (destinationChainId === "1151111081099710" && ["native", "sol", "solana"].includes(alias)) {
    return LIFI_SOLANA_NATIVE_TOKEN_ADDRESS;
  }
  return raw;
}

function normalizeLifiChainId(value, fieldName) {
  const normalized = assertNonEmptyString(value, fieldName).toLowerCase();
  const effective = LIFI_CHAIN_ALIASES[normalized] || normalized;
  if (!["1", "8453", "1151111081099710"].includes(effective)) {
    throw new Error(`${fieldName} must be one of: ethereum, base, solana, 1, 8453, 1151111081099710.`);
  }
  return effective;
}

function parseLifiSlippage(value, fallback = DEFAULT_LIFI_SLIPPAGE) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  if (typeof value === "boolean") {
    throw new Error("slippage must be a number between 0 and 1.");
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
    throw new Error("slippage must be a number between 0 and 1.");
  }
  return parsed;
}

function normalizeBridgeList(value, fieldName) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  if (typeof value === "string") {
    const items = value.split(",").map((item) => item.trim()).filter(Boolean);
    return items.length > 0 ? items.join(",") : null;
  }
  if (Array.isArray(value)) {
    const items = value.map((item) => assertNonEmptyString(item, fieldName));
    return items.length > 0 ? items.join(",") : null;
  }
  throw new Error(`${fieldName} must be a string or array of strings.`);
}

function mergeBridgeLists(...values) {
  const items = [];
  for (const value of values) {
    const normalized = normalizeBridgeList(value, "denyBridges");
    if (!normalized) {
      continue;
    }
    for (const item of normalized.split(",")) {
      const bridge = item.trim();
      if (bridge && !items.some((existing) => existing.toLowerCase() === bridge.toLowerCase())) {
        items.push(bridge);
      }
    }
  }
  return items.length > 0 ? items.join(",") : null;
}

function buildSwapRequest({ tokenIn, tokenOut, tokenInAmount }) {
  const swapRequest = {
    tokenIn: normalizeAddress(tokenIn, "tokenIn"),
    tokenOut: normalizeAddress(tokenOut, "tokenOut"),
    tokenInAmount: assertPositiveBigIntString(tokenInAmount, "tokenInAmount"),
  };
  assertDistinctAddresses(swapRequest.tokenIn, "tokenIn", swapRequest.tokenOut, "tokenOut");
  return swapRequest;
}

function buildLifiEvmSwapRequest({
  tokenIn,
  destinationChain,
  outputToken,
  destinationAddress,
  tokenInAmount,
  slippage,
  allowBridges,
  denyBridges,
  preferBridges,
}) {
  const destinationChainId = normalizeLifiChainId(destinationChain, "destinationChain");
  return {
    tokenIn: normalizeEvmTokenAddressAllowingNative(tokenIn, "tokenIn"),
    destinationChainId,
    outputToken: normalizeLifiOutputTokenAddress(outputToken, destinationChainId, "outputToken"),
    destinationAddress: assertNonEmptyString(destinationAddress, "destinationAddress"),
    tokenInAmount: assertPositiveBigIntString(tokenInAmount, "tokenInAmount"),
    slippage: parseLifiSlippage(slippage),
    allowBridges: normalizeBridgeList(allowBridges, "allowBridges"),
    denyBridges: normalizeBridgeList(denyBridges, "denyBridges"),
    preferBridges: normalizeBridgeList(preferBridges, "preferBridges"),
  };
}

function buildAaveOperationRequest({ operation, token, tokenAddress, amount, onBehalfOf, to }) {
  if (onBehalfOf !== undefined && onBehalfOf !== null && String(onBehalfOf).trim()) {
    throw new Error("Aave delegated onBehalfOf operations are not exposed by this local wallet runtime.");
  }
  if (to !== undefined && to !== null && String(to).trim()) {
    throw new Error("Aave third-party withdraw destinations are not exposed by this local wallet runtime.");
  }
  const preferredToken = tokenAddress ?? token;
  if (tokenAddress && token && String(tokenAddress).toLowerCase() !== String(token).toLowerCase()) {
    throw new Error("tokenAddress and token must refer to the same address.");
  }
  return {
    operation: normalizeAaveOperation(operation),
    token: normalizeAddress(preferredToken, "tokenAddress"),
    amount: assertPositiveBigIntString(amount, "amount"),
  };
}

function parseOptionalDecimalBigInt(value) {
  const normalized = String(value ?? "").trim();
  if (!/^[0-9]+$/.test(normalized)) {
    return null;
  }
  return BigInt(normalized);
}

function parseOptionalHexOrDecimalBigInt(value) {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return null;
  }
  if (/^0x[0-9a-fA-F]+$/.test(normalized) || /^[0-9]+$/.test(normalized)) {
    return BigInt(normalized);
  }
  return null;
}

function computeMinimumOutputAmount(destAmount, slippageBps) {
  const amount = BigInt(destAmount);
  const bps = BigInt(slippageBps);
  if (bps <= 0n) {
    return amount;
  }
  return (amount * (10000n - bps)) / 10000n;
}

function assertValidHash(value, fieldName) {
  const hash = assertNonEmptyString(value, fieldName);
  if (!/^0x[a-fA-F0-9]{64}$/.test(hash)) {
    throw new Error(`${fieldName} must be a valid 32-byte transaction hash.`);
  }
  return hash;
}

function stripHexPrefix(value) {
  return String(value || "").startsWith("0x") ? String(value).slice(2) : String(value || "");
}

function toRpcHex(value) {
  const numeric = BigInt(value || 0);
  return `0x${numeric.toString(16)}`;
}

function parseHexOrDecimalBigInt(value, fieldName) {
  const normalized = String(value ?? "0").trim();
  if (/^0x[0-9a-fA-F]+$/.test(normalized)) {
    return BigInt(normalized);
  }
  if (/^[0-9]+$/.test(normalized)) {
    return BigInt(normalized);
  }
  throw new Error(`${fieldName} must be a hex or base-10 integer string.`);
}

function leftPadHex(value, length = 64) {
  return stripHexPrefix(value).toLowerCase().padStart(length, "0");
}

function buildBalanceOfCallData(owner) {
  return `${ERC20_BALANCE_OF_SELECTOR}${leftPadHex(normalizeAddress(owner, "owner"))}`;
}

function sha256Hex(value) {
  return crypto.createHash("sha256").update(String(value || ""), "utf8").digest("hex");
}

function normalizeErrorCodeValue(error) {
  if (!error || typeof error !== "object") {
    return "";
  }
  return String(error.errorCode || error.code || "").trim().toLowerCase();
}

function decodeUint256Result(value, fieldName) {
  const hex = stripHexPrefix(value);
  if (!hex || !/^[0-9a-fA-F]+$/.test(hex)) {
    throw new Error(`${fieldName} returned invalid hex data.`);
  }
  return BigInt(`0x${hex}`);
}

function decodeAbiStringResult(value, fieldName) {
  const hex = stripHexPrefix(value);
  if (!hex || !/^[0-9a-fA-F]+$/.test(hex) || hex.length % 2 !== 0) {
    throw new Error(`${fieldName} returned invalid hex data.`);
  }
  if (hex.length === 64) {
    const buffer = Buffer.from(hex, "hex");
    const end = buffer.indexOf(0);
    return buffer.slice(0, end >= 0 ? end : undefined).toString("utf8");
  }
  if (hex.length < 128) {
    throw new Error(`${fieldName} returned an unsupported ABI payload.`);
  }
  const offset = Number(decodeUint256Result(`0x${hex.slice(0, 64)}`, fieldName));
  const offsetHexIndex = offset * 2;
  const lengthIndex = offsetHexIndex + 64;
  if (offsetHexIndex + 64 > hex.length || lengthIndex > hex.length) {
    throw new Error(`${fieldName} returned a truncated ABI payload.`);
  }
  const byteLength = Number(
    decodeUint256Result(`0x${hex.slice(offsetHexIndex, offsetHexIndex + 64)}`, fieldName)
  );
  const dataStart = offsetHexIndex + 64;
  const dataEnd = dataStart + byteLength * 2;
  if (dataEnd > hex.length) {
    throw new Error(`${fieldName} returned a truncated ABI string payload.`);
  }
  return Buffer.from(hex.slice(dataStart, dataEnd), "hex").toString("utf8");
}

function formatUnits(value, decimals = 18) {
  const sign = value < 0n ? "-" : "";
  const absolute = value < 0n ? value * -1n : value;
  const base = 10n ** BigInt(decimals);
  const whole = absolute / base;
  const fraction = absolute % base;
  if (fraction === 0n) {
    return `${sign}${whole.toString()}`;
  }
  const fractionText = fraction.toString().padStart(decimals, "0").replace(/0+$/, "");
  return `${sign}${whole.toString()}.${fractionText}`;
}

function rayMul(value, rayValue) {
  return (BigInt(value || 0) * BigInt(rayValue || 0)) / AAVE_RAY;
}

function formatBasisPoints(value) {
  return formatUnits(BigInt(value || 0), 2);
}

function formatRayAprPercent(value) {
  return formatUnits(BigInt(value || 0), 25);
}

function computeAaveUsdPriceRaw(priceInMarketReferenceCurrency, baseCurrencyInfo) {
  const marketReferenceCurrencyUnit = BigInt(baseCurrencyInfo?.marketReferenceCurrencyUnit || 0);
  const marketReferenceCurrencyPriceInUsd = BigInt(baseCurrencyInfo?.marketReferenceCurrencyPriceInUsd || 0);
  if (marketReferenceCurrencyUnit <= 0n || marketReferenceCurrencyPriceInUsd <= 0n) {
    return null;
  }
  return (
    (BigInt(priceInMarketReferenceCurrency || 0) * marketReferenceCurrencyPriceInUsd) /
    marketReferenceCurrencyUnit
  );
}

function computeAaveUsdValueRaw(amountRaw, decimals, priceUsdRaw) {
  if (priceUsdRaw === null || priceUsdRaw === undefined) {
    return null;
  }
  const scale = 10n ** BigInt(Number.isInteger(decimals) ? decimals : 18);
  if (scale <= 0n) {
    return null;
  }
  return (BigInt(amountRaw || 0) * BigInt(priceUsdRaw)) / scale;
}

async function rpcRequest(providerUrl, method, params = []) {
  let response;
  try {
    response = await fetch(providerUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method,
        params,
      }),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw createTaggedError(`RPC network unavailable: ${message}`, "network_unavailable", {
      providerUrl,
      rpcMethod: method,
    });
  }
  if (!response.ok) {
    throw createTaggedError(`RPC request failed with HTTP ${response.status}.`, "network_unavailable", {
      providerUrl,
      rpcMethod: method,
      httpStatus: response.status,
    });
  }
  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw createTaggedError(`RPC returned invalid JSON: ${message}`, "network_unavailable", {
      providerUrl,
      rpcMethod: method,
    });
  }
  if (payload?.error) {
    const rpcMessage = payload.error.message || `RPC ${method} failed.`;
    const error = new Error(rpcMessage);
    if (payload.error.code !== undefined && payload.error.code !== null) {
      error.code = String(payload.error.code);
    }
    error.errorDetails = {
      providerUrl,
      rpcMethod: method,
      rpcCode: payload.error.code,
    };
    throw error;
  }
  return payload.result;
}

async function ethCall(providerUrl, to, data) {
  return rpcRequest(providerUrl, "eth_call", [{ to, data }, "latest"]);
}

function buildErc20ApproveTransaction(tokenAddress, spender, amount) {
  return {
    to: normalizeAddress(tokenAddress, "tokenAddress"),
    value: 0n,
    data: `${ERC20_APPROVE_SELECTOR}${leftPadHex(
      normalizeAddress(spender, "spender")
    )}${leftPadHex(BigInt(amount).toString(16))}`,
  };
}

function isRecoverableSwapFeeEstimateFailure(error) {
  const code = normalizeErrorCodeValue(error);
  const message = error instanceof Error ? error.message : String(error || "");
  const lower = message.toLowerCase();
  if (
    code === "insufficient_funds" ||
    code === "call_exception" ||
    code === "execution_reverted" ||
    code === "bad_data"
  ) {
    return true;
  }
  return (
    lower.includes("execution reverted") ||
    lower.includes("insufficient funds") ||
    lower.includes("estimategas") ||
    lower.includes("missing revert data") ||
    lower.includes("call_exception")
  );
}

function parseInsufficientFundsHint(error) {
  const message = error instanceof Error ? error.message : String(error || "");
  const match = message.match(/have\s+([0-9]+)\s+want\s+([0-9]+)/i);
  if (!match) {
    return null;
  }
  const available = BigInt(match[1]);
  const required = BigInt(match[2]);
  return {
    availableNativeBalanceWei: available.toString(),
    requiredNativeBalanceWei: required.toString(),
    missingNativeBalanceWei: (required > available ? required - available : 0n).toString(),
  };
}

function isRecoverableAllowanceReadFailure(error) {
  const code = normalizeErrorCodeValue(error);
  const message = error instanceof Error ? error.message : String(error || "");
  const lower = message.toLowerCase();
  if (code === "bad_data" || code === "call_exception" || code === "buffer_overrun") {
    return true;
  }
  return (
    lower.includes("could not decode result data") ||
    lower.includes("allowance(address,address)") ||
    lower.includes('value="0x"') ||
    lower.includes("bad data") ||
    lower.includes("buffer overrun")
  );
}

function isRecoverableTokenBalanceReadFailure(error) {
  const code = normalizeErrorCodeValue(error);
  const message = error instanceof Error ? error.message : String(error || "");
  const lower = message.toLowerCase();
  if (code === "bad_data" || code === "call_exception" || code === "buffer_overrun") {
    return true;
  }
  return (
    lower.includes("missing revert data") ||
    lower.includes("could not decode result data") ||
    lower.includes("balanceof(address)") ||
    lower.includes('value="0x"') ||
    lower.includes("bad data") ||
    lower.includes("buffer overrun")
  );
}

function isRecoverableTokenTransferSimulationFailure(error) {
  const code = normalizeErrorCodeValue(error);
  const message = error instanceof Error ? error.message : String(error || "");
  const lower = message.toLowerCase();
  if (code === "insufficient_funds" || lower.includes("insufficient funds")) {
    return false;
  }
  if (code === "bad_data" || code === "call_exception" || code === "execution_reverted") {
    return true;
  }
  return (
    lower.includes("missing revert data") ||
    lower.includes("execution reverted") ||
    lower.includes("call exception") ||
    lower.includes("call_exception") ||
    lower.includes("could not decode result data")
  );
}

async function maybeDispose(value) {
  if (value && typeof value.dispose === "function") {
    await value.dispose();
  }
  if (value && typeof value.close === "function") {
    await value.close();
  }
}

export class WdkEvmWalletService {
  constructor(config) {
    this.config = config;
    this._tokenMetadataCache = new Map();
  }

  generateSeedPhrase(words = 12) {
    const count = Number(words);
    if (!Number.isInteger(count) || count !== 12) {
      throw new Error(
        "Only 12-word seed phrase generation is exposed by this service because that is the documented WDK helper surface."
      );
    }
    return {
      seedPhrase: WDK.getRandomSeedPhrase(),
      wordCount: count,
      source: "wdk",
    };
  }

  async resolveAddress({ seedPhrase, accountIndex = 0, network }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => ({
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      accountIndex,
      address: await account.getAddress(),
      source: "wdk-wallet-evm",
    }));
  }

  async getBalance({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        const address = await account.getAddress();
        const balance = await account.getBalance();
        return {
          network: runtimeConfig.network,
          chainId: runtimeConfig.chainId,
          nativeSymbol: runtimeConfig.nativeSymbol,
          accountIndex,
          address,
          balance,
          balanceFormatted: formatUnits(BigInt(balance), 18),
          source: "wdk-wallet-evm",
        };
      }
    );
  }

  async getTokenBalance({ seedPhrase, address, tokenAddress, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        const address = await account.getAddress();
        const token = normalizeAddress(tokenAddress, "tokenAddress");
        const balance = await this.#readTokenBalanceWithFallback({
          account,
          runtimeConfig,
          tokenAddress: token,
          ownerAddress: address,
        });
        const tokenMetadata = await this.#getBestEffortTokenMetadata(runtimeConfig, token);
        return {
          network: runtimeConfig.network,
          chainId: runtimeConfig.chainId,
          accountIndex,
          address,
          tokenAddress: token,
          balance,
          balanceFormatted:
            tokenMetadata && Number.isInteger(tokenMetadata.decimals)
              ? formatUnits(BigInt(balance), tokenMetadata.decimals)
              : null,
          tokenMetadata,
          source: "wdk-wallet-evm",
        };
      }
    );
  }

  async getTokenMetadata({ tokenAddress, network }) {
    const runtimeConfig = this.#resolveRuntimeConfig(network);
    const token = normalizeAddress(tokenAddress, "tokenAddress");
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      tokenAddress: token,
      tokenMetadata: await this.#getTokenMetadata(runtimeConfig, token),
      source: "erc20-rpc",
    };
  }

  async getFeeRates({ network } = {}) {
    const runtimeConfig = this.#resolveRuntimeConfig(network);
    const gasPriceHex = await rpcRequest(runtimeConfig.providerUrl, "eth_gasPrice", []);
    const priorityHex = await rpcRequest(
      runtimeConfig.providerUrl,
      "eth_maxPriorityFeePerGas",
      []
    );
    const feeHistory = await rpcRequest(
      runtimeConfig.providerUrl,
      "eth_feeHistory",
      ["0x1", "latest", []]
    );
    const baseFeeItems = Array.isArray(feeHistory?.baseFeePerGas) ? feeHistory.baseFeePerGas : [];
    const latestBaseFeeHex = baseFeeItems.length ? baseFeeItems[baseFeeItems.length - 1] : "0x0";
    const baseFeePerGas = BigInt(latestBaseFeeHex);
    const priorityFeePerGas = BigInt(priorityHex || "0x0");
    const gasPrice = BigInt(gasPriceHex || "0x0");
    const normalMaxFeePerGas = baseFeePerGas + priorityFeePerGas;
    const fastMaxFeePerGas = baseFeePerGas * 2n + priorityFeePerGas;
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      gasPrice,
      feeRates: {
        slow: gasPrice,
        normal: normalMaxFeePerGas,
        fast: fastMaxFeePerGas,
        baseFeePerGas,
        maxPriorityFeePerGas: priorityFeePerGas,
      },
      source: "rpc",
    };
  }

  async getTransactionReceipt({ txHash, network }) {
    const runtimeConfig = this.#resolveRuntimeConfig(network);
    const receipt = await rpcRequest(
      runtimeConfig.providerUrl,
      "eth_getTransactionReceipt",
      [assertValidHash(txHash, "txHash")]
    );
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      txHash,
      receipt,
      found: receipt !== null,
      source: "rpc",
    };
  }

  async getAaveAccountData({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertAaveSupportedNetwork(runtimeConfig.network);
        const accountAddress = await account.getAddress();
        const protocol = new AaveProtocolEvm(account);
        try {
          const accountData = await protocol.getAccountData(accountAddress);
          return {
            network: runtimeConfig.network,
            chainId: runtimeConfig.chainId,
            accountIndex,
            address: accountAddress,
            protocol: "aave-v3",
            accountData: this.#formatAaveAccountData(accountData),
            source: "wdk-protocol-lending-aave-evm",
          };
        } finally {
          await maybeDispose(protocol);
        }
      }
    );
  }

  async getAaveReserves({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertAaveSupportedNetwork(runtimeConfig.network);
        const protocol = new AaveProtocolEvm(account);
        try {
          const catalog = await this.#readAaveReserveCatalog(protocol);
          return {
            network: runtimeConfig.network,
            chainId: runtimeConfig.chainId,
            accountIndex,
            protocol: "aave-v3",
            pool: catalog.addresses.pool,
            poolAddressesProvider: catalog.addresses.poolAddressesProvider,
            uiPoolDataProvider: catalog.addresses.uiPoolDataProvider,
            priceOracle: catalog.addresses.priceOracle,
            baseCurrencyInfo: catalog.baseCurrencyInfo,
            reserveCount: catalog.reserves.length,
            reserves: catalog.reserves,
            source: "wdk-protocol-lending-aave-evm",
          };
        } finally {
          await maybeDispose(protocol);
        }
      }
    );
  }

  async getAavePositions({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertAaveSupportedNetwork(runtimeConfig.network);
        const accountAddress = await account.getAddress();
        const protocol = new AaveProtocolEvm(account);
        try {
          const catalog = await this.#readAaveReserveCatalog(protocol);
          const poolContract = await protocol._getPoolContract();
          const eModeCategoryIdRaw =
            poolContract && typeof poolContract.getUserEMode === "function"
              ? await poolContract.getUserEMode(accountAddress)
              : 0n;
          const protocolDataProviderContract = this.#getAaveProtocolDataProviderContract(
            runtimeConfig.network,
            protocol
          );
          const accountData = await protocol.getAccountData(accountAddress);
          const userReserveEntries = await Promise.all(
            catalog.reserves.map(async (reserve) => ({
              reserve,
              userReserve: await protocolDataProviderContract.getUserReserveData(
                reserve.underlyingAsset,
                accountAddress
              ),
            }))
          );
          const positions = [];
          for (const { reserve, userReserve } of userReserveEntries) {
            const liquidityIndexRaw = BigInt(reserve?.liquidityIndexRaw || 0);
            const suppliedBalance = BigInt(userReserve?.currentATokenBalance || 0);
            const currentStableDebt = BigInt(userReserve?.currentStableDebt || 0);
            const variableDebt = BigInt(userReserve?.currentVariableDebt || 0);
            const principalStableDebt = BigInt(userReserve?.principalStableDebt || 0);
            const scaledVariableDebt = BigInt(userReserve?.scaledVariableDebt || 0);
            const scaledATokenBalance =
              liquidityIndexRaw > 0n
                ? (suppliedBalance * AAVE_RAY) / liquidityIndexRaw
                : 0n;
            if (
              suppliedBalance <= 0n &&
              variableDebt <= 0n &&
              currentStableDebt <= 0n &&
              principalStableDebt <= 0n &&
              !Boolean(userReserve?.usageAsCollateralEnabled)
            ) {
              continue;
            }
            const suppliedValueUsdRaw = computeAaveUsdValueRaw(
              suppliedBalance,
              reserve.decimals,
              reserve.priceInUsdRaw
            );
            const variableDebtValueUsdRaw = computeAaveUsdValueRaw(
              variableDebt,
              reserve.decimals,
              reserve.priceInUsdRaw
            );
            const currentStableDebtValueUsdRaw = computeAaveUsdValueRaw(
              currentStableDebt,
              reserve.decimals,
              reserve.priceInUsdRaw
            );
            const principalStableDebtValueUsdRaw = computeAaveUsdValueRaw(
              principalStableDebt,
              reserve.decimals,
              reserve.priceInUsdRaw
            );
            positions.push({
              underlyingAsset: reserve.underlyingAsset,
              name: reserve.name,
              symbol: reserve.symbol,
              decimals: reserve.decimals,
              aTokenAddress: reserve.aTokenAddress,
              variableDebtTokenAddress: reserve.variableDebtTokenAddress,
              collateralEnabled: Boolean(userReserve?.usageAsCollateralEnabled),
              suppliedBalanceRaw: suppliedBalance.toString(),
              suppliedBalanceFormatted: formatUnits(suppliedBalance, reserve.decimals),
              suppliedValueUsdRaw: suppliedValueUsdRaw !== null ? suppliedValueUsdRaw.toString() : null,
              suppliedValueUsdFormatted:
                suppliedValueUsdRaw !== null
                  ? formatUnits(suppliedValueUsdRaw, catalog.baseCurrencyInfo.usdDecimals)
                  : null,
              scaledATokenBalanceRaw: scaledATokenBalance.toString(),
              variableDebtRaw: variableDebt.toString(),
              variableDebtFormatted: formatUnits(variableDebt, reserve.decimals),
              variableDebtValueUsdRaw:
                variableDebtValueUsdRaw !== null ? variableDebtValueUsdRaw.toString() : null,
              variableDebtValueUsdFormatted:
                variableDebtValueUsdRaw !== null
                  ? formatUnits(variableDebtValueUsdRaw, catalog.baseCurrencyInfo.usdDecimals)
                  : null,
              scaledVariableDebtRaw: scaledVariableDebt.toString(),
              currentStableDebtRaw: currentStableDebt.toString(),
              currentStableDebtFormatted: formatUnits(currentStableDebt, reserve.decimals),
              currentStableDebtValueUsdRaw:
                currentStableDebtValueUsdRaw !== null ? currentStableDebtValueUsdRaw.toString() : null,
              currentStableDebtValueUsdFormatted:
                currentStableDebtValueUsdRaw !== null
                  ? formatUnits(currentStableDebtValueUsdRaw, catalog.baseCurrencyInfo.usdDecimals)
                  : null,
              principalStableDebtRaw: principalStableDebt.toString(),
              principalStableDebtFormatted: formatUnits(principalStableDebt, reserve.decimals),
              principalStableDebtValueUsdRaw:
                principalStableDebtValueUsdRaw !== null
                  ? principalStableDebtValueUsdRaw.toString()
                  : null,
              principalStableDebtValueUsdFormatted:
                principalStableDebtValueUsdRaw !== null
                  ? formatUnits(principalStableDebtValueUsdRaw, catalog.baseCurrencyInfo.usdDecimals)
                  : null,
              stableBorrowRateRaw: BigInt(userReserve?.stableBorrowRate || 0).toString(),
              stableBorrowAprPercent: formatRayAprPercent(BigInt(userReserve?.stableBorrowRate || 0)),
              stableBorrowLastUpdateTimestamp: BigInt(
                userReserve?.stableRateLastUpdated || 0
              ).toString(),
              reserve: {
                priceInUsdRaw: reserve.priceInUsdRaw !== null ? reserve.priceInUsdRaw.toString() : null,
                priceInUsdFormatted: reserve.priceInUsdFormatted,
                priceInMarketReferenceCurrency: reserve.priceInMarketReferenceCurrency,
                usageAsCollateralEnabled: reserve.usageAsCollateralEnabled,
                borrowingEnabled: reserve.borrowingEnabled,
                isActive: reserve.isActive,
                isFrozen: reserve.isFrozen,
                isPaused: reserve.isPaused,
                flashLoanEnabled: reserve.flashLoanEnabled,
              },
            });
          }
          return {
            network: runtimeConfig.network,
            chainId: runtimeConfig.chainId,
            accountIndex,
            address: accountAddress,
            protocol: "aave-v3",
            eModeCategoryId: BigInt(eModeCategoryIdRaw || 0).toString(),
            accountData: this.#formatAaveAccountData(accountData),
            baseCurrencyInfo: catalog.baseCurrencyInfo,
            positionCount: positions.length,
            positions,
            source: "wdk-protocol-lending-aave-evm",
          };
        } finally {
          await maybeDispose(protocol);
        }
      }
    );
  }

  async quoteAaveOperation({
    seedPhrase,
    address,
    operation,
    token,
    tokenAddress,
    amount,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertAaveSupportedNetwork(runtimeConfig.network);
        const request = buildAaveOperationRequest({
          operation,
          token,
          tokenAddress,
          amount,
        });
        const accountAddress = await account.getAddress();
        const plan = await this.#buildAaveOperationPlan({
          account,
          runtimeConfig,
          address: accountAddress,
          request,
          tolerateOperationFeeFailure: true,
        });
        return this.#formatAaveOperationResponse({
          runtimeConfig,
          accountIndex,
          address: accountAddress,
          request,
          plan,
        });
      }
    );
  }

  async sendAaveOperation({
    seedPhrase,
    operation,
    token,
    tokenAddress,
    amount,
    accountIndex = 0,
    network,
    expectedQuoteFingerprint = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertAaveSupportedNetwork(runtimeConfig.network);
      const request = buildAaveOperationRequest({
        operation,
        token,
        tokenAddress,
        amount,
      });
      const normalizedExpectedQuoteFingerprint =
        typeof expectedQuoteFingerprint === "string" && expectedQuoteFingerprint.trim()
          ? expectedQuoteFingerprint.trim()
          : null;
      const address = await account.getAddress();
      let initialPlan = await this.#buildAaveOperationPlan({
        account,
        runtimeConfig,
        address,
        request,
        tolerateOperationFeeFailure: true,
      });
      this.#assertExpectedAaveFingerprint(
        normalizedExpectedQuoteFingerprint,
        initialPlan.quoteFingerprint
      );

      const approvalExecution = await this.#executeAaveApprovalsIfNeeded({
        account,
        runtimeConfig,
        request,
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (approvalExecution.performed) {
          finalPlan = await this.#buildAaveOperationPlan({
            account,
            runtimeConfig,
            address,
            request,
          });
          this.#assertExpectedAaveFingerprint(
            normalizedExpectedQuoteFingerprint,
            finalPlan.quoteFingerprint
          );
        }

        if (finalPlan.approval.required) {
          throw createTaggedError(
            "Aave operation still requires token approval after the approval step completed.",
            "aave_approval_required",
            {
              spender: finalPlan.spender,
              requiredAllowance: finalPlan.amount.toString(),
              currentAllowance: finalPlan.currentAllowance.toString(),
            }
          );
        }

        if (finalPlan.operationFee === null) {
          throw createTaggedError(
            "Aave operation fee estimate was unavailable. Generate a new quote before sending.",
            "aave_fee_unavailable",
            {
              operation: request.operation,
              feeEstimateError: finalPlan.operationFeeError,
            }
          );
        }

        const protocol = new AaveProtocolEvm(account);
        let result;
        try {
          result = await protocol[request.operation]({
            token: request.token,
            amount: request.amount,
          });
        } finally {
          await maybeDispose(protocol);
        }
        const resultFee = BigInt(result?.fee || 0);
        const totalFee = approvalExecution.totalFee + resultFee;
        return {
          ...this.#formatAaveOperationResponse({
            runtimeConfig,
            accountIndex,
            address,
            request,
            plan: {
              ...finalPlan,
              operationFee: resultFee,
              totalEstimatedFee: totalFee,
              approval: {
                ...finalPlan.approval,
                estimatedFee: approvalExecution.totalFee,
              },
            },
          }),
          result: {
            ...result,
            fee: resultFee.toString(),
            totalFee: totalFee.toString(),
            approvalFee: approvalExecution.totalFee.toString(),
            ...(approvalExecution.approveHash ? { approveHash: approvalExecution.approveHash } : {}),
            ...(approvalExecution.resetAllowanceHash
              ? { resetAllowanceHash: approvalExecution.resetAllowanceHash }
              : {}),
          },
        };
      } catch (error) {
        const cleanup = await this.#restoreAllowanceAfterFailedAaveOperation({
          account,
          runtimeConfig,
          tokenAddress: request.token,
          spender: initialPlan.spender,
          originalAllowance: initialPlan.currentAllowance,
          approvalExecution,
        });
        this.#throwAaveFailureWithCleanup(error, cleanup);
      }
    });
  }

  async quoteSwap({
    seedPhrase,
    address,
    tokenIn,
    tokenOut,
    tokenInAmount,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertVeloraSupportedNetwork(runtimeConfig.network);
        const swapRequest = buildSwapRequest({ tokenIn, tokenOut, tokenInAmount });
        const address = await account.getAddress();
        const readOnlyAccount =
          typeof account.toReadOnlyAccount === "function" ? await account.toReadOnlyAccount() : account;
        try {
          const plan = await this.#buildVeloraSwapPlan({
            account: readOnlyAccount,
            runtimeConfig,
            swapRequest,
            tolerateSwapFeeFailure: true,
          });
          const [tokenInMetadata, tokenOutMetadata] = await Promise.all([
            this.#getSwapTokenMetadata(runtimeConfig, swapRequest.tokenIn, plan.priceRoute?.srcDecimals),
            this.#getSwapTokenMetadata(runtimeConfig, swapRequest.tokenOut, plan.priceRoute?.destDecimals),
          ]);
          const quote = {
            fee: plan.swapFee !== null ? plan.swapFee.toString() : null,
            tokenInAmount: plan.tokenInAmount.toString(),
            tokenOutAmount: plan.tokenOutAmount.toString(),
            priceRoute: plan.priceRoute,
          };
          return {
            network: runtimeConfig.network,
            chainId: runtimeConfig.chainId,
            accountIndex,
            address,
            protocol: "velora",
            executionSupported: true,
            swapRequest,
            tokenInMetadata,
            tokenOutMetadata,
            inputAmountFormatted: formatUnits(swapRequest.tokenInAmount, tokenInMetadata.decimals),
            outputAmountFormatted: formatUnits(plan.tokenOutAmount, tokenOutMetadata.decimals),
            quoteFingerprint: plan.quoteFingerprint,
            estimatedFeeWei:
              plan.totalEstimatedFee !== null ? plan.totalEstimatedFee.toString() : null,
            estimatedSwapFeeWei: plan.swapFee !== null ? plan.swapFee.toString() : null,
            estimatedApprovalFeeWei: plan.approval.estimatedFee.toString(),
            feeEstimateAvailable: plan.swapFee !== null,
            feeEstimateError: plan.swapFeeError,
            slippageBps: plan.slippageBps,
            minimumOutputAmountRaw: plan.minimumTokenOutAmount.toString(),
            allowance: {
              spender: plan.spender,
              currentAllowance: plan.currentAllowance.toString(),
              requiredAllowance: plan.tokenInAmount.toString(),
              approvalRequired: plan.approval.required,
              approvalSequence: plan.approval.steps,
              readError: plan.allowanceReadError,
            },
            router: plan.router,
            simulation: plan.simulation,
            swapTransaction: plan.swapTransaction,
            quote,
            source: "wdk-protocol-swap-velora-evm",
          };
        } finally {
          if (readOnlyAccount !== account) {
            await maybeDispose(readOnlyAccount);
          }
        }
      }
    );
  }

  async quoteLifiSwap({
    seedPhrase,
    address,
    tokenIn,
    destinationChain,
    outputToken,
    destinationAddress,
    tokenInAmount,
    slippage = DEFAULT_LIFI_SLIPPAGE,
    allowBridges = null,
    denyBridges = null,
    preferBridges = null,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertLifiSupportedNetwork(runtimeConfig.network);
        const swapRequest = buildLifiEvmSwapRequest({
          tokenIn,
          destinationChain,
          outputToken,
          destinationAddress,
          tokenInAmount,
          slippage,
          allowBridges,
          denyBridges,
          preferBridges,
        });
        const sourceAddress = await account.getAddress();
        const plan = await this.#buildLifiEvmSwapPlan({
          account,
          runtimeConfig,
          address: sourceAddress,
          swapRequest,
          tolerateSwapFeeFailure: true,
        });
        return this.#formatLifiSwapResponse({
          runtimeConfig,
          accountIndex,
          address: sourceAddress,
          swapRequest,
          plan,
        });
      }
    );
  }

  async swap({
    seedPhrase,
    tokenIn,
    tokenOut,
    tokenInAmount,
    accountIndex = 0,
    network,
    expectedQuoteFingerprint = null,
    minimumTokenOutAmount = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertVeloraSupportedNetwork(runtimeConfig.network);
      const swapRequest = buildSwapRequest({ tokenIn, tokenOut, tokenInAmount });
      const normalizedExpectedQuoteFingerprint =
        typeof expectedQuoteFingerprint === "string" && expectedQuoteFingerprint.trim()
          ? expectedQuoteFingerprint.trim()
          : null;
      const requestedMinimumTokenOutAmount =
        minimumTokenOutAmount !== null && minimumTokenOutAmount !== undefined
          ? assertPositiveBigIntString(minimumTokenOutAmount, "minimumTokenOutAmount")
          : null;
      const address = await account.getAddress();
      let initialPlan = await this.#buildVeloraSwapPlan({
        account,
        runtimeConfig,
        swapRequest,
      });
      const [tokenInMetadata, tokenOutMetadata] = await Promise.all([
        this.#getSwapTokenMetadata(runtimeConfig, swapRequest.tokenIn, initialPlan.priceRoute?.srcDecimals),
        this.#getSwapTokenMetadata(runtimeConfig, swapRequest.tokenOut, initialPlan.priceRoute?.destDecimals),
      ]);
      this.#assertExpectedSwapFingerprint(
        normalizedExpectedQuoteFingerprint,
        initialPlan.quoteFingerprint
      );
      this.#assertMinimumSwapOutput(
        requestedMinimumTokenOutAmount,
        initialPlan.minimumTokenOutAmount,
        initialPlan.tokenOutAmount
      );

      const approvalExecution = await this.#executeSwapApprovalsIfNeeded({
        account,
        runtimeConfig,
        swapRequest,
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (approvalExecution.performed) {
          finalPlan = await this.#buildVeloraSwapPlan({
            account,
            runtimeConfig,
            swapRequest,
          });
          this.#assertExpectedSwapFingerprint(
            normalizedExpectedQuoteFingerprint,
            finalPlan.quoteFingerprint
          );
        }
        this.#assertMinimumSwapOutput(
          requestedMinimumTokenOutAmount,
          finalPlan.minimumTokenOutAmount,
          finalPlan.tokenOutAmount
        );

        const allowanceReadUncertain =
          approvalExecution.performed && finalPlan.allowanceReadError !== null;

        if (finalPlan.approval.required && !allowanceReadUncertain) {
          throw createTaggedError(
            "Swap still requires token approval after the approval step completed.",
            "swap_approval_required",
            {
              spender: finalPlan.spender,
              requiredAllowance: finalPlan.tokenInAmount.toString(),
              currentAllowance: finalPlan.currentAllowance.toString(),
            }
          );
        }

        const effectiveSimulation = allowanceReadUncertain
          ? await this.#simulatePreparedTransaction({
              runtimeConfig,
              from: address,
              tx: finalPlan.swapTx,
            })
          : finalPlan.simulation;
        this.#assertSimulationSucceeded(effectiveSimulation);
        const { hash } = await account.sendTransaction(finalPlan.swapTx);
        const totalFee = approvalExecution.totalFee + finalPlan.swapFee;
        const result = {
          hash,
          fee: totalFee.toString(),
          swapFee: finalPlan.swapFee.toString(),
          approvalFee: approvalExecution.totalFee.toString(),
          tokenInAmount: finalPlan.tokenInAmount.toString(),
          tokenOutAmount: finalPlan.tokenOutAmount.toString(),
          ...(approvalExecution.approveHash ? { approveHash: approvalExecution.approveHash } : {}),
          ...(approvalExecution.resetAllowanceHash
            ? { resetAllowanceHash: approvalExecution.resetAllowanceHash }
            : {}),
        };
        return {
          network: runtimeConfig.network,
          chainId: runtimeConfig.chainId,
          accountIndex,
          address,
          protocol: "velora",
          executionSupported: true,
          swapRequest,
          tokenInMetadata,
          tokenOutMetadata,
          inputAmountFormatted: formatUnits(swapRequest.tokenInAmount, tokenInMetadata.decimals),
          outputAmountFormatted: formatUnits(finalPlan.tokenOutAmount, tokenOutMetadata.decimals),
        quoteFingerprint: finalPlan.quoteFingerprint,
        estimatedFeeWei: totalFee.toString(),
        estimatedSwapFeeWei: finalPlan.swapFee.toString(),
        estimatedApprovalFeeWei: approvalExecution.totalFee.toString(),
        feeEstimateAvailable: true,
        feeEstimateError: null,
        slippageBps: finalPlan.slippageBps,
        minimumOutputAmountRaw: finalPlan.minimumTokenOutAmount.toString(),
        allowance: {
          spender: finalPlan.spender,
          currentAllowance: finalPlan.currentAllowance.toString(),
          requiredAllowance: finalPlan.tokenInAmount.toString(),
          approvalRequired: finalPlan.approval.required,
            approvalSequence: finalPlan.approval.steps,
            readError: finalPlan.allowanceReadError,
          },
          router: finalPlan.router,
          simulation: effectiveSimulation,
          swapTransaction: finalPlan.swapTransaction,
          result,
          source: "wdk-protocol-swap-velora-evm",
        };
      } catch (error) {
        const cleanup = await this.#restoreAllowanceAfterFailedSwap({
          account,
          runtimeConfig,
          tokenAddress: swapRequest.tokenIn,
          spender: initialPlan.spender,
          originalAllowance: initialPlan.currentAllowance,
          approvalExecution,
        });
        this.#throwSwapFailureWithCleanup(error, cleanup);
      }
    });
  }

  async sendLifiSwap({
    seedPhrase,
    tokenIn,
    destinationChain,
    outputToken,
    destinationAddress,
    tokenInAmount,
    slippage = DEFAULT_LIFI_SLIPPAGE,
    allowBridges = null,
    denyBridges = null,
    preferBridges = null,
    accountIndex = 0,
    network,
    minimumTokenOutAmount = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertLifiSupportedNetwork(runtimeConfig.network);
      const swapRequest = buildLifiEvmSwapRequest({
        tokenIn,
        destinationChain,
        outputToken,
        destinationAddress,
        tokenInAmount,
        slippage,
        allowBridges,
        denyBridges,
        preferBridges,
      });
      const requestedMinimumTokenOutAmount =
        minimumTokenOutAmount !== null && minimumTokenOutAmount !== undefined
          ? assertPositiveBigIntString(minimumTokenOutAmount, "minimumTokenOutAmount")
          : null;
      const sourceAddress = await account.getAddress();
      let initialPlan = await this.#buildLifiEvmSwapPlan({
        account,
        runtimeConfig,
        address: sourceAddress,
        swapRequest,
      });
      this.#assertMinimumSwapOutput(
        requestedMinimumTokenOutAmount,
        initialPlan.minimumTokenOutAmount,
        initialPlan.tokenOutAmount
      );

      const approvalExecution = await this.#executeSwapApprovalsIfNeeded({
        account,
        runtimeConfig,
        swapRequest: {
          tokenIn: swapRequest.tokenIn,
        },
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (approvalExecution.performed) {
          finalPlan = await this.#buildLifiEvmSwapPlan({
            account,
            runtimeConfig,
            address: sourceAddress,
            swapRequest,
          });
        }
        this.#assertMinimumSwapOutput(
          requestedMinimumTokenOutAmount,
          finalPlan.minimumTokenOutAmount,
          finalPlan.tokenOutAmount
        );

        const allowanceReadUncertain =
          approvalExecution.performed && finalPlan.allowanceReadError !== null;

        if (finalPlan.approval.required && !allowanceReadUncertain) {
          throw createTaggedError(
            "LI.FI cross-chain swap still requires token approval after the approval step completed.",
            "swap_approval_required",
            {
              spender: finalPlan.spender,
              requiredAllowance: finalPlan.tokenInAmount.toString(),
              currentAllowance: finalPlan.currentAllowance.toString(),
            }
          );
        }

        const effectiveSimulation = allowanceReadUncertain
          ? await this.#simulatePreparedTransaction({
              runtimeConfig,
              from: sourceAddress,
              tx: finalPlan.swapTx,
            })
          : finalPlan.simulation;
        this.#assertSimulationSucceeded(effectiveSimulation);

        const { hash } = await account.sendTransaction(finalPlan.swapTx);
        const totalFee = approvalExecution.totalFee + finalPlan.swapFee;
        const result = {
          hash,
          fee: totalFee.toString(),
          swapFee: finalPlan.swapFee.toString(),
          approvalFee: approvalExecution.totalFee.toString(),
          tokenInAmount: finalPlan.tokenInAmount.toString(),
          tokenOutAmount: finalPlan.tokenOutAmount.toString(),
          ...(approvalExecution.approveHash ? { approveHash: approvalExecution.approveHash } : {}),
          ...(approvalExecution.resetAllowanceHash
            ? { resetAllowanceHash: approvalExecution.resetAllowanceHash }
            : {}),
        };
        return {
          ...this.#formatLifiSwapResponse({
            runtimeConfig,
            accountIndex,
            address: sourceAddress,
            swapRequest,
            plan: {
              ...finalPlan,
              simulation: effectiveSimulation,
              swapFee: totalFee,
              totalEstimatedFee: totalFee,
              approval: {
                ...finalPlan.approval,
                estimatedFee: approvalExecution.totalFee,
              },
            },
          }),
          result,
        };
      } catch (error) {
        const cleanup = await this.#restoreAllowanceAfterFailedSwap({
          account,
          runtimeConfig,
          tokenAddress: swapRequest.tokenIn,
          spender: initialPlan.spender,
          originalAllowance: initialPlan.currentAllowance,
          approvalExecution,
        });
        this.#throwSwapFailureWithCleanup(error, cleanup);
      }
    });
  }

  async quoteNativeTransfer({ seedPhrase, to, value, accountIndex = 0, network }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      const tx = {
        to: normalizeAddress(to, "to"),
        value: assertPositiveBigIntString(value, "value"),
      };
      const quote = await account.quoteSendTransaction(tx);
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        transaction: tx,
        quote,
        source: "wdk-wallet-evm",
      };
    });
  }

  async sendNativeTransfer({ seedPhrase, to, value, accountIndex = 0, network }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      const tx = {
        to: normalizeAddress(to, "to"),
        value: assertPositiveBigIntString(value, "value"),
      };
      const result = await account.sendTransaction(tx);
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        transaction: tx,
        result,
        source: "wdk-wallet-evm",
      };
    });
  }

  async quoteTokenTransfer({
    seedPhrase,
    tokenAddress,
    recipient,
    amount,
    accountIndex = 0,
    network,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      const transfer = {
        token: normalizeAddress(tokenAddress, "tokenAddress"),
        recipient: normalizeAddress(recipient, "recipient"),
        amount: assertPositiveBigIntString(amount, "amount"),
      };
      const ownerAddress = await account.getAddress();
      const { tokenMetadata } = await this.#prepareTokenTransferContext({
        account,
        runtimeConfig,
        transfer,
        ownerAddress,
      });
      let quote;
      try {
        quote = await account.quoteTransfer(transfer);
      } catch (error) {
        if (isRecoverableTokenTransferSimulationFailure(error)) {
          throw createTaggedError(
            "Token transfer could not be simulated by the token contract.",
            "token_transfer_failed",
            {
              network: runtimeConfig.network,
              tokenAddress: transfer.token,
              ownerAddress,
              recipient: transfer.recipient,
              amount: transfer.amount.toString(),
              underlying:
                error instanceof Error
                  ? {
                      message: error.message,
                      code: String(error.errorCode || error.code || "").trim() || null,
                    }
                  : {
                      message: String(error),
                      code: null,
                    },
            }
          );
        }
        throw error;
      }
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        transfer,
        tokenMetadata,
        amountFormatted: formatUnits(transfer.amount, tokenMetadata.decimals),
        quote,
        source: "wdk-wallet-evm",
      };
    });
  }

  async sendTokenTransfer({
    seedPhrase,
    tokenAddress,
    recipient,
    amount,
    accountIndex = 0,
    network,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      const transfer = {
        token: normalizeAddress(tokenAddress, "tokenAddress"),
        recipient: normalizeAddress(recipient, "recipient"),
        amount: assertPositiveBigIntString(amount, "amount"),
      };
      const ownerAddress = await account.getAddress();
      const { tokenMetadata } = await this.#prepareTokenTransferContext({
        account,
        runtimeConfig,
        transfer,
        ownerAddress,
      });
      let result;
      try {
        result = await account.transfer(transfer);
      } catch (error) {
        if (isRecoverableTokenTransferSimulationFailure(error)) {
          throw createTaggedError(
            "Token transfer could not be simulated by the token contract.",
            "token_transfer_failed",
            {
              network: runtimeConfig.network,
              tokenAddress: transfer.token,
              ownerAddress,
              recipient: transfer.recipient,
              amount: transfer.amount.toString(),
              underlying:
                error instanceof Error
                  ? {
                      message: error.message,
                      code: String(error.errorCode || error.code || "").trim() || null,
                    }
                  : {
                      message: String(error),
                      code: null,
                    },
            }
          );
        }
        throw error;
      }
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        transfer,
        tokenMetadata,
        amountFormatted: formatUnits(transfer.amount, tokenMetadata.decimals),
        result,
        source: "wdk-wallet-evm",
      };
    });
  }

  #resolveRuntimeConfig(networkOverride) {
    const network = assertValidNetwork(networkOverride) || this.config.network;
    const profile = this.config.networkProfiles?.[network];
    if (!profile) {
      throw new Error(`Missing RPC profile for network: ${network}`);
    }
    return {
      ...this.config,
      network,
      chainId: profile.chainId,
      providerUrl: profile.providerUrl,
      nativeSymbol: profile.nativeSymbol,
    };
  }

  async #withWallet({ seedPhrase, network }, callback) {
    const mnemonic = assertValidSeedPhrase(seedPhrase);
    const runtimeConfig = this.#resolveRuntimeConfig(network);
    const options = {
      provider: runtimeConfig.providerUrl,
      chainId: runtimeConfig.chainId,
    };
    if (runtimeConfig.transferMaxFeeWei !== null) {
      options.transferMaxFee = runtimeConfig.transferMaxFeeWei;
    }
    const wallet = new WalletManagerEvm(mnemonic, options);
    try {
      return await callback(wallet, runtimeConfig);
    } finally {
      await maybeDispose(wallet);
    }
  }

  async #withAccount({ seedPhrase, accountIndex, network }, callback) {
    return this.#withWallet({ seedPhrase, network }, async (wallet, runtimeConfig) => {
      const account = await wallet.getAccount(assertNonNegativeInteger(accountIndex, "accountIndex"));
      return await callback(account, runtimeConfig);
    });
  }

  async #withReadableAccount({ seedPhrase, address, accountIndex, network }, callback) {
    const normalizedAddress = String(address || "").trim();
    if (normalizedAddress) {
      const runtimeConfig = this.#resolveRuntimeConfig(network);
      const account = new WalletAccountReadOnlyEvm(
        normalizeAddress(normalizedAddress, "address"),
        { provider: runtimeConfig.providerUrl }
      );
      try {
        return await callback(account, runtimeConfig);
      } finally {
        await maybeDispose(account);
      }
    }
    return this.#withAccount({ seedPhrase, accountIndex, network }, callback);
  }

  async #getTokenMetadata(runtimeConfig, tokenAddress) {
    const cacheKey = `${runtimeConfig.network}:${tokenAddress.toLowerCase()}`;
    const cached = this._tokenMetadataCache.get(cacheKey);
    if (cached) {
      return { ...cached };
    }
    const [name, symbol, decimalsRaw] = await Promise.all([
      ethCall(runtimeConfig.providerUrl, tokenAddress, ERC20_NAME_SELECTOR),
      ethCall(runtimeConfig.providerUrl, tokenAddress, ERC20_SYMBOL_SELECTOR),
      ethCall(runtimeConfig.providerUrl, tokenAddress, ERC20_DECIMALS_SELECTOR),
    ]);
    const decimals = Number(decodeUint256Result(decimalsRaw, "decimals"));
    if (!Number.isInteger(decimals) || decimals < 0 || decimals > 255) {
      throw new Error("decimals must be an integer between 0 and 255.");
    }
    const metadata = {
      address: tokenAddress,
      name: decodeAbiStringResult(name, "name"),
      symbol: decodeAbiStringResult(symbol, "symbol"),
      decimals,
      verified: false,
      source: "erc20-rpc",
    };
    this._tokenMetadataCache.set(cacheKey, metadata);
    return { ...metadata };
  }

  async #getBestEffortTokenMetadata(runtimeConfig, tokenAddress) {
    try {
      return await this.#getTokenMetadata(runtimeConfig, tokenAddress);
    } catch {
      return {
        address: tokenAddress,
        name: null,
        symbol: null,
        decimals: null,
        verified: false,
        source: "erc20-rpc-unavailable",
      };
    }
  }

  async #prepareTokenTransferContext({ account, runtimeConfig, transfer, ownerAddress }) {
    const currentBalance = await this.#readTokenBalanceWithFallback({
      account,
      runtimeConfig,
      tokenAddress: transfer.token,
      ownerAddress,
    });
    if (currentBalance < transfer.amount) {
      throw createTaggedError("Insufficient token balance for transfer.", "insufficient_funds", {
        network: runtimeConfig.network,
        tokenAddress: transfer.token,
        ownerAddress,
        recipient: transfer.recipient,
        currentBalance: currentBalance.toString(),
        requiredAmount: transfer.amount.toString(),
        assetType: "erc20",
      });
    }
    const tokenMetadata = await this.#getBestEffortTokenMetadata(runtimeConfig, transfer.token);
    return {
      currentBalance,
      tokenMetadata,
    };
  }

  async #readTokenBalanceWithFallback({ account, runtimeConfig, tokenAddress, ownerAddress }) {
    try {
      return await account.getTokenBalance(tokenAddress);
    } catch (error) {
      if (!isRecoverableTokenBalanceReadFailure(error)) {
        throw error;
      }
      const code = await rpcRequest(runtimeConfig.providerUrl, "eth_getCode", [
        normalizeAddress(tokenAddress, "tokenAddress"),
        "latest",
      ]);
      if (!code || String(code).toLowerCase() === "0x") {
        throw createTaggedError("Token contract could not be resolved on this network.", "token_not_found", {
          network: runtimeConfig.network,
          tokenAddress,
        });
      }
      return await this.#readTokenBalanceDirect(runtimeConfig, tokenAddress, ownerAddress);
    }
  }

  async #readTokenBalanceDirect(runtimeConfig, tokenAddress, ownerAddress) {
    const data = buildBalanceOfCallData(ownerAddress);
    let lastError = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const raw = await ethCall(runtimeConfig.providerUrl, tokenAddress, data);
        return decodeUint256Result(raw, "balanceOf");
      } catch (error) {
        lastError = error;
        if (
          attempt >= 2 ||
          !isRecoverableTokenBalanceReadFailure(error) ||
          normalizeErrorCodeValue(error) === "network_unavailable"
        ) {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 150 * (attempt + 1)));
      }
    }
    throw createTaggedError("Token balance could not be read from the token contract.", "token_read_failed", {
      network: runtimeConfig.network,
      tokenAddress,
      ownerAddress,
      underlying:
        lastError instanceof Error
          ? {
              message: lastError.message,
              code: String(lastError.errorCode || lastError.code || "").trim() || null,
            }
          : {
              message: String(lastError),
              code: null,
            },
    });
  }

  async #getSwapTokenMetadata(runtimeConfig, tokenAddress, fallbackDecimals) {
    if (isVeloraNativeTokenAddress(tokenAddress)) {
      return {
        address: tokenAddress,
        name: runtimeConfig.nativeSymbol === "ETH" ? "Ether" : runtimeConfig.nativeSymbol,
        symbol: runtimeConfig.nativeSymbol,
        decimals: 18,
        verified: true,
        source: "native-asset",
      };
    }
    try {
      return await this.#getTokenMetadata(runtimeConfig, tokenAddress);
    } catch (error) {
      const decimals = Number(fallbackDecimals);
      if (!Number.isInteger(decimals) || decimals < 0 || decimals > 255) {
        throw error;
      }
      return {
        address: tokenAddress,
        name: null,
        symbol: null,
        decimals,
        verified: false,
        source: "swap-route-fallback",
      };
    }
  }

  #assertMaxFee(runtimeConfig, fee, operation) {
    if (
      runtimeConfig.transferMaxFeeWei !== null &&
      BigInt(fee) >= BigInt(runtimeConfig.transferMaxFeeWei)
    ) {
      throw createTaggedError(`Exceeded maximum fee cost for ${operation}.`, "fee_limit_exceeded", {
        network: runtimeConfig.network,
        operation,
        fee: BigInt(fee).toString(),
        maxFee: BigInt(runtimeConfig.transferMaxFeeWei).toString(),
      });
    }
  }

  async #buildLifiEvmSwapPlan({
    account,
    runtimeConfig,
    address,
    swapRequest,
    tolerateSwapFeeFailure = false,
  }) {
    const quote = await this.#fetchLifiQuote({
      runtimeConfig,
      address,
      swapRequest,
    });
    const transactionRequest = quote.transactionRequest || {};
    const spender = !isZeroAddress(swapRequest.tokenIn)
      ? normalizeAddress(String(quote.estimate?.approvalAddress || ""), "approvalAddress")
      : normalizeAddress(String(transactionRequest.to || ""), "transactionRequest.to");
    const swapTx = {
      to: normalizeAddress(String(transactionRequest.to || ""), "transactionRequest.to"),
      data: assertNonEmptyString(String(transactionRequest.data || ""), "transactionRequest.data"),
      value: parseHexOrDecimalBigInt(transactionRequest.value || "0", "transactionRequest.value"),
    };
    const isNativeTokenIn = isZeroAddress(swapRequest.tokenIn);
    const allowanceState = isNativeTokenIn
      ? {
          currentAllowance: swapRequest.tokenInAmount,
          error: null,
        }
      : await this.#getSwapAllowanceState({
          account,
          tokenAddress: swapRequest.tokenIn,
          spender,
        });
    const currentAllowance = allowanceState.currentAllowance;
    const approval = isNativeTokenIn
      ? {
          required: false,
          estimatedFee: 0n,
          steps: [],
        }
      : await this.#buildSwapApprovalPlan({
          account,
          runtimeConfig,
          tokenAddress: swapRequest.tokenIn,
          spender,
          requiredAmount: swapRequest.tokenInAmount,
          currentAllowance,
        });

    const swapFeeQuote = await this.#quoteSwapTransaction({
      account,
      runtimeConfig,
      from: address,
      swapTx,
      fallbackGasLimit: parseOptionalHexOrDecimalBigInt(transactionRequest.gasLimit),
      tolerateFailure: tolerateSwapFeeFailure || approval.required,
    });
    if (swapFeeQuote.fee === null && !tolerateSwapFeeFailure && !approval.required) {
      throw createTaggedError(
        "LI.FI swap fee estimate was unavailable.",
        "network_unavailable",
        {
          provider: "lifi",
          feeEstimateError: swapFeeQuote.error,
        }
      );
    }
    const simulation = approval.required
      ? {
          ok: null,
          skipped: true,
          reason: "allowance_required",
        }
      : await this.#simulatePreparedTransaction({
          runtimeConfig,
          from: address,
          tx: swapTx,
        });
    const tokenOutAmount = BigInt(String(quote.estimate?.toAmount || "0"));
    const minimumTokenOutAmount = BigInt(String(quote.estimate?.toAmountMin || quote.estimate?.toAmount || "0"));
    const swapTransaction = {
      to: swapTx.to,
      value: swapTx.value.toString(),
      dataHash: sha256Hex(swapTx.data),
    };
    const quoteFingerprint = sha256Hex(
      JSON.stringify({
        chainId: runtimeConfig.chainId,
        network: runtimeConfig.network,
        from: address.toLowerCase(),
        sourceChainId: LIFI_CHAIN_IDS_BY_NETWORK[runtimeConfig.network],
        destinationChainId: swapRequest.destinationChainId,
        tokenIn: swapRequest.tokenIn.toLowerCase(),
        outputToken: swapRequest.outputToken,
        destinationAddress: swapRequest.destinationAddress,
        tokenInAmount: swapRequest.tokenInAmount.toString(),
        minimumTokenOutAmount: minimumTokenOutAmount.toString(),
        tool: quote.tool,
        swapTxTo: swapTransaction.to.toLowerCase(),
        swapTxValue: swapTransaction.value,
      })
    );
    return {
      quote,
      quoteFingerprint,
      quoteId: String(quote.id || "").trim() || null,
      quoteType: String(quote.type || "").trim() || null,
      tool: String(quote.tool || "").trim() || null,
      toolDetails: quote.toolDetails || null,
      slippage: Number(quote.action?.slippage ?? swapRequest.slippage),
      minimumTokenOutAmount,
      router: swapTx.to,
      spender,
      currentAllowance,
      allowanceReadError: allowanceState.error,
      tokenInAmount: swapRequest.tokenInAmount,
      tokenOutAmount,
      swapTx,
      swapFee: swapFeeQuote.fee,
      swapFeeError: swapFeeQuote.error,
      totalEstimatedFee: swapFeeQuote.fee !== null ? swapFeeQuote.fee + approval.estimatedFee : null,
      approval,
      simulation,
      swapTransaction,
      tokenInMetadata: this.#buildLifiTokenMetadata(
        quote.action?.fromToken,
        swapRequest.tokenIn,
        isNativeTokenIn ? "native-asset" : "lifi-source-token"
      ),
      outputTokenMetadata: this.#buildLifiTokenMetadata(
        quote.action?.toToken,
        swapRequest.outputToken,
        "lifi-destination-token"
      ),
    };
  }

  async #fetchLifiQuote({ runtimeConfig, address, swapRequest }) {
    const params = new URLSearchParams({
      fromChain: LIFI_CHAIN_IDS_BY_NETWORK[runtimeConfig.network],
      toChain: swapRequest.destinationChainId,
      fromToken: swapRequest.tokenIn,
      toToken: swapRequest.outputToken,
      fromAmount: swapRequest.tokenInAmount.toString(),
      fromAddress: address,
      toAddress: swapRequest.destinationAddress,
      slippage: String(swapRequest.slippage),
      integrator: this.config.lifiIntegrator || "openclaw",
    });
    const denyBridges = mergeBridgeLists(
      this.config.lifiDefaultDenyBridges,
      swapRequest.denyBridges,
      ALWAYS_DENIED_LIFI_BRIDGES
    );
    if (swapRequest.allowBridges) {
      params.set("allowBridges", swapRequest.allowBridges);
    }
    if (denyBridges) {
      params.set("denyBridges", denyBridges);
    }
    if (swapRequest.preferBridges) {
      params.set("preferBridges", swapRequest.preferBridges);
    }
    const response = await fetch(`${String(this.config.lifiApiBaseUrl).replace(/\/+$/, "")}/quote?${params.toString()}`, {
      headers: {
        Accept: "application/json",
        ...(this.config.lifiApiKey ? { "x-lifi-api-key": this.config.lifiApiKey } : {}),
      },
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const message =
        payload?.message || payload?.error || payload?.detail || `LI.FI quote failed with HTTP ${response.status}.`;
      throw createTaggedError(String(message), "network_unavailable", {
        provider: "lifi",
        httpStatus: response.status,
      });
    }
    if (!payload || typeof payload !== "object" || !payload.transactionRequest) {
      throw createTaggedError("LI.FI quote returned no executable transactionRequest.", "network_unavailable", {
        provider: "lifi",
      });
    }
    return payload;
  }

  #buildLifiTokenMetadata(token, fallbackAddress, fallbackSource = "lifi-quote") {
    const raw = token && typeof token === "object" ? token : {};
    const decimals = Number(raw.decimals);
    return {
      address: String(raw.address || fallbackAddress || "").trim(),
      name: raw.name !== undefined && raw.name !== null ? String(raw.name) : null,
      symbol: raw.symbol !== undefined && raw.symbol !== null ? String(raw.symbol) : null,
      decimals: Number.isInteger(decimals) ? decimals : null,
      verified: Array.isArray(raw.tags) && raw.tags.includes("stablecoin"),
      source: fallbackSource,
    };
  }

  #formatLifiSwapResponse({ runtimeConfig, accountIndex, address, swapRequest, plan }) {
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      accountIndex,
      address,
      protocol: "lifi",
      executionSupported: true,
      sourceChain: runtimeConfig.network,
      destinationChainId: swapRequest.destinationChainId,
      destinationChain: swapRequest.destinationChainId,
      swapRequest: {
        tokenIn: swapRequest.tokenIn,
        outputToken: swapRequest.outputToken,
        destinationAddress: swapRequest.destinationAddress,
        tokenInAmount: swapRequest.tokenInAmount.toString(),
      },
      tokenInMetadata: plan.tokenInMetadata,
      outputTokenMetadata: plan.outputTokenMetadata,
      inputAmountFormatted:
        plan.tokenInMetadata.decimals !== null
          ? formatUnits(swapRequest.tokenInAmount, plan.tokenInMetadata.decimals)
          : null,
      outputAmountFormatted:
        plan.outputTokenMetadata.decimals !== null
          ? formatUnits(plan.tokenOutAmount, plan.outputTokenMetadata.decimals)
          : null,
      quoteFingerprint: plan.quoteFingerprint,
      estimatedFeeWei: plan.totalEstimatedFee !== null ? plan.totalEstimatedFee.toString() : null,
      estimatedSwapFeeWei: plan.swapFee !== null ? plan.swapFee.toString() : null,
      estimatedApprovalFeeWei: plan.approval.estimatedFee.toString(),
      feeEstimateAvailable: plan.swapFee !== null,
      feeEstimateError: plan.swapFeeError,
      slippage: plan.slippage,
      minimumOutputAmountRaw: plan.minimumTokenOutAmount.toString(),
      allowance: {
        spender: plan.spender,
        currentAllowance: plan.currentAllowance.toString(),
        requiredAllowance: plan.tokenInAmount.toString(),
        approvalRequired: plan.approval.required,
        approvalSequence: plan.approval.steps,
        readError: plan.allowanceReadError,
      },
      router: plan.router,
      simulation: plan.simulation,
      swapTransaction: plan.swapTransaction,
      quoteType: plan.quoteType,
      quoteId: plan.quoteId,
      tool: plan.tool,
      toolDetails: plan.toolDetails,
      quote: plan.quote,
      source: "lifi",
    };
  }

  #assertExpectedSwapFingerprint(expectedQuoteFingerprint, actualQuoteFingerprint) {
    if (!expectedQuoteFingerprint) {
      return;
    }
    if (expectedQuoteFingerprint !== actualQuoteFingerprint) {
      throw createTaggedError(
        "Swap quote changed since preview. Generate a new preview and approval before execute.",
        "swap_quote_changed",
        {
          expectedQuoteFingerprint,
          actualQuoteFingerprint,
        }
      );
    }
  }

  #assertMinimumSwapOutput(expectedMinimumTokenOutAmount, actualMinimumTokenOutAmount, actualTokenOutAmount) {
    if (expectedMinimumTokenOutAmount === null || expectedMinimumTokenOutAmount === undefined) {
      return;
    }
    if (BigInt(actualTokenOutAmount) < BigInt(expectedMinimumTokenOutAmount)) {
      throw createTaggedError(
        "Swap quote changed beyond the allowed slippage window. Generate a new preview and approval before execute.",
        "swap_quote_changed",
        {
          expectedMinimumTokenOutAmount: BigInt(expectedMinimumTokenOutAmount).toString(),
          actualMinimumTokenOutAmount: BigInt(actualMinimumTokenOutAmount).toString(),
          actualTokenOutAmount: BigInt(actualTokenOutAmount).toString(),
        }
      );
    }
  }

  #assertSimulationSucceeded(simulation) {
    if (simulation?.ok === false) {
      throw createTaggedError(
        simulation.message || "Swap simulation failed.",
        "swap_simulation_failed",
        {
          ...(simulation.details && typeof simulation.details === "object" ? simulation.details : {}),
        }
      );
    }
  }

  #formatAaveAccountData(accountData) {
    return {
      totalCollateralBase: BigInt(accountData.totalCollateralBase || 0).toString(),
      totalDebtBase: BigInt(accountData.totalDebtBase || 0).toString(),
      availableBorrowsBase: BigInt(accountData.availableBorrowsBase || 0).toString(),
      currentLiquidationThreshold: BigInt(accountData.currentLiquidationThreshold || 0).toString(),
      ltv: BigInt(accountData.ltv || 0).toString(),
      healthFactor: BigInt(accountData.healthFactor || 0).toString(),
    };
  }

  async #readAaveReserveCatalog(protocol) {
    const addressMap = await protocol._getAddressMap();
    const uiPoolDataProviderContract = await protocol._getUiPoolDataProviderContract();
    const [reservesRaw, baseCurrencyInfoRaw] = await uiPoolDataProviderContract.getReservesData(
      addressMap.poolAddressesProvider
    );
    const baseCurrencyInfo = this.#formatAaveBaseCurrencyInfo(baseCurrencyInfoRaw);
    const reserves = (Array.isArray(reservesRaw) ? reservesRaw : []).map((reserve) =>
      this.#formatAaveReserveEntry(reserve, baseCurrencyInfo)
    );
    return {
      addresses: {
        pool: addressMap.pool,
        poolAddressesProvider: addressMap.poolAddressesProvider,
        uiPoolDataProvider: addressMap.uiPoolDataProvider,
        priceOracle: addressMap.priceOracle,
      },
      baseCurrencyInfo,
      reserves,
    };
  }

  #getAaveProtocolDataProviderContract(network, protocol) {
    const contractAddress = AAVE_PROTOCOL_DATA_PROVIDER_BY_NETWORK[network];
    if (!contractAddress) {
      throw new Error(`Aave protocol data provider is not configured for network '${network}'.`);
    }
    return new Contract(contractAddress, AAVE_PROTOCOL_DATA_PROVIDER_ABI, protocol._provider);
  }

  #formatAaveBaseCurrencyInfo(baseCurrencyInfo) {
    const usdDecimals = Number(baseCurrencyInfo?.networkBaseTokenPriceDecimals || 8);
    const marketReferenceCurrencyPriceInUsd = BigInt(
      baseCurrencyInfo?.marketReferenceCurrencyPriceInUsd || 0
    );
    const networkBaseTokenPriceInUsd = BigInt(baseCurrencyInfo?.networkBaseTokenPriceInUsd || 0);
    return {
      marketReferenceCurrencyUnit: BigInt(baseCurrencyInfo?.marketReferenceCurrencyUnit || 0).toString(),
      marketReferenceCurrencyPriceInUsd: marketReferenceCurrencyPriceInUsd.toString(),
      marketReferenceCurrencyPriceInUsdFormatted:
        marketReferenceCurrencyPriceInUsd > 0n ? formatUnits(marketReferenceCurrencyPriceInUsd, usdDecimals) : null,
      networkBaseTokenPriceInUsd: networkBaseTokenPriceInUsd.toString(),
      networkBaseTokenPriceInUsdFormatted:
        networkBaseTokenPriceInUsd > 0n ? formatUnits(networkBaseTokenPriceInUsd, usdDecimals) : null,
      networkBaseTokenPriceDecimals: usdDecimals,
      usdDecimals,
    };
  }

  #formatAaveReserveEntry(reserve, baseCurrencyInfo) {
    const decimals = Number(reserve?.decimals || 18);
    const liquidityIndexRaw = BigInt(reserve?.liquidityIndex || 0);
    const variableBorrowIndexRaw = BigInt(reserve?.variableBorrowIndex || 0);
    const totalScaledVariableDebtRaw = BigInt(reserve?.totalScaledVariableDebt || 0);
    const totalVariableDebtRaw = rayMul(totalScaledVariableDebtRaw, variableBorrowIndexRaw);
    const priceInUsdRaw = computeAaveUsdPriceRaw(
      BigInt(reserve?.priceInMarketReferenceCurrency || 0),
      baseCurrencyInfo
    );
    return {
      underlyingAsset: normalizeAddress(String(reserve?.underlyingAsset || ""), "underlyingAsset").toLowerCase(),
      name: String(reserve?.name || "").trim() || null,
      symbol: String(reserve?.symbol || "").trim() || null,
      decimals,
      baseLtvAsCollateral: BigInt(reserve?.baseLTVasCollateral || 0).toString(),
      baseLtvAsCollateralPercent: formatBasisPoints(BigInt(reserve?.baseLTVasCollateral || 0)),
      reserveLiquidationThreshold: BigInt(reserve?.reserveLiquidationThreshold || 0).toString(),
      reserveLiquidationThresholdPercent: formatBasisPoints(
        BigInt(reserve?.reserveLiquidationThreshold || 0)
      ),
      reserveLiquidationBonus: BigInt(reserve?.reserveLiquidationBonus || 0).toString(),
      reserveFactor: BigInt(reserve?.reserveFactor || 0).toString(),
      reserveFactorPercent: formatBasisPoints(BigInt(reserve?.reserveFactor || 0)),
      usageAsCollateralEnabled: Boolean(reserve?.usageAsCollateralEnabled),
      borrowingEnabled: Boolean(reserve?.borrowingEnabled),
      isActive: Boolean(reserve?.isActive),
      isFrozen: Boolean(reserve?.isFrozen),
      isPaused: Boolean(reserve?.isPaused),
      isSiloedBorrowing: Boolean(reserve?.isSiloedBorrowing),
      flashLoanEnabled: Boolean(reserve?.flashLoanEnabled),
      borrowableInIsolation: Boolean(reserve?.borrowableInIsolation),
      virtualAccActive: Boolean(reserve?.virtualAccActive),
      aTokenAddress: normalizeAddress(String(reserve?.aTokenAddress || ""), "aTokenAddress").toLowerCase(),
      variableDebtTokenAddress: normalizeAddress(
        String(reserve?.variableDebtTokenAddress || ""),
        "variableDebtTokenAddress"
      ).toLowerCase(),
      interestRateStrategyAddress: normalizeAddress(
        String(reserve?.interestRateStrategyAddress || ""),
        "interestRateStrategyAddress"
      ).toLowerCase(),
      availableLiquidityRaw: BigInt(reserve?.availableLiquidity || 0).toString(),
      availableLiquidityFormatted: formatUnits(BigInt(reserve?.availableLiquidity || 0), decimals),
      totalScaledVariableDebtRaw: totalScaledVariableDebtRaw.toString(),
      totalVariableDebtRaw: totalVariableDebtRaw.toString(),
      totalVariableDebtFormatted: formatUnits(totalVariableDebtRaw, decimals),
      liquidityIndexRaw: liquidityIndexRaw.toString(),
      variableBorrowIndexRaw: variableBorrowIndexRaw.toString(),
      liquidityRateRaw: BigInt(reserve?.liquidityRate || 0).toString(),
      liquidityAprPercent: formatRayAprPercent(BigInt(reserve?.liquidityRate || 0)),
      variableBorrowRateRaw: BigInt(reserve?.variableBorrowRate || 0).toString(),
      variableBorrowAprPercent: formatRayAprPercent(BigInt(reserve?.variableBorrowRate || 0)),
      lastUpdateTimestamp: BigInt(reserve?.lastUpdateTimestamp || 0).toString(),
      priceInMarketReferenceCurrency: BigInt(reserve?.priceInMarketReferenceCurrency || 0).toString(),
      priceInUsdRaw: priceInUsdRaw !== null ? priceInUsdRaw.toString() : null,
      priceInUsdFormatted:
        priceInUsdRaw !== null ? formatUnits(priceInUsdRaw, baseCurrencyInfo.usdDecimals) : null,
      priceOracle: normalizeAddress(String(reserve?.priceOracle || ""), "priceOracle").toLowerCase(),
      variableRateSlope1Raw: BigInt(reserve?.variableRateSlope1 || 0).toString(),
      variableRateSlope2Raw: BigInt(reserve?.variableRateSlope2 || 0).toString(),
      baseVariableBorrowRateRaw: BigInt(reserve?.baseVariableBorrowRate || 0).toString(),
      optimalUsageRatioRaw: BigInt(reserve?.optimalUsageRatio || 0).toString(),
      accruedToTreasuryRaw: BigInt(reserve?.accruedToTreasury || 0).toString(),
      unbackedRaw: BigInt(reserve?.unbacked || 0).toString(),
      isolationModeTotalDebtRaw: BigInt(reserve?.isolationModeTotalDebt || 0).toString(),
      debtCeilingRaw: BigInt(reserve?.debtCeiling || 0).toString(),
      debtCeilingDecimals: Number(reserve?.debtCeilingDecimals || 0),
      borrowCapRaw: BigInt(reserve?.borrowCap || 0).toString(),
      supplyCapRaw: BigInt(reserve?.supplyCap || 0).toString(),
      virtualUnderlyingBalanceRaw: BigInt(reserve?.virtualUnderlyingBalance || 0).toString(),
    };
  }

  async #buildAaveOperationPlan({
    account,
    runtimeConfig,
    address,
    request,
    tolerateOperationFeeFailure = false,
  }) {
    const protocol = new AaveProtocolEvm(account);
    try {
      const poolContract = await protocol._getPoolContract();
      const spender = normalizeAddress(String(poolContract.target || ""), "aavePool");
      const needsAllowance = ["supply", "repay"].includes(request.operation);
      const allowanceState = needsAllowance
        ? await this.#getSwapAllowanceState({
            account,
            tokenAddress: request.token,
            spender,
          })
        : {
            currentAllowance: request.amount,
            error: null,
          };
      const currentAllowance = allowanceState.currentAllowance;
      const approval = needsAllowance
        ? await this.#buildAaveApprovalPlan({
            account,
            runtimeConfig,
            tokenAddress: request.token,
            spender,
            requiredAmount: request.amount,
            currentAllowance,
          })
        : {
            required: false,
            estimatedFee: 0n,
            steps: [],
          };
      const operationFeeQuote = await this.#quoteAaveProtocolOperation({
        protocol,
        request,
        skipWhenApprovalRequired: approval.required,
        tolerateFailure: tolerateOperationFeeFailure || approval.required,
      });
      const tokenMetadata = await this.#getBestEffortTokenMetadata(runtimeConfig, request.token);
      const quoteFingerprint = sha256Hex(
        JSON.stringify({
          chainId: runtimeConfig.chainId,
          network: runtimeConfig.network,
          from: address.toLowerCase(),
          protocol: "aave-v3",
          operation: request.operation,
          pool: spender.toLowerCase(),
          token: request.token.toLowerCase(),
          amount: request.amount.toString(),
        })
      );
      return {
        quoteFingerprint,
        spender,
        currentAllowance,
        allowanceReadError: allowanceState.error,
        amount: request.amount,
        operationFee: operationFeeQuote.fee,
        operationFeeError: operationFeeQuote.error,
        totalEstimatedFee:
          operationFeeQuote.fee !== null ? operationFeeQuote.fee + approval.estimatedFee : null,
        approval,
        tokenMetadata,
      };
    } finally {
      await maybeDispose(protocol);
    }
  }

  async #quoteAaveProtocolOperation({
    protocol,
    request,
    skipWhenApprovalRequired,
    tolerateFailure,
  }) {
    if (skipWhenApprovalRequired) {
      return {
        fee: null,
        error: {
          code: "allowance_required",
          message: "Operation fee estimate is unavailable until the Aave pool allowance is approved.",
        },
      };
    }
    const quoteMethod = {
      supply: "quoteSupply",
      withdraw: "quoteWithdraw",
      borrow: "quoteBorrow",
      repay: "quoteRepay",
    }[request.operation];
    try {
      const quote = await protocol[quoteMethod]({
        token: request.token,
        amount: request.amount,
      });
      const fee = BigInt(quote?.fee || 0);
      return {
        fee,
        error: null,
      };
    } catch (error) {
      if (!tolerateFailure) {
        throw error;
      }
      return {
        fee: null,
        error: {
          code: normalizeErrorCodeValue(error) || null,
          message: error instanceof Error ? error.message : String(error),
        },
      };
    }
  }

  async #buildAaveApprovalPlan({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    requiredAmount,
    currentAllowance,
  }) {
    const steps = [];
    if (currentAllowance < requiredAmount) {
      if (
        runtimeConfig.chainId === 1 &&
        tokenAddress.toLowerCase() === USDT_MAINNET_ADDRESS &&
        currentAllowance > 0n
      ) {
        steps.push({ type: "reset_allowance", amount: "0" });
      }
      steps.push({ type: "approve", amount: requiredAmount.toString() });
    }
    let estimatedFee = 0n;
    for (const step of steps) {
      const quote = await account.quoteSendTransaction(
        buildErc20ApproveTransaction(tokenAddress, spender, step.amount)
      );
      const fee = BigInt(quote.fee);
      this.#assertMaxFee(runtimeConfig, fee, `aave ${step.type}`);
      step.estimatedFeeWei = fee.toString();
      estimatedFee += fee;
    }
    return {
      required: steps.length > 0,
      estimatedFee,
      steps,
    };
  }

  #formatAaveOperationResponse({ runtimeConfig, accountIndex, address, request, plan }) {
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      accountIndex,
      address,
      protocol: "aave-v3",
      operation: request.operation,
      operationRequest: {
        token: request.token,
        amount: request.amount.toString(),
      },
      tokenMetadata: plan.tokenMetadata,
      amountFormatted:
        plan.tokenMetadata && Number.isInteger(plan.tokenMetadata.decimals)
          ? formatUnits(request.amount, plan.tokenMetadata.decimals)
          : null,
      quoteFingerprint: plan.quoteFingerprint,
      estimatedFeeWei: plan.totalEstimatedFee !== null ? plan.totalEstimatedFee.toString() : null,
      estimatedOperationFeeWei: plan.operationFee !== null ? plan.operationFee.toString() : null,
      estimatedApprovalFeeWei: plan.approval.estimatedFee.toString(),
      feeEstimateAvailable: plan.operationFee !== null,
      feeEstimateError: plan.operationFeeError,
      allowance: {
        spender: plan.spender,
        currentAllowance: plan.currentAllowance.toString(),
        requiredAllowance: plan.amount.toString(),
        approvalRequired: plan.approval.required,
        approvalSequence: plan.approval.steps,
        readError: plan.allowanceReadError,
      },
      source: "wdk-protocol-lending-aave-evm",
    };
  }

  #assertExpectedAaveFingerprint(expectedQuoteFingerprint, actualQuoteFingerprint) {
    if (!expectedQuoteFingerprint) {
      return;
    }
    if (expectedQuoteFingerprint !== actualQuoteFingerprint) {
      throw createTaggedError(
        "Aave quote changed since preview. Generate a new preview and approval before execute.",
        "aave_quote_changed",
        {
          expectedQuoteFingerprint,
          actualQuoteFingerprint,
        }
      );
    }
  }

  async #executeAaveApprovalsIfNeeded({ account, runtimeConfig, request, plan }) {
    if (!plan.approval.required) {
      return {
        performed: false,
        totalFee: 0n,
        approveHash: null,
        resetAllowanceHash: null,
      };
    }
    let totalFee = 0n;
    let approveHash = null;
    let resetAllowanceHash = null;
    for (const step of plan.approval.steps) {
      const result = await account.approve({
        token: request.token,
        spender: plan.spender,
        amount: step.amount,
      });
      totalFee += BigInt(result.fee || 0);
      if (step.type === "reset_allowance") {
        resetAllowanceHash = result.hash;
      } else if (step.type === "approve") {
        approveHash = result.hash;
      }
      await this.#waitForTransactionReceipt(runtimeConfig, result.hash);
    }
    return {
      performed: true,
      totalFee,
      approveHash,
      resetAllowanceHash,
    };
  }

  async #restoreAllowanceAfterFailedAaveOperation({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    originalAllowance,
    approvalExecution,
  }) {
    if (!approvalExecution?.performed) {
      return {
        attempted: false,
        restored: false,
        originalAllowance: BigInt(originalAllowance || 0n).toString(),
      };
    }
    const cleanup = {
      attempted: true,
      restored: false,
      originalAllowance: BigInt(originalAllowance || 0n).toString(),
      restoreHashes: [],
      restoreSteps: [],
      error: null,
    };
    try {
      const restorePlan = await this.#buildAllowanceRestorePlan({
        account,
        runtimeConfig,
        tokenAddress,
        spender,
        targetAllowance: BigInt(originalAllowance || 0n),
      });
      cleanup.restoreSteps = restorePlan.steps.map((step) => ({ ...step }));
      if (!restorePlan.required) {
        cleanup.restored = true;
        return cleanup;
      }
      for (const step of restorePlan.steps) {
        const result = await account.approve({
          token: tokenAddress,
          spender,
          amount: step.amount,
        });
        cleanup.restoreHashes.push({
          type: step.type,
          hash: result.hash,
          fee: BigInt(result.fee || 0).toString(),
        });
        await this.#waitForTransactionReceipt(runtimeConfig, result.hash);
      }
      const finalAllowance = await account.getAllowance(tokenAddress, spender);
      cleanup.finalAllowance = finalAllowance.toString();
      cleanup.restored = finalAllowance === BigInt(originalAllowance || 0n);
      return cleanup;
    } catch (cleanupError) {
      cleanup.error = {
        message: cleanupError instanceof Error ? cleanupError.message : String(cleanupError),
        code:
          cleanupError && typeof cleanupError === "object"
            ? String(cleanupError.errorCode || cleanupError.code || "").trim() || null
            : null,
      };
      return cleanup;
    }
  }

  #throwAaveFailureWithCleanup(error, cleanup) {
    if (cleanup?.attempted && cleanup.restored !== true) {
      throw createTaggedError(
        "Aave operation failed after approval and automatic allowance restore did not complete.",
        "aave_cleanup_failed",
        {
          originalError:
            error instanceof Error
              ? {
                  message: error.message,
                  code: String(error.errorCode || error.code || "").trim() || null,
                }
              : { message: String(error), code: null },
          cleanup,
        }
      );
    }
    throw error;
  }

  async #getSwapAllowanceState({ account, tokenAddress, spender }) {
    try {
      return {
        currentAllowance: await account.getAllowance(tokenAddress, spender),
        error: null,
      };
    } catch (error) {
      if (!isRecoverableAllowanceReadFailure(error)) {
        throw error;
      }
      return {
        currentAllowance: 0n,
        error: {
          code: normalizeErrorCodeValue(error) || null,
          message: error instanceof Error ? error.message : String(error),
        },
      };
    }
  }

  async #buildVeloraSwapPlan({
    account,
    runtimeConfig,
    swapRequest,
    tolerateSwapFeeFailure = false,
  }) {
    const protocol = new VeloraProtocolEvm(account);
    try {
      const veloraSdk = await protocol._getVeloraSdk();
      const address = await account.getAddress();
      const normalizedTokenIn = swapRequest.tokenIn.toLowerCase();
      const normalizedTokenOut = swapRequest.tokenOut.toLowerCase();
      const slippageBps = DEFAULT_SWAP_SLIPPAGE_BPS;
      const priceRoute = await veloraSdk.swap.getRate({
        srcToken: normalizedTokenIn,
        destToken: normalizedTokenOut,
        amount: swapRequest.tokenInAmount.toString(),
        side: "SELL",
      });
      const swapTx = await veloraSdk.swap.buildTx(
        {
          partner: "wdk",
          srcToken: priceRoute.srcToken,
          destToken: priceRoute.destToken,
          srcAmount: priceRoute.srcAmount,
          slippage: slippageBps,
          userAddress: address,
          priceRoute,
        },
        {
          ignoreChecks: true,
        }
      );
      const [spender, contracts] = await Promise.all([
        veloraSdk.swap.getSpender(),
        typeof veloraSdk.swap.getContracts === "function"
          ? veloraSdk.swap.getContracts()
          : Promise.resolve(null),
      ]);
      const router = normalizeAddress(
        String(
          contracts?.AugustusSwapper ||
            swapTx.to ||
            ""
        ),
        "router"
      );
      const normalizedSpender = normalizeAddress(spender, "spender");
      const isNativeTokenIn = isVeloraNativeTokenAddress(swapRequest.tokenIn);
      const allowanceState = isNativeTokenIn
        ? {
            currentAllowance: swapRequest.tokenInAmount,
            error: null,
          }
        : await this.#getSwapAllowanceState({
            account,
            tokenAddress: swapRequest.tokenIn,
            spender: normalizedSpender,
          });
      const currentAllowance = allowanceState.currentAllowance;
      const approval = isNativeTokenIn
        ? {
            required: false,
            estimatedFee: 0n,
            steps: [],
          }
        : await this.#buildSwapApprovalPlan({
            account,
            runtimeConfig,
            tokenAddress: swapRequest.tokenIn,
            spender: normalizedSpender,
            requiredAmount: swapRequest.tokenInAmount,
            currentAllowance,
          });
      const swapFeeQuote = await this.#quoteSwapTransaction({
        account,
        runtimeConfig,
        from: address,
        swapTx,
        fallbackGasLimit: parseOptionalDecimalBigInt(priceRoute?.gasCost),
        tolerateFailure: tolerateSwapFeeFailure || approval.required,
      });
      const swapFee = swapFeeQuote.fee;
      const simulation = approval.required
        ? {
            ok: null,
            skipped: true,
            reason: "allowance_required",
          }
        : await this.#simulatePreparedTransaction({
            runtimeConfig,
            from: address,
            tx: swapTx,
          });
      const swapTransaction = {
        to: normalizeAddress(String(swapTx.to || ""), "swapTx.to"),
        value: BigInt(swapTx.value || 0).toString(),
        dataHash: sha256Hex(String(swapTx.data || "")),
      };
      const minimumTokenOutAmount = computeMinimumOutputAmount(priceRoute.destAmount, slippageBps);
      const quoteFingerprint = sha256Hex(
        JSON.stringify({
          chainId: runtimeConfig.chainId,
          network: runtimeConfig.network,
          from: address.toLowerCase(),
          router: router.toLowerCase(),
          spender: normalizedSpender.toLowerCase(),
          tokenIn: swapRequest.tokenIn.toLowerCase(),
          tokenOut: swapRequest.tokenOut.toLowerCase(),
          tokenInAmount: swapRequest.tokenInAmount.toString(),
          slippageBps,
          swapTxTo: swapTransaction.to.toLowerCase(),
          swapTxValue: swapTransaction.value,
        })
      );
      return {
        priceRoute,
        quoteFingerprint,
        slippageBps,
        minimumTokenOutAmount,
        router,
        spender: normalizedSpender,
        currentAllowance,
        allowanceReadError: allowanceState.error,
        tokenInAmount: BigInt(priceRoute.srcAmount),
        tokenOutAmount: BigInt(priceRoute.destAmount),
        swapTx,
        swapFee,
        swapFeeError: swapFeeQuote.error,
        totalEstimatedFee: swapFee !== null ? swapFee + approval.estimatedFee : null,
        approval,
        simulation,
        swapTransaction,
      };
    } finally {
      await maybeDispose(protocol);
    }
  }

  async #buildSwapApprovalPlan({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    requiredAmount,
    currentAllowance,
  }) {
    const steps = [];
    if (currentAllowance < requiredAmount) {
      if (
        runtimeConfig.chainId === 1 &&
        tokenAddress.toLowerCase() === USDT_MAINNET_ADDRESS &&
        currentAllowance > 0n
      ) {
        steps.push({ type: "reset_allowance", amount: "0" });
      }
      steps.push({ type: "approve", amount: requiredAmount.toString() });
    }
    let estimatedFee = 0n;
    for (const step of steps) {
      const quote = await account.quoteSendTransaction(
        buildErc20ApproveTransaction(tokenAddress, spender, step.amount)
      );
      const fee = BigInt(quote.fee);
      this.#assertMaxFee(runtimeConfig, fee, `swap ${step.type}`);
      step.estimatedFeeWei = fee.toString();
      estimatedFee += fee;
    }
    return {
      required: steps.length > 0,
      estimatedFee,
      steps,
    };
  }

  async #buildAllowanceRestorePlan({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    targetAllowance,
    operationLabel = "swap",
  }) {
    const currentAllowance = await account.getAllowance(tokenAddress, spender);
    const desiredAllowance = BigInt(targetAllowance);
    if (currentAllowance === desiredAllowance) {
      return {
        currentAllowance,
        targetAllowance: desiredAllowance,
        required: false,
        estimatedFee: 0n,
        steps: [],
      };
    }
    const steps = [];
    if (
      runtimeConfig.chainId === 1 &&
      tokenAddress.toLowerCase() === USDT_MAINNET_ADDRESS &&
      currentAllowance > 0n
    ) {
      steps.push({ type: "reset_allowance", amount: "0" });
      if (desiredAllowance > 0n) {
        steps.push({ type: "restore_allowance", amount: desiredAllowance.toString() });
      }
    } else {
      steps.push({
        type: desiredAllowance === 0n ? "reset_allowance" : "restore_allowance",
        amount: desiredAllowance.toString(),
      });
    }
    let estimatedFee = 0n;
    for (const step of steps) {
      const quote = await account.quoteSendTransaction(
        buildErc20ApproveTransaction(tokenAddress, spender, step.amount)
      );
      const fee = BigInt(quote.fee);
      this.#assertMaxFee(runtimeConfig, fee, `${operationLabel} ${step.type}`);
      step.estimatedFeeWei = fee.toString();
      estimatedFee += fee;
    }
    return {
      currentAllowance,
      targetAllowance: desiredAllowance,
      required: steps.length > 0,
      estimatedFee,
      steps,
    };
  }

  async #executeSwapApprovalsIfNeeded({ account, runtimeConfig, swapRequest, plan }) {
    if (!plan.approval.required) {
      return {
        performed: false,
        totalFee: 0n,
        approveHash: null,
        resetAllowanceHash: null,
      };
    }
    let totalFee = 0n;
    let approveHash = null;
    let resetAllowanceHash = null;
    for (const step of plan.approval.steps) {
      const result = await account.approve({
        token: swapRequest.tokenIn,
        spender: plan.spender,
        amount: step.amount,
      });
      totalFee += BigInt(result.fee || 0);
      if (step.type === "reset_allowance") {
        resetAllowanceHash = result.hash;
      } else if (step.type === "approve") {
        approveHash = result.hash;
      }
      await this.#waitForTransactionReceipt(runtimeConfig, result.hash);
    }
    return {
      performed: true,
      totalFee,
      approveHash,
      resetAllowanceHash,
    };
  }

  async #quoteSwapTransaction({
    account,
    runtimeConfig,
    from,
    swapTx,
    fallbackGasLimit = null,
    tolerateFailure,
  }) {
    try {
      const quote = await account.quoteSendTransaction(swapTx);
      const fee = BigInt(quote.fee);
      this.#assertMaxFee(runtimeConfig, fee, "swap");
      return {
        fee,
        error: null,
      };
    } catch (error) {
      const insufficientFundsHint = parseInsufficientFundsHint(error);
      if (
        normalizeErrorCodeValue(error) === "insufficient_funds" ||
        insufficientFundsHint !== null
      ) {
        try {
          const rpcQuote = await this.#quotePreparedTransactionFromRpc({
            runtimeConfig,
            from,
            tx: swapTx,
          });
          return {
            fee: rpcQuote.fee,
            error: null,
          };
        } catch (rpcEstimateError) {
          if (fallbackGasLimit !== null) {
            try {
              const routeQuote = await this.#quotePreparedTransactionFromGasLimit({
                runtimeConfig,
                gasLimit: fallbackGasLimit,
              });
              return {
                fee: routeQuote.fee,
                error: null,
              };
            } catch {
              // Fall through to degraded error reporting below.
            }
          }
          if (!tolerateFailure || !isRecoverableSwapFeeEstimateFailure(rpcEstimateError)) {
            if (tolerateFailure) {
              return {
                fee: null,
                error: {
                  code: normalizeErrorCodeValue(error) || null,
                  message:
                    error instanceof Error
                      ? error.message
                      : String(error),
                  ...(insufficientFundsHint ? insufficientFundsHint : {}),
                  fallbackError: {
                    code: normalizeErrorCodeValue(rpcEstimateError) || null,
                    message:
                      rpcEstimateError instanceof Error
                        ? rpcEstimateError.message
                        : String(rpcEstimateError),
                  },
                },
              };
            }
            throw rpcEstimateError;
          }
          const hint = parseInsufficientFundsHint(rpcEstimateError);
          return {
            fee: null,
            error: {
              code: normalizeErrorCodeValue(rpcEstimateError) || null,
              message:
                rpcEstimateError instanceof Error
                  ? rpcEstimateError.message
                  : String(rpcEstimateError),
              ...(hint ? hint : {}),
            },
          };
        }
      }
      if (!tolerateFailure || !isRecoverableSwapFeeEstimateFailure(error)) {
        throw error;
      }
      if (fallbackGasLimit !== null) {
        try {
          const routeQuote = await this.#quotePreparedTransactionFromGasLimit({
            runtimeConfig,
            gasLimit: fallbackGasLimit,
          });
          return {
            fee: routeQuote.fee,
            error: null,
          };
        } catch {
          // Fall through to degraded error reporting below.
        }
      }
      return {
        fee: null,
        error: {
          code: normalizeErrorCodeValue(error) || null,
          message: error instanceof Error ? error.message : String(error),
          ...(insufficientFundsHint ? insufficientFundsHint : {}),
        },
      };
    }
  }

  async #quotePreparedTransactionFromRpc({ runtimeConfig, from, tx }) {
    const gasLimitHex = await rpcRequest(runtimeConfig.providerUrl, "eth_estimateGas", [
      {
        from: normalizeAddress(from, "from"),
        to: normalizeAddress(String(tx.to || ""), "to"),
        data: assertNonEmptyString(String(tx.data || ""), "data"),
        value: toRpcHex(tx.value || 0),
      },
    ]);
    const gasLimit = BigInt(gasLimitHex || "0x0");
    const effectiveFeePerGas = await this.#getEffectiveGasPrice(runtimeConfig);
    const fee = gasLimit * effectiveFeePerGas;
    this.#assertMaxFee(runtimeConfig, fee, "swap");
    return {
      gasLimit,
      effectiveFeePerGas,
      fee,
    };
  }

  async #quotePreparedTransactionFromGasLimit({ runtimeConfig, gasLimit }) {
    const normalizedGasLimit = BigInt(gasLimit);
    const effectiveFeePerGas = await this.#getEffectiveGasPrice(runtimeConfig);
    const fee = normalizedGasLimit * effectiveFeePerGas;
    this.#assertMaxFee(runtimeConfig, fee, "swap");
    return {
      gasLimit: normalizedGasLimit,
      effectiveFeePerGas,
      fee,
    };
  }

  async #getEffectiveGasPrice(runtimeConfig) {
    const gasPriceHex = await rpcRequest(runtimeConfig.providerUrl, "eth_gasPrice", []);
    const priorityHex = await rpcRequest(
      runtimeConfig.providerUrl,
      "eth_maxPriorityFeePerGas",
      []
    );
    const feeHistory = await rpcRequest(
      runtimeConfig.providerUrl,
      "eth_feeHistory",
      ["0x1", "latest", []]
    );
    const baseFeeItems = Array.isArray(feeHistory?.baseFeePerGas) ? feeHistory.baseFeePerGas : [];
    const latestBaseFeeHex = baseFeeItems.length ? baseFeeItems[baseFeeItems.length - 1] : "0x0";
    const baseFeePerGas = BigInt(latestBaseFeeHex || "0x0");
    const priorityFeePerGas = BigInt(priorityHex || "0x0");
    const gasPrice = BigInt(gasPriceHex || "0x0");
    return gasPrice > baseFeePerGas + priorityFeePerGas
      ? gasPrice
      : baseFeePerGas + priorityFeePerGas;
  }

  async #restoreAllowanceAfterFailedSwap({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    originalAllowance,
    approvalExecution,
  }) {
    if (!approvalExecution?.performed) {
      return {
        attempted: false,
        restored: false,
        originalAllowance: BigInt(originalAllowance || 0n).toString(),
      };
    }
    const cleanup = {
      attempted: true,
      restored: false,
      originalAllowance: BigInt(originalAllowance || 0n).toString(),
      restoreHashes: [],
      restoreSteps: [],
      error: null,
    };
    try {
      const restorePlan = await this.#buildAllowanceRestorePlan({
        account,
        runtimeConfig,
        tokenAddress,
        spender,
        targetAllowance: BigInt(originalAllowance || 0n),
        operationLabel: "aave",
      });
      cleanup.restoreSteps = restorePlan.steps.map((step) => ({ ...step }));
      if (!restorePlan.required) {
        cleanup.restored = true;
        return cleanup;
      }
      for (const step of restorePlan.steps) {
        const result = await account.approve({
          token: tokenAddress,
          spender,
          amount: step.amount,
        });
        cleanup.restoreHashes.push({
          type: step.type,
          hash: result.hash,
          fee: BigInt(result.fee || 0).toString(),
        });
        await this.#waitForTransactionReceipt(runtimeConfig, result.hash);
      }
      const finalAllowance = await account.getAllowance(tokenAddress, spender);
      cleanup.finalAllowance = finalAllowance.toString();
      cleanup.restored = finalAllowance === BigInt(originalAllowance || 0n);
      return cleanup;
    } catch (cleanupError) {
      cleanup.error = {
        message: cleanupError instanceof Error ? cleanupError.message : String(cleanupError),
        code:
          cleanupError && typeof cleanupError === "object"
            ? String(cleanupError.errorCode || cleanupError.code || "").trim() || null
            : null,
      };
      return cleanup;
    }
  }

  #throwSwapFailureWithCleanup(error, cleanup) {
    if (cleanup?.attempted && cleanup.restored !== true) {
      throw createTaggedError(
        "Swap failed after approval and automatic allowance restore did not complete.",
        "swap_cleanup_failed",
        {
          originalError:
            error instanceof Error
              ? {
                  message: error.message,
                  code: String(error.errorCode || error.code || "").trim() || null,
                }
              : { message: String(error), code: null },
          cleanup,
        }
      );
    }
    throw error;
  }

  async #simulatePreparedTransaction({ runtimeConfig, from, tx }) {
    try {
      await rpcRequest(runtimeConfig.providerUrl, "eth_call", [
        {
          from: normalizeAddress(from, "from"),
          to: normalizeAddress(String(tx.to || ""), "to"),
          data: assertNonEmptyString(String(tx.data || ""), "data"),
          value: toRpcHex(tx.value || 0),
        },
        "latest",
      ]);
      return {
        ok: true,
        skipped: false,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        ok: false,
        skipped: false,
        message: `Swap simulation failed: ${message}`,
        details:
          error && typeof error === "object" && error.errorDetails && typeof error.errorDetails === "object"
            ? { ...error.errorDetails }
            : {},
      };
    }
  }

  async #waitForTransactionReceipt(runtimeConfig, txHash) {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const receipt = await rpcRequest(runtimeConfig.providerUrl, "eth_getTransactionReceipt", [txHash]);
      if (receipt) {
        const status = String(receipt.status || "").toLowerCase();
        if (status === "0x0") {
          throw createTaggedError("Approval transaction reverted onchain.", "swap_approval_failed", {
            txHash,
            network: runtimeConfig.network,
          });
        }
        return receipt;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw createTaggedError(
      "Timed out waiting for approval transaction confirmation.",
      "swap_approval_timeout",
      {
        txHash,
        network: runtimeConfig.network,
      }
    );
  }
}
