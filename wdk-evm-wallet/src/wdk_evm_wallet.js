import crypto from "node:crypto";

import { Contract, Interface } from "ethers";
import { isRequirementApproval, isRequirementAuthorization } from "@morpho-org/morpho-sdk";
import WDK from "@tetherto/wdk";
import MorphoProtocolEvm from "@morpho-org/wdk-protocol-lending-morpho-evm";
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
const PERMIT2_ADDRESS = "0x000000000022D473030F116dDEE9F6B43aC78BA3";
const UNISWAP_SUPPORTED_CHAIN_IDS = { ethereum: 1, base: 8453, robinhood: 4663 };
// Universal Router v2.0 allow-list (defense-in-depth: /swap response `to` must match).
const UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK = {
  ethereum: "0x66a9893cc07d91d95644aedd05d03f95e1dba8af",
  base: "0x6ff5693b99212da76ad316178a184ab56d299b43",
  robinhood: "0x8876789976decbfcbbbe364623c63652db8c0904",
};
const AAVE_RAY = 10n ** 27n;
const LIDO_STETH_DECIMALS = 18;
const LIDO_MIN_STETH_WITHDRAWAL_AMOUNT = 100n;
const LIDO_MAX_STETH_WITHDRAWAL_AMOUNT = 1000n * 10n ** 18n;
const LIDO_CONTRACTS_BY_NETWORK = {
  ethereum: {
    steth: {
      address: "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",
      name: "Liquid staked Ether 2.0",
      symbol: "stETH",
      decimals: LIDO_STETH_DECIMALS,
    },
    wsteth: {
      address: "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0",
      name: "Wrapped liquid staked Ether 2.0",
      symbol: "wstETH",
      decimals: LIDO_STETH_DECIMALS,
    },
    referralStaker: "0xa88f0329c2c4ce51ba3fc619bbf44efe7120dd0d",
    withdrawalQueue: "0x889edc2edab5f40e902b864ad4d7ade8e412f9b1",
  },
};
const AAVE_PROTOCOL_DATA_PROVIDER_BY_NETWORK = {
  ethereum: AaveV3Ethereum.AAVE_PROTOCOL_DATA_PROVIDER,
  base: AaveV3Base.AAVE_PROTOCOL_DATA_PROVIDER,
};
const AAVE_PROTOCOL_DATA_PROVIDER_ABI = [
  "function getUserReserveData(address asset, address user) view returns (uint256 currentATokenBalance, uint256 currentStableDebt, uint256 currentVariableDebt, uint256 principalStableDebt, uint256 scaledVariableDebt, uint256 stableBorrowRate, uint256 liquidityRate, uint40 stableRateLastUpdated, bool usageAsCollateralEnabled)",
];
const LIDO_WSTETH_ABI = [
  "function getWstETHByStETH(uint256 _stETHAmount) view returns (uint256)",
  "function getStETHByWstETH(uint256 _wstETHAmount) view returns (uint256)",
  "function wrap(uint256 _stETHAmount) returns (uint256)",
  "function unwrap(uint256 _wstETHAmount) returns (uint256)",
];
const LIDO_REFERRAL_STAKER_ABI = [
  "function stakeETH(address _referral) payable returns (uint256)",
];
const LIDO_WITHDRAWAL_QUEUE_ABI = [
  "function requestWithdrawals(uint256[] _amounts, address _owner) returns (uint256[] requestIds)",
  "function requestWithdrawalsWstETH(uint256[] _amounts, address _owner) returns (uint256[] requestIds)",
  "function getWithdrawalRequests(address _owner) view returns (uint256[] requestIds)",
  "function getWithdrawalStatus(uint256[] _requestIds) view returns ((uint256 amountOfStETH,uint256 amountOfShares,address owner,uint256 timestamp,bool isFinalized,bool isClaimed)[] statuses)",
  "function claimWithdrawal(uint256 _requestId)",
];
const MORPHO_AUTHORIZATION_ABI = [
  "function setAuthorization(address authorized, bool isAuthorized)",
];
const LIDO_WSTETH_INTERFACE = new Interface(LIDO_WSTETH_ABI);
const LIDO_REFERRAL_STAKER_INTERFACE = new Interface(LIDO_REFERRAL_STAKER_ABI);
const LIDO_WITHDRAWAL_QUEUE_INTERFACE = new Interface(LIDO_WITHDRAWAL_QUEUE_ABI);
const MORPHO_AUTHORIZATION_INTERFACE = new Interface(MORPHO_AUTHORIZATION_ABI);
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
// Default is deliberately small: list responses land in an LLM agent's
// context window (a 100-item vault list is ~80 KB of JSON). Agents can raise
// the limit explicitly when they really need more.
const MORPHO_DEFAULT_LIST_LIMIT = 20;
const MORPHO_MAX_LIST_LIMIT = 500;
// Discovery lists/details only — never user positions. APY/TVL drift over
// two minutes is below the indexer's own aggregation noise.
const MORPHO_DISCOVERY_CACHE_TTL_MS = 120_000;
const MORPHO_DISCOVERY_CACHE_MAX_ENTRIES = 64;
const morphoDiscoveryCache = new Map();

function morphoDiscoveryCacheGet(key) {
  const entry = morphoDiscoveryCache.get(key);
  if (!entry) {
    return null;
  }
  if (entry.expiresAt <= Date.now()) {
    morphoDiscoveryCache.delete(key);
    return null;
  }
  return JSON.parse(entry.payload);
}

function morphoDiscoveryCacheSet(key, payload) {
  if (morphoDiscoveryCache.size >= MORPHO_DISCOVERY_CACHE_MAX_ENTRIES) {
    morphoDiscoveryCache.delete(morphoDiscoveryCache.keys().next().value);
  }
  morphoDiscoveryCache.set(key, {
    expiresAt: Date.now() + MORPHO_DISCOVERY_CACHE_TTL_MS,
    payload: JSON.stringify(payload),
  });
}
const MORPHO_VAULT_LIST_QUERY = `
  query MorphoVaultV2List($first: Int!, $where: VaultV2sFilters, $orderBy: VaultV2OrderBy, $orderDirection: OrderDirection) {
    vaultV2s(first: $first, where: $where, orderBy: $orderBy, orderDirection: $orderDirection) {
      items {
        address
        symbol
        name
        listed
        totalAssets
        totalAssetsUsd
        totalSupply
        liquidity
        liquidityUsd
        idleAssets
        idleAssetsUsd
        sharePrice
        netApy
        avgNetApy
        avgNetApyExcludingRewards
        performanceFee
        managementFee
        maxRate
        warnings {
          type
          level
        }
        asset {
          id
          address
          decimals
          symbol
          name
          priceUsd
          yield {
            apr
            lookback
          }
        }
        chain {
          id
          network
        }
        rewards {
          supplyApr
          asset {
            address
            symbol
            chain {
              id
            }
          }
        }
      }
    }
  }
`;
const MORPHO_VAULT_BY_ADDRESS_QUERY = `
  query MorphoVaultV2ByAddress($address: String!, $chainId: Int!) {
    vaultV2ByAddress(address: $address, chainId: $chainId) {
      address
      symbol
      name
      listed
      totalAssets
      totalAssetsUsd
      totalSupply
      liquidity
      liquidityUsd
      idleAssets
      idleAssetsUsd
      sharePrice
      avgNetApy
      avgNetApyExcludingRewards
      performanceFee
      managementFee
      maxRate
      metadata {
        description
        image
      }
      warnings {
        type
        level
      }
      asset {
        id
        address
        decimals
        symbol
        name
        priceUsd
        yield {
          apr
          lookback
        }
      }
      chain {
        id
        network
      }
      rewards {
        supplyApr
        asset {
          address
          symbol
          chain {
            id
          }
        }
      }
      adapters(first: 20) {
        items {
          __typename
          address
          type
          assets
          assetsUsd
          ... on MorphoMarketV1Adapter {
            positions(first: 50) {
              items {
                market {
                  marketId
                  collateralAsset {
                    symbol
                    address
                  }
                  loanAsset {
                    symbol
                    address
                  }
                }
                state {
                  supplyAssets
                  supplyAssetsUsd
                }
              }
            }
          }
          ... on MetaMorphoAdapter {
            metaMorpho {
              address
              name
              symbol
            }
          }
          ... on MorphoVaultV2Adapter {
            innerVault {
              address
              name
              symbol
            }
          }
        }
      }
    }
  }
`;
const MORPHO_MARKET_LIST_QUERY = `
  query MorphoMarketList($first: Int!, $where: MarketFilters, $orderBy: MarketOrderBy, $orderDirection: OrderDirection) {
    markets(first: $first, where: $where, orderBy: $orderBy, orderDirection: $orderDirection) {
      items {
        marketId
        lltv
        irmAddress
        warnings {
          type
          level
        }
        oracle {
          address
          type
        }
        loanAsset {
          address
          symbol
          decimals
          name
          priceUsd
        }
        collateralAsset {
          address
          symbol
          decimals
          name
          priceUsd
        }
        state {
          collateralAssets
          collateralAssetsUsd
          borrowAssets
          borrowAssetsUsd
          supplyAssets
          supplyAssetsUsd
          liquidityAssets
          liquidityAssetsUsd
          borrowApy
          avgBorrowApy
          avgNetBorrowApy
          supplyApy
          avgSupplyApy
          avgNetSupplyApy
          fee
          utilization
          rewards {
            supplyApr
            borrowApr
            asset {
              address
              symbol
              chain {
                id
              }
            }
          }
        }
      }
    }
  }
`;
const MORPHO_MARKET_BY_ID_QUERY = `
  query MorphoMarketById($marketId: String!, $chainId: Int!) {
    marketById(marketId: $marketId, chainId: $chainId) {
      marketId
      lltv
      irmAddress
      warnings {
        type
        level
      }
      oracle {
        address
        type
      }
      loanAsset {
        address
        symbol
        decimals
        name
        priceUsd
      }
      collateralAsset {
        address
        symbol
        decimals
        name
        priceUsd
      }
      state {
        collateralAssets
        collateralAssetsUsd
        borrowAssets
        borrowAssetsUsd
        supplyAssets
        supplyAssetsUsd
        liquidityAssets
        liquidityAssetsUsd
        borrowApy
        avgBorrowApy
        avgNetBorrowApy
        supplyApy
        avgSupplyApy
        avgNetSupplyApy
        fee
        utilization
        rewards {
          supplyApr
          borrowApr
          asset {
            address
            symbol
            chain {
              id
            }
          }
        }
      }
      supplyingVaults {
        address
        name
        symbol
      }
      supplyingVaultV2s {
        address
        name
        symbol
      }
    }
  }
`;
const MORPHO_USER_OVERVIEW_QUERY = `
  query MorphoUserByAddress($address: String!, $chainId: Int!) {
    userByAddress(address: $address, chainId: $chainId) {
      address
      marketPositions {
        market {
          marketId
          loanAsset {
            address
            symbol
            decimals
            name
          }
          collateralAsset {
            address
            symbol
            decimals
            name
          }
        }
        state {
          supplyShares
          supplyAssets
          supplyAssetsUsd
          borrowShares
          borrowAssets
          borrowAssetsUsd
          collateral
          collateralUsd
        }
      }
      vaultV2Positions {
        vault {
          address
          name
          symbol
          asset {
            address
            symbol
            decimals
            name
          }
        }
        shares
        assets
        assetsUsd
      }
    }
  }
`;

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
    "robinhood-mainnet": "robinhood",
  };
  const effective = aliases[normalized] || normalized;
  if (!["ethereum", "sepolia", "base", "base-sepolia", "robinhood"].includes(effective)) {
    throw new Error(
      `${fieldName} must be one of: ethereum, sepolia, base, base-sepolia, robinhood.`
    );
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

function assertNonNegativeBigIntString(value, fieldName) {
  const normalized = String(value ?? "").trim();
  if (!/^[0-9]+$/.test(normalized)) {
    throw new Error(`${fieldName} must be a non-negative base-10 integer string.`);
  }
  return normalized;
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

function assertLidoSupportedNetwork(network) {
  if (network !== "ethereum") {
    throw new Error("Lido staking is currently supported only on ethereum mainnet.");
  }
}

function assertMorphoSupportedNetwork(network) {
  if (!["ethereum", "base"].includes(network)) {
    throw new Error("Morpho is currently supported only on ethereum and base mainnet.");
  }
}

function normalizeMorphoListLimit(value) {
  if (value === undefined || value === null || value === "") {
    return MORPHO_DEFAULT_LIST_LIMIT;
  }
  const limit = assertNonNegativeInteger(value, "limit");
  if (limit < 1 || limit > MORPHO_MAX_LIST_LIMIT) {
    throw new Error(`limit must be between 1 and ${MORPHO_MAX_LIST_LIMIT}.`);
  }
  return limit;
}

function normalizeMorphoListedOnly(value, fallback = true) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  if (typeof value !== "boolean") {
    throw new Error("listedOnly must be a boolean.");
  }
  return value;
}

function buildOrderFieldLookup(fields) {
  const lookup = new Map();
  for (const field of fields) {
    lookup.set(field.toLowerCase(), field);
  }
  return lookup;
}

const MORPHO_VAULT_ORDER_LOOKUP = buildOrderFieldLookup([
  "Address",
  "TotalAssets",
  "TotalAssetsUsd",
  "TotalSupply",
  "Liquidity",
  "LiquidityUsd",
  "Apy",
  "NetApy",
  "RealAssets",
  "RealAssetsUsd",
  "IdleAssets",
  "IdleAssetsUsd",
]);

const MORPHO_MARKET_ORDER_LOOKUP = buildOrderFieldLookup([
  "UniqueKey",
  "Lltv",
  "BorrowAssets",
  "BorrowAssetsUsd",
  "SupplyAssets",
  "SupplyAssetsUsd",
  "BorrowShares",
  "SupplyShares",
  "Utilization",
  "ApyAtTarget",
  "SupplyApy",
  "NetSupplyApy",
  "BorrowApy",
  "NetBorrowApy",
  "Fee",
  "LoanAssetSymbol",
  "CollateralAssetSymbol",
  "TotalLiquidityUsd",
  "AvgBorrowApy",
  "AvgNetBorrowApy",
  "DailyBorrowApy",
  "DailyNetBorrowApy",
  "SizeUsd",
]);

function normalizeMorphoOrderBy(value, lookup, fallback, fieldName = "orderBy") {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  const canonical = lookup.get(String(value).trim().toLowerCase());
  if (!canonical) {
    throw new Error(`${fieldName} must be one of: ${[...lookup.values()].join(", ")}.`);
  }
  return canonical;
}

function normalizeMorphoOrderDirection(value, fallback = "Desc") {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }
  const normalized = String(value).trim().toLowerCase();
  if (normalized === "asc") {
    return "Asc";
  }
  if (normalized === "desc") {
    return "Desc";
  }
  throw new Error("orderDirection must be 'asc' or 'desc'.");
}

function normalizeMorphoSearch(value) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  if (typeof value !== "string") {
    throw new Error("search must be a string.");
  }
  return value.trim() || null;
}

function normalizeOptionalNonNegativeNumber(value, fieldName) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  const num = Number(value);
  if (!Number.isFinite(num) || num < 0) {
    throw new Error(`${fieldName} must be a non-negative number.`);
  }
  return num;
}

function normalizeOptionalAddressFilter(value, fieldName) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  const values = Array.isArray(value) ? value : [value];
  const normalized = values
    .filter((entry) => entry !== undefined && entry !== null && String(entry).trim())
    .map((entry) => normalizeAddress(entry, fieldName));
  return normalized.length > 0 ? normalized : null;
}

function assertMorphoMarketId(value, fieldName = "marketId") {
  const id = assertNonEmptyString(value, fieldName);
  if (!/^0x[a-fA-F0-9]{64}$/.test(id)) {
    throw new Error(`${fieldName} must be a 32-byte hex string.`);
  }
  return id;
}

function normalizeAaveOperation(value) {
  const operation = assertNonEmptyString(value, "operation").toLowerCase();
  if (!["supply", "withdraw", "borrow", "repay"].includes(operation)) {
    throw new Error("operation must be one of: supply, withdraw, borrow, repay.");
  }
  return operation;
}

function normalizeMorphoVaultOperation(value) {
  const operation = assertNonEmptyString(value, "operation").toLowerCase();
  if (!["supply", "withdraw"].includes(operation)) {
    throw new Error("operation must be one of: supply, withdraw.");
  }
  return operation;
}

function normalizeMorphoMarketOperation(value) {
  const operation = assertNonEmptyString(value, "operation").toLowerCase();
  if (!["supply_collateral", "borrow", "repay", "withdraw_collateral"].includes(operation)) {
    throw new Error(
      "operation must be one of: supply_collateral, borrow, repay, withdraw_collateral."
    );
  }
  return operation;
}

function normalizeLidoOperation(value) {
  const operation = assertNonEmptyString(value, "operation").toLowerCase();
  if (!["stake_eth_for_wsteth", "wrap_steth", "unwrap_wsteth"].includes(operation)) {
    throw new Error("operation must be one of: stake_eth_for_wsteth, wrap_steth, unwrap_wsteth.");
  }
  return operation;
}

function normalizeLidoWithdrawalOperation(value) {
  const operation = assertNonEmptyString(value, "operation").toLowerCase();
  if (!["request_withdrawal_steth", "request_withdrawal_wsteth", "claim_withdrawal"].includes(operation)) {
    throw new Error(
      "operation must be one of: request_withdrawal_steth, request_withdrawal_wsteth, claim_withdrawal."
    );
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

function normalizeVeloraTokenAddress(value, fieldName) {
  const raw = assertNonEmptyString(value, fieldName);
  const alias = raw.toLowerCase();
  if (
    alias === "native" ||
    alias === "eth" ||
    alias === "ethereum" ||
    isZeroAddress(raw) ||
    isVeloraNativeTokenAddress(raw)
  ) {
    return VELORA_NATIVE_TOKEN_ADDRESS;
  }
  return normalizeAddress(raw, fieldName);
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

function normalizeUniswapTokenAddress(value, fieldName) {
  return normalizeEvmTokenAddressAllowingNative(value, fieldName);
}

function assertUniswapSupportedNetwork(network) {
  const chainId = UNISWAP_SUPPORTED_CHAIN_IDS[network];
  if (!chainId) {
    throw new Error(
      "Uniswap Trading API swaps are currently supported only on ethereum, base, and robinhood mainnet."
    );
  }
  return chainId;
}

function uniswapSlippagePercentFromBps(bps) {
  const parsed = Number(bps);
  if (!Number.isInteger(parsed) || parsed < 0 || parsed > 5000) {
    throw new Error("slippageBps must be an integer between 0 and 5000.");
  }
  return parsed / 100;
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

function assertPlainObject(value, fieldName) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${fieldName} must be an object.`);
  }
  return value;
}

function normalizeX402ExactTypedData({ domain, types, primaryType, message }, runtimeConfig) {
  const normalizedPrimaryType = assertNonEmptyString(primaryType, "primaryType");
  if (normalizedPrimaryType !== "TransferWithAuthorization") {
    throw new Error("primaryType must be TransferWithAuthorization for x402 exact EVM payments.");
  }

  const domainObject = assertPlainObject(domain, "domain");
  const domainChainId = assertNonNegativeInteger(domainObject.chainId, "domain.chainId");
  if (domainChainId !== runtimeConfig.chainId) {
    throw new Error("domain.chainId must match the active network chain id.");
  }
  const normalizedDomain = {
    name: assertNonEmptyString(domainObject.name, "domain.name"),
    version: assertNonEmptyString(domainObject.version, "domain.version"),
    chainId: domainChainId,
    verifyingContract: normalizeAddress(domainObject.verifyingContract, "domain.verifyingContract"),
  };

  const typesObject = assertPlainObject(types, "types");
  const primaryFields = typesObject[normalizedPrimaryType];
  if (!Array.isArray(primaryFields) || primaryFields.length === 0) {
    throw new Error(`types.${normalizedPrimaryType} must be a non-empty array.`);
  }
  const normalizedTypes = {};
  for (const [typeName, fields] of Object.entries(typesObject)) {
    if (!Array.isArray(fields) || fields.length === 0) {
      throw new Error(`types.${typeName} must be a non-empty array.`);
    }
    normalizedTypes[typeName] = fields.map((field, index) => {
      const normalizedField = assertPlainObject(field, `types.${typeName}[${index}]`);
      return {
        name: assertNonEmptyString(normalizedField.name, `types.${typeName}[${index}].name`),
        type: assertNonEmptyString(normalizedField.type, `types.${typeName}[${index}].type`),
      };
    });
  }

  const messageObject = assertPlainObject(message, "message");
  const normalizedMessage = {
    from: normalizeAddress(messageObject.from, "message.from"),
    to: normalizeAddress(messageObject.to, "message.to"),
    value: assertPositiveBigIntString(messageObject.value, "message.value").toString(),
    validAfter: assertNonNegativeBigIntString(messageObject.validAfter, "message.validAfter"),
    validBefore: assertPositiveBigIntString(messageObject.validBefore, "message.validBefore").toString(),
    nonce: assertNonEmptyString(messageObject.nonce, "message.nonce"),
  };
  if (!/^0x[a-fA-F0-9]{64}$/.test(normalizedMessage.nonce)) {
    throw new Error("message.nonce must be a 32-byte hex string.");
  }

  return {
    domain: normalizedDomain,
    types: normalizedTypes,
    primaryType: normalizedPrimaryType,
    message: normalizedMessage,
  };
}

function normalizeUniswapPermitData(permitData, runtimeConfig) {
  const data = assertPlainObject(permitData, "permitData");
  const domain = assertPlainObject(data.domain, "permitData.domain");
  const domainChainId = assertNonNegativeInteger(domain.chainId, "permitData.domain.chainId");
  if (domainChainId !== runtimeConfig.chainId) {
    throw new Error("permitData.domain.chainId must match the active network chain id.");
  }
  const typesObject = assertPlainObject(data.types, "permitData.types");
  const normalizedTypes = {};
  for (const [typeName, fields] of Object.entries(typesObject)) {
    if (typeName === "EIP712Domain") {
      continue; // ethers infers the domain type; including it throws.
    }
    if (!Array.isArray(fields) || fields.length === 0) {
      throw new Error(`permitData.types.${typeName} must be a non-empty array.`);
    }
    normalizedTypes[typeName] = fields.map((field, index) => {
      const normalizedField = assertPlainObject(field, `permitData.types.${typeName}[${index}]`);
      return {
        name: assertNonEmptyString(normalizedField.name, `permitData.types.${typeName}[${index}].name`),
        type: assertNonEmptyString(normalizedField.type, `permitData.types.${typeName}[${index}].type`),
      };
    });
  }
  if (Object.keys(normalizedTypes).length === 0) {
    throw new Error("permitData.types must contain at least one non-domain type.");
  }
  const message = assertPlainObject(data.values, "permitData.values");
  return { domain, types: normalizedTypes, message };
}

function buildSwapRequest({ tokenIn, tokenOut, tokenInAmount }) {
  const swapRequest = {
    tokenIn: normalizeVeloraTokenAddress(tokenIn, "tokenIn"),
    tokenOut: normalizeVeloraTokenAddress(tokenOut, "tokenOut"),
    tokenInAmount: assertPositiveBigIntString(tokenInAmount, "tokenInAmount"),
  };
  assertDistinctAddresses(swapRequest.tokenIn, "tokenIn", swapRequest.tokenOut, "tokenOut");
  return swapRequest;
}

function buildUniswapSwapRequest({ tokenIn, tokenOut, tokenInAmount, slippageBps }) {
  const swapRequest = {
    tokenIn: normalizeUniswapTokenAddress(tokenIn, "tokenIn"),
    tokenOut: normalizeUniswapTokenAddress(tokenOut, "tokenOut"),
    tokenInAmount: assertPositiveBigIntString(tokenInAmount, "tokenInAmount"),
    slippagePercent: uniswapSlippagePercentFromBps(slippageBps),
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

function parseOptionalPositiveBigIntString(value, fieldName) {
  if (value === undefined || value === null || value === "") {
    return null;
  }
  return assertPositiveBigIntString(value, fieldName);
}

function normalizeMorphoVaultTarget({ vaultAddress, vaultPreset }) {
  const normalizedVaultAddress = vaultAddress ? normalizeAddress(vaultAddress, "vaultAddress") : null;
  const normalizedVaultPreset =
    vaultPreset !== undefined && vaultPreset !== null && String(vaultPreset).trim()
      ? assertNonEmptyString(vaultPreset, "vaultPreset")
      : null;
  if (normalizedVaultAddress && normalizedVaultPreset) {
    throw new Error("Provide either vaultAddress or vaultPreset, not both.");
  }
  if (!normalizedVaultAddress && !normalizedVaultPreset) {
    throw new Error("vaultAddress or vaultPreset is required.");
  }
  return {
    vaultAddress: normalizedVaultAddress,
    vaultPreset: normalizedVaultPreset,
  };
}

function normalizeMorphoMarketTarget({ marketId, marketPreset }) {
  const normalizedMarketId =
    marketId === undefined || marketId === null || marketId === ""
      ? null
      : assertMorphoMarketId(marketId, "marketId");
  const normalizedMarketPreset =
    marketPreset !== undefined && marketPreset !== null && String(marketPreset).trim()
      ? assertNonEmptyString(marketPreset, "marketPreset")
      : null;
  if (normalizedMarketId && normalizedMarketPreset) {
    throw new Error("Provide either marketId or marketPreset, not both.");
  }
  if (!normalizedMarketId && !normalizedMarketPreset) {
    throw new Error("marketId or marketPreset is required.");
  }
  return {
    marketId: normalizedMarketId,
    marketPreset: normalizedMarketPreset,
  };
}

function buildMorphoVaultOperationRequest({
  operation,
  vaultAddress,
  vaultPreset,
  token,
  tokenAddress,
  amount,
  nativeAmount,
  onBehalfOf,
  to,
}) {
  if (onBehalfOf !== undefined && onBehalfOf !== null && String(onBehalfOf).trim()) {
    throw new Error("Morpho delegated onBehalfOf operations are not exposed by this local wallet runtime.");
  }
  if (to !== undefined && to !== null && String(to).trim()) {
    throw new Error("Morpho third-party withdraw destinations are not exposed by this local wallet runtime.");
  }
  const preferredToken = tokenAddress ?? token;
  if (tokenAddress && token && String(tokenAddress).toLowerCase() !== String(token).toLowerCase()) {
    throw new Error("tokenAddress and token must refer to the same address.");
  }
  const request = {
    target: normalizeMorphoVaultTarget({ vaultAddress, vaultPreset }),
    operation: normalizeMorphoVaultOperation(operation),
    token: normalizeAddress(preferredToken, "tokenAddress"),
  };
  if (request.operation === "supply") {
    const supplyAmount = parseOptionalPositiveBigIntString(amount, "amount");
    const supplyNativeAmount = parseOptionalPositiveBigIntString(nativeAmount, "nativeAmount");
    if (supplyAmount === null && supplyNativeAmount === null) {
      throw new Error("amount or nativeAmount is required for Morpho vault supply.");
    }
    return {
      ...request,
      amount: supplyAmount,
      nativeAmount: supplyNativeAmount,
    };
  }
  return {
    ...request,
    amount: assertPositiveBigIntString(amount, "amount"),
  };
}

function buildMorphoMarketOperationRequest({
  operation,
  marketId,
  marketPreset,
  token,
  tokenAddress,
  amount,
  nativeAmount,
  onBehalfOf,
  to,
}) {
  if (onBehalfOf !== undefined && onBehalfOf !== null && String(onBehalfOf).trim()) {
    throw new Error("Morpho delegated onBehalfOf operations are not exposed by this local wallet runtime.");
  }
  if (to !== undefined && to !== null && String(to).trim()) {
    throw new Error("Morpho third-party withdraw destinations are not exposed by this local wallet runtime.");
  }
  const preferredToken = tokenAddress ?? token;
  if (tokenAddress && token && String(tokenAddress).toLowerCase() !== String(token).toLowerCase()) {
    throw new Error("tokenAddress and token must refer to the same address.");
  }
  const request = {
    target: normalizeMorphoMarketTarget({ marketId, marketPreset }),
    operation: normalizeMorphoMarketOperation(operation),
    token: normalizeAddress(preferredToken, "tokenAddress"),
  };
  if (request.operation === "repay") {
    const normalizedAmount = String(amount ?? "").trim().toLowerCase();
    return {
      ...request,
      amount:
        normalizedAmount === "max"
          ? "max"
          : assertPositiveBigIntString(amount, "amount"),
      nativeAmount: null,
    };
  }
  if (request.operation === "supply_collateral") {
    const collateralAmount = parseOptionalPositiveBigIntString(amount, "amount");
    const collateralNativeAmount = parseOptionalPositiveBigIntString(nativeAmount, "nativeAmount");
    if (collateralAmount === null && collateralNativeAmount === null) {
      throw new Error("amount or nativeAmount is required for Morpho market supply_collateral.");
    }
    return {
      ...request,
      amount: collateralAmount,
      nativeAmount: collateralNativeAmount,
    };
  }
  return {
    ...request,
    amount: assertPositiveBigIntString(amount, "amount"),
    nativeAmount: null,
  };
}

function buildLidoOperationRequest({ operation, amount }) {
  return {
    operation: normalizeLidoOperation(operation),
    amount: assertPositiveBigIntString(amount, "amount"),
  };
}

function buildLidoWithdrawalRequest({ operation, amount, requestId }) {
  const normalizedOperation = normalizeLidoWithdrawalOperation(operation);
  if (normalizedOperation === "claim_withdrawal") {
    const normalizedRequestId = String(requestId ?? "").trim();
    if (!/^[0-9]+$/.test(normalizedRequestId) || BigInt(normalizedRequestId) <= 0n) {
      throw new Error("requestId must be a positive base-10 integer string.");
    }
    return {
      operation: normalizedOperation,
      requestId: BigInt(normalizedRequestId),
    };
  }
  return {
    operation: normalizedOperation,
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

function withLidoMetadataDefaults(metadata, defaults) {
  const resolved = metadata && typeof metadata === "object" ? { ...metadata } : {};
  return {
    address: String(resolved.address || defaults.address).toLowerCase(),
    name: resolved.name || defaults.name,
    symbol: resolved.symbol || defaults.symbol,
    decimals: Number.isInteger(resolved.decimals) ? resolved.decimals : defaults.decimals,
    verified: resolved.verified === true,
    source: resolved.source || "lido-catalog",
  };
}

async function fetchJson(url, { headers = {} } = {}) {
  let response;
  try {
    response = await fetch(url, {
      headers: {
        Accept: "application/json",
        ...headers,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw createTaggedError(`HTTP network unavailable: ${message}`, "network_unavailable", {
      url,
    });
  }
  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw createTaggedError(`HTTP returned invalid JSON: ${message}`, "network_unavailable", {
      url,
      httpStatus: response.status,
    });
  }
  if (!response.ok) {
    throw createTaggedError(`HTTP request failed with status ${response.status}.`, "network_unavailable", {
      url,
      httpStatus: response.status,
      payload,
    });
  }
  return payload;
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

async function ethCallTransaction(providerUrl, tx) {
  return rpcRequest(providerUrl, "eth_call", [tx, "latest"]);
}

async function callContract(providerUrl, to, contractInterface, functionName, args = [], txOverrides = {}) {
  const data = contractInterface.encodeFunctionData(functionName, args);
  const raw = await ethCallTransaction(providerUrl, {
    to,
    data,
    ...txOverrides,
  });
  return contractInterface.decodeFunctionResult(functionName, raw);
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

  async getMorphoVaults({
    network,
    vaultAddress = null,
    limit,
    listedOnly = true,
    assetAddress = null,
    minTotalAssetsUsd = null,
    minNetApy = null,
    orderBy,
    orderDirection,
  }) {
    const runtimeConfig = this.#resolveRuntimeConfig(network);
    assertMorphoSupportedNetwork(runtimeConfig.network);
    if (vaultAddress !== null && vaultAddress !== undefined && String(vaultAddress).trim()) {
      const address = normalizeAddress(vaultAddress, "vaultAddress");
      const cacheKey = JSON.stringify(["vault", runtimeConfig.chainId, address]);
      const cached = morphoDiscoveryCacheGet(cacheKey);
      if (cached) {
        return cached;
      }
      const data = await this.#morphoGraphqlRequest({
        query: MORPHO_VAULT_BY_ADDRESS_QUERY,
        variables: {
          address,
          chainId: runtimeConfig.chainId,
        },
        operationName: "MorphoVaultV2ByAddress",
      });
      const result = {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        protocol: "morpho",
        vault: data.vaultV2ByAddress || null,
        found: Boolean(data.vaultV2ByAddress),
        source: "morpho-api",
      };
      morphoDiscoveryCacheSet(cacheKey, result);
      return result;
    }
    const first = normalizeMorphoListLimit(limit);
    const onlyListed = normalizeMorphoListedOnly(listedOnly);
    const assetAddressFilter = normalizeOptionalAddressFilter(assetAddress, "assetAddress");
    const minTotalAssetsUsdFilter = normalizeOptionalNonNegativeNumber(
      minTotalAssetsUsd,
      "minTotalAssetsUsd"
    );
    const minNetApyFilter = normalizeOptionalNonNegativeNumber(minNetApy, "minNetApy");
    const resolvedOrderBy = normalizeMorphoOrderBy(
      orderBy,
      MORPHO_VAULT_ORDER_LOOKUP,
      "TotalAssetsUsd"
    );
    const resolvedOrderDirection = normalizeMorphoOrderDirection(orderDirection);
    const where = { chainId_in: [runtimeConfig.chainId] };
    if (onlyListed) {
      where.listed = true;
    }
    if (assetAddressFilter) {
      where.assetAddress_in = assetAddressFilter;
    }
    if (minTotalAssetsUsdFilter !== null) {
      where.totalAssetsUsd_gte = minTotalAssetsUsdFilter;
    }
    if (minNetApyFilter !== null) {
      where.netApy_gte = minNetApyFilter;
    }
    const variables = {
      first,
      where,
      orderBy: resolvedOrderBy,
      orderDirection: resolvedOrderDirection,
    };
    const cacheKey = JSON.stringify(["vaults", variables]);
    const cached = morphoDiscoveryCacheGet(cacheKey);
    if (cached) {
      return cached;
    }
    const data = await this.#morphoGraphqlRequest({
      query: MORPHO_VAULT_LIST_QUERY,
      variables,
      operationName: "MorphoVaultV2List",
    });
    const vaults = Array.isArray(data?.vaultV2s?.items) ? data.vaultV2s.items : [];
    const result = {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      protocol: "morpho",
      listedOnly: onlyListed,
      requestedLimit: first,
      orderBy: resolvedOrderBy,
      orderDirection: resolvedOrderDirection,
      assetAddressFilter,
      minTotalAssetsUsd: minTotalAssetsUsdFilter,
      minNetApy: minNetApyFilter,
      vaultCount: vaults.length,
      vaults,
      source: "morpho-api",
    };
    morphoDiscoveryCacheSet(cacheKey, result);
    return result;
  }

  async getMorphoMarkets({
    network,
    marketId = null,
    limit,
    listedOnly = true,
    search,
    collateralAssetAddress = null,
    loanAssetAddress = null,
    minSupplyAssetsUsd = null,
    minNetSupplyApy = null,
    orderBy,
    orderDirection,
  }) {
    const runtimeConfig = this.#resolveRuntimeConfig(network);
    assertMorphoSupportedNetwork(runtimeConfig.network);
    if (marketId !== null && marketId !== undefined && String(marketId).trim()) {
      const normalizedMarketId = assertMorphoMarketId(marketId, "marketId");
      const cacheKey = JSON.stringify(["market", runtimeConfig.chainId, normalizedMarketId]);
      const cached = morphoDiscoveryCacheGet(cacheKey);
      if (cached) {
        return cached;
      }
      const data = await this.#morphoGraphqlRequest({
        query: MORPHO_MARKET_BY_ID_QUERY,
        variables: {
          marketId: normalizedMarketId,
          chainId: runtimeConfig.chainId,
        },
        operationName: "MorphoMarketById",
      });
      const result = {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        protocol: "morpho",
        market: data.marketById || null,
        found: Boolean(data.marketById),
        source: "morpho-api",
      };
      morphoDiscoveryCacheSet(cacheKey, result);
      return result;
    }
    const first = normalizeMorphoListLimit(limit);
    const onlyListed = normalizeMorphoListedOnly(listedOnly);
    const searchTerm = normalizeMorphoSearch(search);
    const collateralFilter = normalizeOptionalAddressFilter(
      collateralAssetAddress,
      "collateralAssetAddress"
    );
    const loanFilter = normalizeOptionalAddressFilter(loanAssetAddress, "loanAssetAddress");
    const minSupplyAssetsUsdFilter = normalizeOptionalNonNegativeNumber(
      minSupplyAssetsUsd,
      "minSupplyAssetsUsd"
    );
    const minNetSupplyApyFilter = normalizeOptionalNonNegativeNumber(
      minNetSupplyApy,
      "minNetSupplyApy"
    );
    const resolvedOrderBy = normalizeMorphoOrderBy(
      orderBy,
      MORPHO_MARKET_ORDER_LOOKUP,
      "SupplyAssetsUsd"
    );
    const resolvedOrderDirection = normalizeMorphoOrderDirection(orderDirection);
    const where = { chainId_in: [runtimeConfig.chainId] };
    if (onlyListed) {
      where.listed = true;
    }
    if (searchTerm) {
      where.search = searchTerm;
    }
    if (collateralFilter) {
      where.collateralAssetAddress_in = collateralFilter;
    }
    if (loanFilter) {
      where.loanAssetAddress_in = loanFilter;
    }
    if (minSupplyAssetsUsdFilter !== null) {
      where.supplyAssetsUsd_gte = minSupplyAssetsUsdFilter;
    }
    if (minNetSupplyApyFilter !== null) {
      where.netSupplyApy_gte = minNetSupplyApyFilter;
    }
    const variables = {
      first,
      where,
      orderBy: resolvedOrderBy,
      orderDirection: resolvedOrderDirection,
    };
    const cacheKey = JSON.stringify(["markets", variables]);
    const cached = morphoDiscoveryCacheGet(cacheKey);
    if (cached) {
      return cached;
    }
    const data = await this.#morphoGraphqlRequest({
      query: MORPHO_MARKET_LIST_QUERY,
      variables,
      operationName: "MorphoMarketList",
    });
    const markets = Array.isArray(data?.markets?.items) ? data.markets.items : [];
    const result = {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      protocol: "morpho",
      listedOnly: onlyListed,
      requestedLimit: first,
      orderBy: resolvedOrderBy,
      orderDirection: resolvedOrderDirection,
      search: searchTerm,
      collateralAssetFilter: collateralFilter,
      loanAssetFilter: loanFilter,
      minSupplyAssetsUsd: minSupplyAssetsUsdFilter,
      minNetSupplyApy: minNetSupplyApyFilter,
      marketCount: markets.length,
      markets,
      source: "morpho-api",
    };
    morphoDiscoveryCacheSet(cacheKey, result);
    return result;
  }

  async getMorphoPositions({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertMorphoSupportedNetwork(runtimeConfig.network);
        const accountAddress = await account.getAddress();
        const data = await this.#morphoGraphqlRequest({
          query: MORPHO_USER_OVERVIEW_QUERY,
          variables: {
            address: accountAddress,
            chainId: runtimeConfig.chainId,
          },
          operationName: "MorphoUserByAddress",
        });
        const user = data.userByAddress || null;
        const marketPositions = Array.isArray(user?.marketPositions) ? user.marketPositions : [];
        const vaultPositions = Array.isArray(user?.vaultV2Positions) ? user.vaultV2Positions : [];
        return {
          network: runtimeConfig.network,
          chainId: runtimeConfig.chainId,
          accountIndex,
          address: accountAddress,
          protocol: "morpho",
          marketPositionCount: marketPositions.length,
          vaultPositionCount: vaultPositions.length,
          marketPositions,
          vaultPositions,
          source: "morpho-api",
        };
      }
    );
  }

  async quoteMorphoVaultOperation({
    seedPhrase,
    address,
    operation,
    vaultAddress,
    vaultPreset,
    token,
    tokenAddress,
    amount,
    nativeAmount,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertMorphoSupportedNetwork(runtimeConfig.network);
        const request = buildMorphoVaultOperationRequest({
          operation,
          vaultAddress,
          vaultPreset,
          token,
          tokenAddress,
          amount,
          nativeAmount,
        });
        const accountAddress = await account.getAddress();
        const plan = await this.#buildMorphoOperationPlan({
          account,
          runtimeConfig,
          address: accountAddress,
          request,
          tolerateOperationFeeFailure: true,
        });
        return this.#formatMorphoOperationResponse({
          runtimeConfig,
          accountIndex,
          address: accountAddress,
          request,
          plan,
        });
      }
    );
  }

  async sendMorphoVaultOperation({
    seedPhrase,
    operation,
    vaultAddress,
    vaultPreset,
    token,
    tokenAddress,
    amount,
    nativeAmount,
    accountIndex = 0,
    network,
    expectedQuoteFingerprint = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertMorphoSupportedNetwork(runtimeConfig.network);
      const request = buildMorphoVaultOperationRequest({
        operation,
        vaultAddress,
        vaultPreset,
        token,
        tokenAddress,
        amount,
        nativeAmount,
      });
      const normalizedExpectedQuoteFingerprint =
        typeof expectedQuoteFingerprint === "string" && expectedQuoteFingerprint.trim()
          ? expectedQuoteFingerprint.trim()
          : null;
      const address = await account.getAddress();
      let initialPlan = await this.#buildMorphoOperationPlan({
        account,
        runtimeConfig,
        address,
        request,
        tolerateOperationFeeFailure: true,
      });
      this.#assertExpectedMorphoFingerprint(
        normalizedExpectedQuoteFingerprint,
        initialPlan.quoteFingerprint
      );
      const requirementExecution = await this.#executeMorphoRequirementsIfNeeded({
        account,
        runtimeConfig,
        request,
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (requirementExecution.performed) {
          finalPlan = await this.#buildMorphoOperationPlan({
            account,
            runtimeConfig,
            address,
            request,
          });
          this.#assertExpectedMorphoFingerprint(
            normalizedExpectedQuoteFingerprint,
            finalPlan.quoteFingerprint
          );
        }

        if (finalPlan.requirements.required) {
          throw createTaggedError(
            "Morpho operation still requires prerequisite transactions after the requirement step completed.",
            "morpho_requirements_unresolved",
            {
              requirementCount: finalPlan.requirements.steps.length,
              requirements: finalPlan.requirements.steps,
            }
          );
        }

        if (finalPlan.operationFee === null) {
          throw createTaggedError(
            "Morpho operation fee estimate was unavailable. Generate a new quote before sending.",
            "morpho_fee_unavailable",
            {
              operation: request.operation,
              feeEstimateError: finalPlan.operationFeeError,
            }
          );
        }

        const protocol = this.#createMorphoProtocol(account, runtimeConfig, request);
        let result;
        try {
          result = await protocol[this.#getMorphoOperationMethods(request).sendMethod](
            this.#buildMorphoOperationOptions(request)
          );
        } finally {
          await maybeDispose(protocol);
        }
        const resultFee = BigInt(result?.fee || finalPlan.operationFee || 0);
        const totalFee = requirementExecution.totalFee + resultFee;
        return {
          ...this.#formatMorphoOperationResponse({
            runtimeConfig,
            accountIndex,
            address,
            request,
            plan: {
              ...finalPlan,
              operationFee: resultFee,
              totalEstimatedFee: totalFee,
              requirements: {
                ...finalPlan.requirements,
                estimatedFee: requirementExecution.totalFee,
              },
            },
          }),
          result: {
            ...result,
            fee: resultFee.toString(),
            totalFee: totalFee.toString(),
            requirementsFee: requirementExecution.totalFee.toString(),
            requirements: requirementExecution.transactions,
          },
        };
      } catch (error) {
        const cleanup = await this.#restoreMorphoRequirementsAfterFailedOperation({
          account,
          runtimeConfig,
          request,
          plan: initialPlan,
          requirementExecution,
        });
        this.#throwMorphoFailureWithCleanup(error, cleanup);
      }
    });
  }

  async quoteMorphoMarketOperation({
    seedPhrase,
    address,
    operation,
    marketId,
    marketPreset,
    token,
    tokenAddress,
    amount,
    nativeAmount,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertMorphoSupportedNetwork(runtimeConfig.network);
        const request = buildMorphoMarketOperationRequest({
          operation,
          marketId,
          marketPreset,
          token,
          tokenAddress,
          amount,
          nativeAmount,
        });
        const accountAddress = await account.getAddress();
        const plan = await this.#buildMorphoOperationPlan({
          account,
          runtimeConfig,
          address: accountAddress,
          request,
          tolerateOperationFeeFailure: true,
        });
        return this.#formatMorphoOperationResponse({
          runtimeConfig,
          accountIndex,
          address: accountAddress,
          request,
          plan,
        });
      }
    );
  }

  async sendMorphoMarketOperation({
    seedPhrase,
    operation,
    marketId,
    marketPreset,
    token,
    tokenAddress,
    amount,
    nativeAmount,
    accountIndex = 0,
    network,
    expectedQuoteFingerprint = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertMorphoSupportedNetwork(runtimeConfig.network);
      const request = buildMorphoMarketOperationRequest({
        operation,
        marketId,
        marketPreset,
        token,
        tokenAddress,
        amount,
        nativeAmount,
      });
      const normalizedExpectedQuoteFingerprint =
        typeof expectedQuoteFingerprint === "string" && expectedQuoteFingerprint.trim()
          ? expectedQuoteFingerprint.trim()
          : null;
      const address = await account.getAddress();
      let initialPlan = await this.#buildMorphoOperationPlan({
        account,
        runtimeConfig,
        address,
        request,
        tolerateOperationFeeFailure: true,
      });
      this.#assertExpectedMorphoFingerprint(
        normalizedExpectedQuoteFingerprint,
        initialPlan.quoteFingerprint
      );
      const requirementExecution = await this.#executeMorphoRequirementsIfNeeded({
        account,
        runtimeConfig,
        request,
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (requirementExecution.performed) {
          finalPlan = await this.#buildMorphoOperationPlan({
            account,
            runtimeConfig,
            address,
            request,
          });
          this.#assertExpectedMorphoFingerprint(
            normalizedExpectedQuoteFingerprint,
            finalPlan.quoteFingerprint
          );
        }

        if (finalPlan.requirements.required) {
          throw createTaggedError(
            "Morpho operation still requires prerequisite transactions after the requirement step completed.",
            "morpho_requirements_unresolved",
            {
              requirementCount: finalPlan.requirements.steps.length,
              requirements: finalPlan.requirements.steps,
            }
          );
        }

        if (finalPlan.operationFee === null) {
          throw createTaggedError(
            "Morpho operation fee estimate was unavailable. Generate a new quote before sending.",
            "morpho_fee_unavailable",
            {
              operation: request.operation,
              feeEstimateError: finalPlan.operationFeeError,
            }
          );
        }

        const protocol = this.#createMorphoProtocol(account, runtimeConfig, request);
        let result;
        try {
          result = await protocol[this.#getMorphoOperationMethods(request).sendMethod](
            this.#buildMorphoOperationOptions(request)
          );
        } finally {
          await maybeDispose(protocol);
        }
        const resultFee = BigInt(result?.fee || finalPlan.operationFee || 0);
        const totalFee = requirementExecution.totalFee + resultFee;
        return {
          ...this.#formatMorphoOperationResponse({
            runtimeConfig,
            accountIndex,
            address,
            request,
            plan: {
              ...finalPlan,
              operationFee: resultFee,
              totalEstimatedFee: totalFee,
              requirements: {
                ...finalPlan.requirements,
                estimatedFee: requirementExecution.totalFee,
              },
            },
          }),
          result: {
            ...result,
            fee: resultFee.toString(),
            totalFee: totalFee.toString(),
            requirementsFee: requirementExecution.totalFee.toString(),
            requirements: requirementExecution.transactions,
          },
        };
      } catch (error) {
        const cleanup = await this.#restoreMorphoRequirementsAfterFailedOperation({
          account,
          runtimeConfig,
          request,
          plan: initialPlan,
          requirementExecution,
        });
        this.#throwMorphoFailureWithCleanup(error, cleanup);
      }
    });
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

  async getLidoOverview({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertLidoSupportedNetwork(runtimeConfig.network);
        const contracts = this.#getLidoContracts(runtimeConfig.network);
        const [stEthMetadata, wstEthMetadata, rates, stakingAprResult] = await Promise.all([
          this.#getLidoTokenMetadata(runtimeConfig, contracts.steth),
          this.#getLidoTokenMetadata(runtimeConfig, contracts.wsteth),
          this.#readLidoSampleRates(runtimeConfig),
          this.#readLidoStakingApr(runtimeConfig),
        ]);
        return {
          network: runtimeConfig.network,
          chainId: runtimeConfig.chainId,
          accountIndex,
          protocol: "lido",
          preferredPositionToken: "wstETH",
          stakingAsset: {
            type: "native",
            symbol: runtimeConfig.nativeSymbol,
            decimals: 18,
          },
          referralAddress: this.#getLidoReferralAddress(),
          contracts: {
            stETH: contracts.steth.address,
            wstETH: contracts.wsteth.address,
            referralStaker: contracts.referralStaker,
            withdrawalQueue: contracts.withdrawalQueue,
          },
          stEthMetadata,
          wstEthMetadata,
          sampleRates: rates,
          stakingApr: stakingAprResult.data,
          stakingAprError: stakingAprResult.error,
          withdrawalLimits: {
            minStEthAmountRaw: LIDO_MIN_STETH_WITHDRAWAL_AMOUNT.toString(),
            minStEthAmountFormatted: formatUnits(LIDO_MIN_STETH_WITHDRAWAL_AMOUNT, LIDO_STETH_DECIMALS),
            maxStEthAmountRaw: LIDO_MAX_STETH_WITHDRAWAL_AMOUNT.toString(),
            maxStEthAmountFormatted: formatUnits(LIDO_MAX_STETH_WITHDRAWAL_AMOUNT, LIDO_STETH_DECIMALS),
          },
          source: "lido-contracts",
        };
      }
    );
  }

  async getLidoPositions({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertLidoSupportedNetwork(runtimeConfig.network);
        const accountAddress = await account.getAddress();
        const contracts = this.#getLidoContracts(runtimeConfig.network);
        const [nativeBalance, stEthMetadata, wstEthMetadata, stEthBalance, wstEthBalance] = await Promise.all([
          account.getBalance(),
          this.#getLidoTokenMetadata(runtimeConfig, contracts.steth),
          this.#getLidoTokenMetadata(runtimeConfig, contracts.wsteth),
          this.#readTokenBalanceWithFallback({
            account,
            runtimeConfig,
            tokenAddress: contracts.steth.address,
            ownerAddress: accountAddress,
          }),
          this.#readTokenBalanceWithFallback({
            account,
            runtimeConfig,
            tokenAddress: contracts.wsteth.address,
            ownerAddress: accountAddress,
          }),
        ]);
        const wstEthAsStEth = await this.#quoteLidoOutputRaw({
          runtimeConfig,
          operation: "unwrap_wsteth",
          amount: wstEthBalance,
          fromAddress: accountAddress,
        });
        const stEthEquivalentTotal = stEthBalance + wstEthAsStEth;
        const positions = [];
        if (stEthBalance > 0n) {
          positions.push({
            asset: "stETH",
            tokenAddress: contracts.steth.address,
            tokenMetadata: stEthMetadata,
            balanceRaw: stEthBalance.toString(),
            balanceFormatted: formatUnits(stEthBalance, stEthMetadata.decimals),
            stEthEquivalentRaw: stEthBalance.toString(),
            stEthEquivalentFormatted: formatUnits(stEthBalance, stEthMetadata.decimals),
          });
        }
        if (wstEthBalance > 0n) {
          positions.push({
            asset: "wstETH",
            tokenAddress: contracts.wsteth.address,
            tokenMetadata: wstEthMetadata,
            balanceRaw: wstEthBalance.toString(),
            balanceFormatted: formatUnits(wstEthBalance, wstEthMetadata.decimals),
            stEthEquivalentRaw: wstEthAsStEth.toString(),
            stEthEquivalentFormatted: formatUnits(wstEthAsStEth, stEthMetadata.decimals),
          });
        }
        return {
          network: runtimeConfig.network,
          chainId: runtimeConfig.chainId,
          accountIndex,
          address: accountAddress,
          protocol: "lido",
          preferredPositionToken: "wstETH",
          contracts: {
            stETH: contracts.steth.address,
            wstETH: contracts.wsteth.address,
            referralStaker: contracts.referralStaker,
            withdrawalQueue: contracts.withdrawalQueue,
          },
          nativeBalanceWei: BigInt(nativeBalance || 0).toString(),
          nativeBalanceFormatted: formatUnits(BigInt(nativeBalance || 0), 18),
          stEthEquivalentTotalRaw: stEthEquivalentTotal.toString(),
          stEthEquivalentTotalFormatted: formatUnits(stEthEquivalentTotal, stEthMetadata.decimals),
          positionCount: positions.length,
          positions,
          source: "lido-contracts",
        };
      }
    );
  }

  async getLidoWithdrawalRequests({ seedPhrase, address, accountIndex = 0, network }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertLidoSupportedNetwork(runtimeConfig.network);
        const accountAddress = await account.getAddress();
        const contracts = this.#getLidoContracts(runtimeConfig.network);
        const [stEthMetadata, wstEthMetadata, requestIds] = await Promise.all([
          this.#getLidoTokenMetadata(runtimeConfig, contracts.steth),
          this.#getLidoTokenMetadata(runtimeConfig, contracts.wsteth),
          this.#getLidoWithdrawalRequestIds(runtimeConfig, accountAddress),
        ]);
        const statuses = requestIds.length
          ? await this.#getLidoWithdrawalStatuses(runtimeConfig, requestIds)
          : [];
        const requests = statuses.map((status) =>
          this.#formatLidoWithdrawalStatus(status, stEthMetadata, wstEthMetadata)
        );
        const claimableCount = requests.filter((request) => request.claimable).length;
        return {
          network: runtimeConfig.network,
          chainId: runtimeConfig.chainId,
          accountIndex,
          address: accountAddress,
          protocol: "lido",
          withdrawalQueue: contracts.withdrawalQueue,
          requestCount: requests.length,
          claimableCount,
          requests,
          source: "lido-contracts",
        };
      }
    );
  }

  async quoteLidoOperation({
    seedPhrase,
    address,
    operation,
    amount,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertLidoSupportedNetwork(runtimeConfig.network);
        const request = buildLidoOperationRequest({ operation, amount });
        const accountAddress = await account.getAddress();
        const plan = await this.#buildLidoOperationPlan({
          account,
          runtimeConfig,
          address: accountAddress,
          request,
          tolerateOperationFeeFailure: true,
        });
        return this.#formatLidoOperationResponse({
          runtimeConfig,
          accountIndex,
          address: accountAddress,
          request,
          plan,
        });
      }
    );
  }

  async sendLidoOperation({
    seedPhrase,
    operation,
    amount,
    accountIndex = 0,
    network,
    expectedQuoteFingerprint = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertLidoSupportedNetwork(runtimeConfig.network);
      const request = buildLidoOperationRequest({ operation, amount });
      const normalizedExpectedQuoteFingerprint =
        typeof expectedQuoteFingerprint === "string" && expectedQuoteFingerprint.trim()
          ? expectedQuoteFingerprint.trim()
          : null;
      const address = await account.getAddress();
      let initialPlan = await this.#buildLidoOperationPlan({
        account,
        runtimeConfig,
        address,
        request,
        tolerateOperationFeeFailure: true,
      });
      this.#assertExpectedLidoFingerprint(
        normalizedExpectedQuoteFingerprint,
        initialPlan.quoteFingerprint
      );

      const approvalExecution = await this.#executeLidoApprovalsIfNeeded({
        account,
        runtimeConfig,
        request,
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (approvalExecution.performed) {
          finalPlan = await this.#buildLidoOperationPlan({
            account,
            runtimeConfig,
            address,
            request,
          });
          this.#assertExpectedLidoFingerprint(
            normalizedExpectedQuoteFingerprint,
            finalPlan.quoteFingerprint
          );
        }

        if (finalPlan.approval.required) {
          throw createTaggedError(
            "Lido operation still requires token approval after the approval step completed.",
            "lido_approval_required",
            {
              spender: finalPlan.spender,
              requiredAllowance: finalPlan.amount.toString(),
              currentAllowance: finalPlan.currentAllowance.toString(),
            }
          );
        }

        if (finalPlan.operationFee === null) {
          throw createTaggedError(
            "Lido operation fee estimate was unavailable. Generate a new quote before sending.",
            "lido_fee_unavailable",
            {
              operation: request.operation,
              feeEstimateError: finalPlan.operationFeeError,
            }
          );
        }

        const result = await account.sendTransaction(finalPlan.operationTx);
        const resultFee = BigInt(result?.fee || finalPlan.operationFee || 0);
        const totalFee = approvalExecution.totalFee + resultFee;
        return {
          ...this.#formatLidoOperationResponse({
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
        const cleanup = await this.#restoreAllowanceAfterFailedLidoOperation({
          account,
          runtimeConfig,
          tokenAddress: finalPlan.inputTokenAddress,
          spender: initialPlan.spender,
          originalAllowance: initialPlan.currentAllowance,
          approvalExecution,
        });
        this.#throwLidoFailureWithCleanup(error, cleanup);
      }
    });
  }

  async quoteLidoWithdrawalOperation({
    seedPhrase,
    address,
    operation,
    amount,
    requestId,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertLidoSupportedNetwork(runtimeConfig.network);
        const request = buildLidoWithdrawalRequest({ operation, amount, requestId });
        const accountAddress = await account.getAddress();
        const plan = await this.#buildLidoWithdrawalPlan({
          account,
          runtimeConfig,
          address: accountAddress,
          request,
          tolerateOperationFeeFailure: true,
        });
        return this.#formatLidoWithdrawalResponse({
          runtimeConfig,
          accountIndex,
          address: accountAddress,
          request,
          plan,
        });
      }
    );
  }

  async sendLidoWithdrawalOperation({
    seedPhrase,
    operation,
    amount,
    requestId,
    accountIndex = 0,
    network,
    expectedQuoteFingerprint = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertLidoSupportedNetwork(runtimeConfig.network);
      const request = buildLidoWithdrawalRequest({ operation, amount, requestId });
      const normalizedExpectedQuoteFingerprint =
        typeof expectedQuoteFingerprint === "string" && expectedQuoteFingerprint.trim()
          ? expectedQuoteFingerprint.trim()
          : null;
      const address = await account.getAddress();
      let initialPlan = await this.#buildLidoWithdrawalPlan({
        account,
        runtimeConfig,
        address,
        request,
        tolerateOperationFeeFailure: true,
      });
      this.#assertExpectedLidoWithdrawalFingerprint(
        normalizedExpectedQuoteFingerprint,
        initialPlan.quoteFingerprint
      );

      const approvalExecution = await this.#executeLidoWithdrawalApprovalsIfNeeded({
        account,
        runtimeConfig,
        request,
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (approvalExecution.performed) {
          finalPlan = await this.#buildLidoWithdrawalPlan({
            account,
            runtimeConfig,
            address,
            request,
          });
          this.#assertExpectedLidoWithdrawalFingerprint(
            normalizedExpectedQuoteFingerprint,
            finalPlan.quoteFingerprint
          );
        }

        if (finalPlan.approval.required) {
          throw createTaggedError(
            "Lido withdrawal still requires token approval after the approval step completed.",
            "lido_withdrawal_approval_required",
            {
              spender: finalPlan.spender,
              requiredAllowance: finalPlan.requiredAllowance.toString(),
              currentAllowance: finalPlan.currentAllowance.toString(),
            }
          );
        }

        if (finalPlan.operationFee === null) {
          throw createTaggedError(
            "Lido withdrawal fee estimate was unavailable. Generate a new quote before sending.",
            "lido_withdrawal_fee_unavailable",
            {
              operation: request.operation,
              feeEstimateError: finalPlan.operationFeeError,
            }
          );
        }

        const result = await account.sendTransaction(finalPlan.operationTx);
        const resultFee = BigInt(result?.fee || finalPlan.operationFee || 0);
        const totalFee = approvalExecution.totalFee + resultFee;
        return {
          ...this.#formatLidoWithdrawalResponse({
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
        const cleanup = await this.#restoreAllowanceAfterFailedLidoWithdrawal({
          account,
          runtimeConfig,
          tokenAddress: finalPlan.inputTokenAddress,
          spender: initialPlan.spender,
          originalAllowance: initialPlan.currentAllowance,
          approvalExecution,
        });
        this.#throwLidoWithdrawalFailureWithCleanup(error, cleanup);
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

  async quoteUniswapSwap({
    seedPhrase,
    address,
    tokenIn,
    tokenOut,
    tokenInAmount,
    slippageBps,
    accountIndex = 0,
    network,
  }) {
    return this.#withReadableAccount(
      { seedPhrase, address, accountIndex, network },
      async (account, runtimeConfig) => {
        assertUniswapSupportedNetwork(runtimeConfig.network);
        const swapRequest = buildUniswapSwapRequest({
          tokenIn,
          tokenOut,
          tokenInAmount,
          slippageBps:
            slippageBps === undefined || slippageBps === null
              ? this.config.uniswapDefaultSlippageBps
              : slippageBps,
        });
        const swapperAddress = await account.getAddress();
        const plan = await this.#buildUniswapSwapPlan({
          account,
          runtimeConfig,
          address: swapperAddress,
          swapRequest,
        });
        return this.#formatUniswapSwapResponse({
          runtimeConfig,
          accountIndex,
          address: swapperAddress,
          swapRequest,
          plan,
        });
      }
    );
  }

  async sendUniswapSwap({
    seedPhrase,
    tokenIn,
    tokenOut,
    tokenInAmount,
    slippageBps,
    accountIndex = 0,
    network,
    expectedQuoteFingerprint = null,
    minimumTokenOutAmount = null,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      assertUniswapSupportedNetwork(runtimeConfig.network);
      const swapRequest = buildUniswapSwapRequest({
        tokenIn,
        tokenOut,
        tokenInAmount,
        slippageBps:
          slippageBps === undefined || slippageBps === null
            ? this.config.uniswapDefaultSlippageBps
            : slippageBps,
      });
      const normalizedExpectedQuoteFingerprint =
        typeof expectedQuoteFingerprint === "string" && expectedQuoteFingerprint.trim()
          ? expectedQuoteFingerprint.trim()
          : null;
      const requestedMinimumTokenOutAmount =
        minimumTokenOutAmount !== null && minimumTokenOutAmount !== undefined
          ? assertPositiveBigIntString(minimumTokenOutAmount, "minimumTokenOutAmount")
          : null;
      const address = await account.getAddress();
      let initialPlan = await this.#buildUniswapSwapPlan({
        account,
        runtimeConfig,
        address,
        swapRequest,
      });
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
        swapRequest: { tokenIn: swapRequest.tokenIn },
        plan: initialPlan,
      });

      let finalPlan = initialPlan;
      try {
        if (approvalExecution.performed) {
          // Re-fetch after approval to obtain fresh permitData (the deadline/nonce are short-lived).
          finalPlan = await this.#buildUniswapSwapPlan({
            account,
            runtimeConfig,
            address,
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
            "Uniswap swap still requires token approval after the approval step completed.",
            "swap_approval_required",
            {
              spender: finalPlan.spender,
              requiredAllowance: finalPlan.tokenInAmount.toString(),
              currentAllowance: finalPlan.currentAllowance.toString(),
            }
          );
        }

        const signature =
          finalPlan.isNativeTokenIn || !finalPlan.permitData
            ? null
            : await this.#signUniswapPermit(account, finalPlan.permitData, runtimeConfig);

        const swapTx = await this.#fetchUniswapSwapCalldata({
          runtimeConfig,
          quoteResponse: finalPlan.quoteResponse,
          permitData: finalPlan.permitData,
          signature,
        });

        const simulation = await this.#simulatePreparedTransaction({
          runtimeConfig,
          from: address,
          tx: swapTx,
        });
        this.#assertSimulationSucceeded(simulation);

        const { hash } = await account.sendTransaction(swapTx);
        const result = {
          hash,
          approvalFee: approvalExecution.totalFee.toString(),
          tokenInAmount: finalPlan.tokenInAmount.toString(),
          tokenOutAmount: finalPlan.tokenOutAmount.toString(),
          ...(approvalExecution.approveHash ? { approveHash: approvalExecution.approveHash } : {}),
          ...(approvalExecution.resetAllowanceHash
            ? { resetAllowanceHash: approvalExecution.resetAllowanceHash }
            : {}),
        };
        return {
          ...(await this.#formatUniswapSwapResponse({
            runtimeConfig,
            accountIndex,
            address,
            swapRequest,
            plan: {
              ...finalPlan,
              approval: {
                ...finalPlan.approval,
                estimatedFee: approvalExecution.totalFee,
              },
            },
          })),
          simulation,
          swapTransaction: { to: swapTx.to, value: swapTx.value.toString(), dataHash: sha256Hex(swapTx.data) },
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

  async #getUniswapTokenMetadata(runtimeConfig, tokenAddress) {
    if (isZeroAddress(tokenAddress)) {
      return {
        address: ZERO_ADDRESS,
        name: runtimeConfig.nativeSymbol === "ETH" ? "Ether" : runtimeConfig.nativeSymbol,
        symbol: runtimeConfig.nativeSymbol,
        decimals: 18,
        verified: true,
        source: "native-asset",
      };
    }
    return this.#getTokenMetadata(runtimeConfig, tokenAddress);
  }

  async #formatUniswapSwapResponse({ runtimeConfig, accountIndex, address, swapRequest, plan }) {
    const [tokenInMetadata, tokenOutMetadata] = await Promise.all([
      this.#getUniswapTokenMetadata(runtimeConfig, swapRequest.tokenIn),
      this.#getUniswapTokenMetadata(runtimeConfig, swapRequest.tokenOut),
    ]);
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      accountIndex,
      address,
      protocol: "uniswap",
      executionSupported: true,
      routing: "CLASSIC",
      swapRequest: {
        tokenIn: swapRequest.tokenIn,
        tokenOut: swapRequest.tokenOut,
        tokenInAmount: swapRequest.tokenInAmount.toString(),
      },
      tokenInMetadata,
      tokenOutMetadata,
      inputAmountFormatted: formatUnits(swapRequest.tokenInAmount, tokenInMetadata.decimals),
      outputAmountFormatted: formatUnits(plan.tokenOutAmount, tokenOutMetadata.decimals),
      quoteFingerprint: plan.quoteFingerprint,
      slippageBps: plan.slippageBps,
      minimumOutputAmountRaw: plan.minimumTokenOutAmount.toString(),
      permitRequired: plan.permitData !== null,
      gasFeeWei: plan.gasFee,
      gasFeeUSD: plan.gasFeeUSD,
      estimatedApprovalFeeWei: plan.approval.estimatedFee.toString(),
      allowance: {
        spender: plan.spender,
        currentAllowance: plan.currentAllowance.toString(),
        requiredAllowance: plan.tokenInAmount.toString(),
        approvalRequired: plan.approval.required,
        approvalSequence: plan.approval.steps,
        readError: plan.allowanceReadError,
      },
      router: plan.router,
      source: "uniswap-trading-api",
    };
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

  async signX402ExactTypedData({
    seedPhrase,
    accountIndex = 0,
    network,
    domain,
    types,
    primaryType,
    message,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      const typedData = normalizeX402ExactTypedData(
        { domain, types, primaryType, message },
        runtimeConfig
      );
      const signerAddress = normalizeAddress(await account.getAddress(), "accountAddress");
      if (typedData.message.from.toLowerCase() !== signerAddress.toLowerCase()) {
        throw new Error("message.from must match the active wallet account address.");
      }
      const signature = await account.signTypedData({
        domain: typedData.domain,
        types: typedData.types,
        message: typedData.message,
      });
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        address: signerAddress,
        primaryType: typedData.primaryType,
        signature,
        source: "wdk-wallet-evm",
      };
    });
  }

  async signPersonalMessage({
    seedPhrase,
    accountIndex = 0,
    network,
    message,
  }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      if (typeof message !== "string" || message.length === 0) {
        throw new Error("message must be a non-empty string.");
      }
      const signerAddress = normalizeAddress(await account.getAddress(), "accountAddress");
      const signature = await account.sign(message);
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        address: signerAddress,
        signature,
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

  async #morphoGraphqlRequest({ query, variables = {}, operationName = null }) {
    const baseUrl = String(this.config.morphoApiBaseUrl || "https://api.morpho.org/graphql").trim();
    if (!baseUrl) {
      throw createTaggedError("Morpho API base URL is not configured.", "morpho_api_failed");
    }
    let response;
    try {
      response = await fetch(baseUrl, {
        method: "POST",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          query,
          variables,
          ...(operationName ? { operationName } : {}),
        }),
      });
    } catch (error) {
      throw createTaggedError(
        `Morpho API request failed: ${error instanceof Error ? error.message : String(error)}`,
        "network_unavailable",
        {
          provider: "morpho",
          endpoint: baseUrl,
          operationName,
        }
      );
    }

    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw createTaggedError(
        `Morpho API returned invalid JSON (HTTP ${response.status}).`,
        "morpho_api_failed",
        {
          provider: "morpho",
          endpoint: baseUrl,
          status: response.status,
          operationName,
        }
      );
    }

    if (!response.ok) {
      const message =
        Array.isArray(payload?.errors) && payload.errors.length > 0
          ? String(payload.errors[0]?.message || "").trim()
          : "";
      throw createTaggedError(
        message || `Morpho API request failed with HTTP ${response.status}.`,
        "morpho_api_failed",
        {
          provider: "morpho",
          endpoint: baseUrl,
          status: response.status,
          operationName,
          errors: Array.isArray(payload?.errors) ? payload.errors : [],
        }
      );
    }

    if (Array.isArray(payload?.errors) && payload.errors.length > 0) {
      const allNotFound = payload.errors.every(
        (entry) =>
          String(entry?.status || entry?.extensions?.code || "").toUpperCase() === "NOT_FOUND"
      );
      if (!allNotFound) {
        throw createTaggedError(
          String(payload.errors[0]?.message || "Morpho API query failed."),
          "morpho_api_failed",
          {
            provider: "morpho",
            endpoint: baseUrl,
            status: response.status,
            operationName,
            errors: payload.errors,
          }
        );
      }
    }

    return payload?.data || {};
  }

  #createMorphoProtocol(account, runtimeConfig, request) {
    return new MorphoProtocolEvm(account, this.#buildMorphoProtocolOptions(runtimeConfig, request));
  }

  #buildMorphoProtocolOptions(runtimeConfig, request) {
    const options = {
      chainId: runtimeConfig.chainId,
      supportSignature: false,
    };
    if (request.target.vaultAddress) {
      options.earnVaultAddress = request.target.vaultAddress;
    } else if (request.target.vaultPreset) {
      options.presets = {
        ...(options.presets || {}),
        earn: request.target.vaultPreset,
      };
    }
    if (request.target.marketId) {
      options.borrowMarketId = request.target.marketId;
    } else if (request.target.marketPreset) {
      options.presets = {
        ...(options.presets || {}),
        borrow: request.target.marketPreset,
      };
    }
    return options;
  }

  #getMorphoOperationMethods(request) {
    const table =
      request.target.vaultAddress || request.target.vaultPreset
        ? {
            supply: {
              requirementsMethod: "getSupplyRequirements",
              quoteMethod: "quoteSupply",
              sendMethod: "supply",
            },
            withdraw: {
              requirementsMethod: null,
              quoteMethod: "quoteWithdraw",
              sendMethod: "withdraw",
            },
          }
        : {
            supply_collateral: {
              requirementsMethod: "getSupplyCollateralRequirements",
              quoteMethod: "quoteSupplyCollateral",
              sendMethod: "supplyCollateral",
            },
            borrow: {
              requirementsMethod: "getBorrowRequirements",
              quoteMethod: "quoteBorrow",
              sendMethod: "borrow",
            },
            repay: {
              requirementsMethod: "getRepayRequirements",
              quoteMethod: "quoteRepay",
              sendMethod: "repay",
            },
            withdraw_collateral: {
              requirementsMethod: null,
              quoteMethod: "quoteWithdrawCollateral",
              sendMethod: "withdrawCollateral",
            },
          };
    const methods = table[request.operation];
    if (!methods) {
      throw new Error(`Unsupported Morpho operation '${request.operation}'.`);
    }
    return methods;
  }

  #buildMorphoOperationOptions(request) {
    const options = {
      token: request.token,
    };
    if (request.amount !== undefined && request.amount !== null) {
      options.amount = request.amount;
    }
    if (request.nativeAmount !== undefined && request.nativeAmount !== null) {
      options.nativeAmount = request.nativeAmount;
    }
    return options;
  }

  async #buildMorphoOperationPlan({
    account,
    runtimeConfig,
    address,
    request,
    tolerateOperationFeeFailure = false,
  }) {
    const protocol = this.#createMorphoProtocol(account, runtimeConfig, request);
    try {
      const methods = this.#getMorphoOperationMethods(request);
      const operationOptions = this.#buildMorphoOperationOptions(request);
      const requirements = await this.#buildMorphoRequirementPlan({
        account,
        runtimeConfig,
        protocol,
        request,
        methods,
        operationOptions,
      });
      const operationFeeQuote = await this.#quoteMorphoProtocolOperation({
        protocol,
        methods,
        operationOptions,
        tolerateFailure: tolerateOperationFeeFailure,
      });
      const tokenMetadata = await this.#getBestEffortTokenMetadata(runtimeConfig, request.token);
      const target =
        request.target.vaultAddress || request.target.vaultPreset
          ? {
              type: "vault",
              vaultAddress: protocol.getVaultAddress().toLowerCase(),
              vaultPreset: request.target.vaultPreset || null,
            }
          : {
              type: "market",
              marketId: protocol.getBorrowMarketId(),
              marketPreset: request.target.marketPreset || null,
            };
      const quoteFingerprint = sha256Hex(
        JSON.stringify({
          chainId: runtimeConfig.chainId,
          network: runtimeConfig.network,
          from: address.toLowerCase(),
          protocol: "morpho",
          target,
          operation: request.operation,
          token: request.token.toLowerCase(),
          amount:
            typeof request.amount === "bigint"
              ? request.amount.toString()
              : request.amount === "max"
                ? "max"
                : null,
          nativeAmount: request.nativeAmount ? request.nativeAmount.toString() : null,
        })
      );
      return {
        quoteFingerprint,
        target,
        amount: request.amount ?? null,
        nativeAmount: request.nativeAmount ?? null,
        tokenMetadata,
        operationFee: operationFeeQuote.fee,
        operationFeeError: operationFeeQuote.error,
        totalEstimatedFee:
          operationFeeQuote.fee !== null ? operationFeeQuote.fee + requirements.estimatedFee : null,
        requirements,
      };
    } finally {
      await maybeDispose(protocol);
    }
  }

  async #buildMorphoRequirementPlan({
    account,
    runtimeConfig,
    protocol,
    request,
    methods,
    operationOptions,
  }) {
    if (!methods.requirementsMethod) {
      return {
        required: false,
        estimatedFee: 0n,
        approvalRequired: false,
        authorizationRequired: false,
        steps: [],
        transactions: [],
        approvalContexts: [],
        authorizationContexts: [],
      };
    }
    const requirements = await protocol[methods.requirementsMethod](operationOptions);
    const steps = [];
    const transactions = [];
    const approvalContexts = [];
    const authorizationContexts = [];
    let estimatedFee = 0n;
    for (const requirement of Array.isArray(requirements) ? requirements : []) {
      if (isRequirementApproval(requirement)) {
        const spender = normalizeAddress(
          String(requirement.action?.args?.spender || ""),
          "morphoRequirement.spender"
        ).toLowerCase();
        const amount = BigInt(requirement.action?.args?.amount || 0);
        const quote = await account.quoteSendTransaction({
          to: requirement.to,
          value: requirement.value ?? 0n,
          data: requirement.data,
        });
        const fee = BigInt(quote?.fee || 0);
        this.#assertMaxFee(runtimeConfig, fee, `morpho approval`);
        estimatedFee += fee;
        steps.push({
          type: "approval",
          spender,
          amount: amount.toString(),
          estimatedFeeWei: fee.toString(),
          to: requirement.to.toLowerCase(),
          value: BigInt(requirement.value ?? 0).toString(),
          dataHash: sha256Hex(requirement.data),
        });
        transactions.push(requirement);
        if (!approvalContexts.some((entry) => entry.spender === spender)) {
          const originalAllowance = await account.getAllowance(request.token, spender);
          approvalContexts.push({
            tokenAddress: request.token,
            spender,
            originalAllowance,
          });
        }
        continue;
      }
      if (isRequirementAuthorization(requirement)) {
        const authorized = normalizeAddress(
          String(requirement.action?.args?.authorized || ""),
          "morphoRequirement.authorized"
        ).toLowerCase();
        const quote = await account.quoteSendTransaction({
          to: requirement.to,
          value: requirement.value ?? 0n,
          data: requirement.data,
        });
        const fee = BigInt(quote?.fee || 0);
        this.#assertMaxFee(runtimeConfig, fee, `morpho authorization`);
        estimatedFee += fee;
        steps.push({
          type: "authorization",
          authorized,
          isAuthorized: Boolean(requirement.action?.args?.isAuthorized),
          estimatedFeeWei: fee.toString(),
          to: requirement.to.toLowerCase(),
          value: BigInt(requirement.value ?? 0).toString(),
          dataHash: sha256Hex(requirement.data),
        });
        transactions.push(requirement);
        if (
          !authorizationContexts.some(
            (entry) =>
              entry.contractAddress === requirement.to.toLowerCase() &&
              entry.authorized === authorized
          )
        ) {
          authorizationContexts.push({
            contractAddress: requirement.to.toLowerCase(),
            authorized,
          });
        }
        continue;
      }
      throw createTaggedError(
        "Morpho returned a signature requirement, but this runtime only supports transaction-based requirements.",
        "morpho_requirements_unresolved",
        {
          requirementType: requirement?.action?.type || null,
        }
      );
    }
    return {
      required: steps.length > 0,
      estimatedFee,
      approvalRequired: steps.some((step) => step.type === "approval"),
      authorizationRequired: steps.some((step) => step.type === "authorization"),
      steps,
      transactions,
      approvalContexts,
      authorizationContexts,
    };
  }

  async #quoteMorphoProtocolOperation({
    protocol,
    methods,
    operationOptions,
    tolerateFailure,
  }) {
    try {
      const quote = await protocol[methods.quoteMethod](operationOptions);
      return {
        fee: BigInt(quote?.fee || 0),
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

  #formatMorphoOperationResponse({ runtimeConfig, accountIndex, address, request, plan }) {
    const amountFormatted =
      typeof plan.amount === "bigint" &&
      plan.tokenMetadata &&
      Number.isInteger(plan.tokenMetadata.decimals)
        ? formatUnits(plan.amount, plan.tokenMetadata.decimals)
        : null;
    const nativeAmountFormatted =
      typeof plan.nativeAmount === "bigint" ? formatUnits(plan.nativeAmount, 18) : null;
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      accountIndex,
      address,
      protocol: "morpho",
      executionSupported: true,
      surface: plan.target.type,
      operation: request.operation,
      target: plan.target,
      operationRequest: {
        token: request.token,
        amount:
          typeof plan.amount === "bigint"
            ? plan.amount.toString()
            : plan.amount === "max"
              ? "max"
              : null,
        nativeAmount: typeof plan.nativeAmount === "bigint" ? plan.nativeAmount.toString() : null,
      },
      tokenMetadata: plan.tokenMetadata,
      amountFormatted,
      nativeAmountFormatted,
      quoteFingerprint: plan.quoteFingerprint,
      estimatedFeeWei: plan.totalEstimatedFee !== null ? plan.totalEstimatedFee.toString() : null,
      estimatedOperationFeeWei: plan.operationFee !== null ? plan.operationFee.toString() : null,
      estimatedRequirementsFeeWei: plan.requirements.estimatedFee.toString(),
      feeEstimateAvailable: plan.operationFee !== null,
      feeEstimateError: plan.operationFeeError,
      requirements: {
        required: plan.requirements.required,
        requirementCount: plan.requirements.steps.length,
        approvalRequired: plan.requirements.approvalRequired,
        authorizationRequired: plan.requirements.authorizationRequired,
        sequence: plan.requirements.steps,
      },
      source: "wdk-protocol-lending-morpho-evm",
    };
  }

  #assertExpectedMorphoFingerprint(expectedQuoteFingerprint, actualQuoteFingerprint) {
    if (!expectedQuoteFingerprint) {
      return;
    }
    if (expectedQuoteFingerprint !== actualQuoteFingerprint) {
      throw createTaggedError(
        "Morpho quote changed since preview. Generate a new preview and approval before execute.",
        "morpho_quote_changed",
        {
          expectedQuoteFingerprint,
          actualQuoteFingerprint,
        }
      );
    }
  }

  async #executeMorphoRequirementsIfNeeded({ account, runtimeConfig, plan }) {
    if (!plan.requirements.required) {
      return {
        performed: false,
        totalFee: 0n,
        transactions: [],
        approvalContexts: plan.requirements.approvalContexts,
        authorizationContexts: plan.requirements.authorizationContexts,
      };
    }
    let totalFee = 0n;
    const transactions = [];
    for (let index = 0; index < plan.requirements.transactions.length; index += 1) {
      const requirementTx = plan.requirements.transactions[index];
      const step = plan.requirements.steps[index];
      const result = await account.sendTransaction({
        to: requirementTx.to,
        value: requirementTx.value ?? 0n,
        data: requirementTx.data,
      });
      const fee = BigInt(result?.fee || 0);
      totalFee += fee;
      transactions.push({
        ...step,
        hash: result.hash,
        fee: fee.toString(),
      });
      await this.#waitForTransactionReceipt(runtimeConfig, result.hash);
    }
    return {
      performed: true,
      totalFee,
      transactions,
      approvalContexts: plan.requirements.approvalContexts,
      authorizationContexts: plan.requirements.authorizationContexts,
    };
  }

  async #restoreMorphoRequirementsAfterFailedOperation({
    account,
    runtimeConfig,
    requirementExecution,
  }) {
    if (!requirementExecution?.performed) {
      return {
        attempted: false,
        restored: false,
      };
    }
    const cleanup = {
      attempted: true,
      restored: false,
      approvals: [],
      authorizations: [],
      error: null,
    };
    try {
      for (const context of requirementExecution.approvalContexts || []) {
        const restorePlan = await this.#buildAllowanceRestorePlan({
          account,
          runtimeConfig,
          tokenAddress: context.tokenAddress,
          spender: context.spender,
          targetAllowance: context.originalAllowance,
        });
        const entry = {
          tokenAddress: context.tokenAddress,
          spender: context.spender,
          originalAllowance: BigInt(context.originalAllowance || 0).toString(),
          restoreSteps: restorePlan.steps.map((step) => ({ ...step })),
          restoreHashes: [],
        };
        for (const step of restorePlan.steps) {
          const result = await account.approve({
            token: context.tokenAddress,
            spender: context.spender,
            amount: step.amount,
          });
          entry.restoreHashes.push({
            type: step.type,
            hash: result.hash,
            fee: BigInt(result.fee || 0).toString(),
          });
          await this.#waitForTransactionReceipt(runtimeConfig, result.hash);
        }
        const finalAllowance = await account.getAllowance(context.tokenAddress, context.spender);
        entry.finalAllowance = finalAllowance.toString();
        entry.restored = finalAllowance === BigInt(context.originalAllowance || 0);
        cleanup.approvals.push(entry);
        if (!entry.restored) {
          throw new Error("Morpho approval allowance restore did not reach the original allowance.");
        }
      }

      for (const context of requirementExecution.authorizationContexts || []) {
        const result = await account.sendTransaction({
          to: context.contractAddress,
          value: 0n,
          data: MORPHO_AUTHORIZATION_INTERFACE.encodeFunctionData("setAuthorization", [
            context.authorized,
            false,
          ]),
        });
        cleanup.authorizations.push({
          contractAddress: context.contractAddress,
          authorized: context.authorized,
          hash: result.hash,
          fee: BigInt(result.fee || 0).toString(),
        });
        await this.#waitForTransactionReceipt(runtimeConfig, result.hash);
      }

      cleanup.restored = true;
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

  #throwMorphoFailureWithCleanup(error, cleanup) {
    if (cleanup?.attempted && cleanup.restored !== true) {
      throw createTaggedError(
        "Morpho operation failed after prerequisite transactions and automatic cleanup did not complete.",
        "morpho_cleanup_failed",
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
      runtimeConfig.transferMaxFeeWei !== undefined &&
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

  async #uniswapTradingApiRequest(pathname, body) {
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
      "x-universal-router-version": this.config.uniswapRouterVersion,
    };
    if (this.config.uniswapViaGateway) {
      // The provider gateway holds the Uniswap key and injects x-api-key upstream;
      // we authenticate to it with the shared gateway bearer (same token used for
      // EVM RPC routing), so no Uniswap key needs to live on this machine.
      const token = String(this.config.providerGatewayToken || "").trim();
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
    } else {
      if (!this.config.uniswapApiKey) {
        throw createTaggedError(
          "UNISWAP_API_KEY is not configured. Set it, or route Uniswap through the provider gateway, to use Uniswap Trading API swaps.",
          "uniswap_api_key_missing",
          { provider: "uniswap" }
        );
      }
      headers["x-api-key"] = this.config.uniswapApiKey;
    }
    const base = String(this.config.uniswapTradingApiBaseUrl).replace(/\/+$/, "");
    let response;
    try {
      response = await fetch(`${base}${pathname}`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw createTaggedError(`Uniswap Trading API unavailable: ${message}`, "network_unavailable", {
        provider: "uniswap",
        pathname,
      });
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const message =
        payload?.detail ||
        payload?.message ||
        payload?.error ||
        `Uniswap Trading API ${pathname} failed with HTTP ${response.status}.`;
      throw createTaggedError(String(message), "network_unavailable", {
        provider: "uniswap",
        pathname,
        httpStatus: response.status,
      });
    }
    if (!payload || typeof payload !== "object") {
      throw createTaggedError(
        `Uniswap Trading API ${pathname} returned an empty response.`,
        "network_unavailable",
        { provider: "uniswap", pathname }
      );
    }
    return payload;
  }

  async #fetchUniswapQuote({ runtimeConfig, address, swapRequest }) {
    const chainId = UNISWAP_SUPPORTED_CHAIN_IDS[runtimeConfig.network];
    const payload = await this.#uniswapTradingApiRequest("/quote", {
      swapper: address,
      tokenIn: swapRequest.tokenIn,
      tokenOut: swapRequest.tokenOut,
      tokenInChainId: chainId,
      tokenOutChainId: chainId,
      amount: swapRequest.tokenInAmount.toString(),
      type: "EXACT_INPUT",
      slippageTolerance: swapRequest.slippagePercent,
      // The live Trading API rejects routingPreference:"CLASSIC"; restricting
      // protocols to V2/V3/V4 is what excludes UniswapX and yields routing=CLASSIC.
      protocols: ["V2", "V3", "V4"],
    });
    const routing = String(payload.routing || "").toUpperCase();
    if (routing !== "CLASSIC") {
      throw createTaggedError(
        `Uniswap returned unsupported routing '${routing}'. Only CLASSIC is enabled in this runtime.`,
        "uniswap_unsupported_route",
        { provider: "uniswap", routing }
      );
    }
    if (!payload.quote || typeof payload.quote !== "object" || !payload.quote.output) {
      throw createTaggedError(
        "Uniswap quote response is missing CLASSIC quote/output fields.",
        "network_unavailable",
        { provider: "uniswap" }
      );
    }
    return payload;
  }

  async #buildUniswapSwapPlan({ account, runtimeConfig, address, swapRequest }) {
    const quoteResponse = await this.#fetchUniswapQuote({ runtimeConfig, address, swapRequest });
    const permitData = quoteResponse.permitData ?? null;
    const isNativeTokenIn = isZeroAddress(swapRequest.tokenIn);
    const spender = isNativeTokenIn ? null : PERMIT2_ADDRESS;
    const allowanceState = isNativeTokenIn
      ? { currentAllowance: swapRequest.tokenInAmount, error: null }
      : await this.#getSwapAllowanceState({
          account,
          tokenAddress: swapRequest.tokenIn,
          spender,
        });
    const currentAllowance = allowanceState.currentAllowance;
    const approval = isNativeTokenIn
      ? { required: false, estimatedFee: 0n, steps: [] }
      : await this.#buildSwapApprovalPlan({
          account,
          runtimeConfig,
          tokenAddress: swapRequest.tokenIn,
          spender,
          requiredAmount: swapRequest.tokenInAmount,
          currentAllowance,
        });
    const tokenOutAmount = BigInt(String(quoteResponse.quote.output.amount || "0"));
    const slippageBps = Math.round(swapRequest.slippagePercent * 100);
    // The Trading API returns the post-slippage floor directly; fall back to a
    // local computation only if the field is absent.
    const minimumTokenOutAmount =
      quoteResponse.quote.output.minimumAmount !== undefined &&
      quoteResponse.quote.output.minimumAmount !== null
        ? BigInt(String(quoteResponse.quote.output.minimumAmount))
        : tokenOutAmount - (tokenOutAmount * BigInt(slippageBps)) / 10000n;
    const router = UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK[runtimeConfig.network];
    // Bind only the stable swap *intent* (who/what/how-much/slippage/route), never
    // the live quoted output: the Trading API re-prices every block, so including
    // tokenOutAmount here made execute's re-quote fingerprint differ from preview's
    // and spuriously fail with "swap_quote_changed". Adverse price movement is
    // caught separately and tolerantly by the minimumTokenOutAmount check, matching
    // the velora swap contract (#buildVeloraSwapPlan).
    const quoteFingerprint = sha256Hex(
      JSON.stringify({
        chainId: runtimeConfig.chainId,
        network: runtimeConfig.network,
        from: address.toLowerCase(),
        router: router.toLowerCase(),
        spender: spender ? spender.toLowerCase() : null,
        tokenIn: swapRequest.tokenIn.toLowerCase(),
        tokenOut: swapRequest.tokenOut.toLowerCase(),
        tokenInAmount: swapRequest.tokenInAmount.toString(),
        slippageBps,
        routing: "CLASSIC",
      })
    );
    return {
      quoteResponse,
      permitData,
      isNativeTokenIn,
      spender,
      currentAllowance,
      allowanceReadError: allowanceState.error,
      approval,
      tokenInAmount: swapRequest.tokenInAmount,
      tokenOutAmount,
      minimumTokenOutAmount,
      slippageBps,
      quoteFingerprint,
      gasFee: quoteResponse.quote.gasFee ?? null,
      gasFeeUSD: quoteResponse.quote.gasFeeUSD ?? null,
      router,
    };
  }

  async #signUniswapPermit(account, permitData, runtimeConfig) {
    const typed = normalizeUniswapPermitData(permitData, runtimeConfig);
    return account.signTypedData({
      domain: typed.domain,
      types: typed.types,
      message: typed.message,
    });
  }

  async #fetchUniswapSwapCalldata({ runtimeConfig, quoteResponse, permitData, signature }) {
    const { permitData: _permitData, permitTransaction: _permitTransaction, ...cleanQuote } =
      quoteResponse;
    const body = { ...cleanQuote };
    // CLASSIC routing: the Universal Router needs permitData on-chain to verify the
    // Permit2 authorization, so signature and permitData are submitted together.
    if (signature && permitData) {
      body.signature = signature;
      body.permitData = permitData;
    }
    const payload = await this.#uniswapTradingApiRequest("/swap", body);
    const swap = payload.swap || {};
    const to = normalizeAddress(String(swap.to || ""), "swap.to");
    const expectedRouter = UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK[runtimeConfig.network];
    if (to.toLowerCase() !== expectedRouter) {
      throw createTaggedError(
        "Uniswap /swap returned an unexpected target contract.",
        "uniswap_unexpected_router",
        { provider: "uniswap", to: to.toLowerCase(), expected: expectedRouter }
      );
    }
    const data = assertNonEmptyString(String(swap.data || ""), "swap.data");
    if (data === "0x") {
      throw createTaggedError(
        "Uniswap /swap returned empty calldata. The quote likely expired; generate a new preview.",
        "swap_quote_changed",
        { provider: "uniswap" }
      );
    }
    return {
      to,
      data,
      value: parseHexOrDecimalBigInt(swap.value || "0", "swap.value"),
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

  #getLidoContracts(network) {
    const contracts = LIDO_CONTRACTS_BY_NETWORK[network];
    if (!contracts) {
      throw new Error(`Lido contracts are not configured for network '${network}'.`);
    }
    return contracts;
  }

  #getLidoReferralAddress() {
    const configured = String(this.config.lidoReferralAddress || "").trim();
    if (!configured) {
      return ZERO_ADDRESS;
    }
    return normalizeAddress(configured, "lidoReferralAddress").toLowerCase();
  }

  async #getLidoTokenMetadata(runtimeConfig, tokenDefinition) {
    const metadata = await this.#getBestEffortTokenMetadata(runtimeConfig, tokenDefinition.address);
    return withLidoMetadataDefaults(metadata, tokenDefinition);
  }

  async #readLidoSampleRates(runtimeConfig) {
    const sampleAmount = 10n ** 18n;
    const [wstEthPerStEthRaw, stEthPerWstEthRaw] = await Promise.all([
      this.#quoteLidoOutputRaw({
        runtimeConfig,
        operation: "wrap_steth",
        amount: sampleAmount,
      }),
      this.#quoteLidoOutputRaw({
        runtimeConfig,
        operation: "unwrap_wsteth",
        amount: sampleAmount,
      }),
    ]);
    return {
      sampleBaseUnits: sampleAmount.toString(),
      wstEthPerStEthRaw: wstEthPerStEthRaw.toString(),
      wstEthPerStEthFormatted: formatUnits(wstEthPerStEthRaw, 18),
      stEthPerWstEthRaw: stEthPerWstEthRaw.toString(),
      stEthPerWstEthFormatted: formatUnits(stEthPerWstEthRaw, 18),
    };
  }

  async #readLidoStakingApr(runtimeConfig) {
    if (runtimeConfig.network !== "ethereum") {
      return {
        data: null,
        error: null,
      };
    }
    const baseUrl = String(this.config.lidoApiBaseUrl || "https://eth-api.lido.fi/v1").replace(
      /\/+$/,
      ""
    );
    if (!baseUrl) {
      return {
        data: null,
        error: {
          code: "lido_apr_unavailable",
          message: "Lido APR API base URL is not configured.",
        },
      };
    }
    try {
      const [lastPayload, smaPayload] = await Promise.all([
        fetchJson(`${baseUrl}/protocol/steth/apr/last`),
        fetchJson(`${baseUrl}/protocol/steth/apr/sma`),
      ]);
      return {
        data: this.#normalizeLidoStakingApr({
          lastPayload,
          smaPayload,
        }),
        error: null,
      };
    } catch (error) {
      return {
        data: null,
        error: {
          code:
            error && typeof error === "object"
              ? String(error.errorCode || error.code || "").trim() || "lido_apr_unavailable"
              : "lido_apr_unavailable",
          message: error instanceof Error ? error.message : String(error),
        },
      };
    }
  }

  #normalizeLidoStakingApr({ lastPayload, smaPayload }) {
    const lastData =
      lastPayload && typeof lastPayload === "object" && lastPayload.data && typeof lastPayload.data === "object"
        ? lastPayload.data
        : {};
    const smaData =
      smaPayload && typeof smaPayload === "object" && smaPayload.data && typeof smaPayload.data === "object"
        ? smaPayload.data
        : {};
    const meta =
      lastPayload && typeof lastPayload === "object" && lastPayload.meta && typeof lastPayload.meta === "object"
        ? lastPayload.meta
        : smaPayload && typeof smaPayload === "object" && smaPayload.meta && typeof smaPayload.meta === "object"
          ? smaPayload.meta
          : {};
    const aprSeries = Array.isArray(smaData.aprs)
      ? smaData.aprs
          .map((entry) => ({
            timeUnix: Number(entry?.timeUnix),
            apr: Number(entry?.apr),
          }))
          .filter((entry) => Number.isFinite(entry.timeUnix) && Number.isFinite(entry.apr))
      : [];
    const lastApr = Number(lastData.apr);
    const lastTimeUnix = Number(lastData.timeUnix);
    const smaApr = Number(smaData.smaApr);
    const chainId = Number(meta.chainId);
    return {
      source: "lido-public-api",
      symbol: typeof meta.symbol === "string" && meta.symbol.trim() ? meta.symbol.trim() : "stETH",
      address:
        typeof meta.address === "string" && meta.address.trim() ? meta.address.trim().toLowerCase() : null,
      chainId: Number.isFinite(chainId) ? chainId : 1,
      lastApr: Number.isFinite(lastApr) ? lastApr : null,
      lastAprTimeUnix: Number.isFinite(lastTimeUnix) ? lastTimeUnix : null,
      smaApr: Number.isFinite(smaApr) ? smaApr : null,
      smaWindowDays: 7,
      aprSeries,
    };
  }

  async #getLidoWithdrawalRequestIds(runtimeConfig, ownerAddress) {
    const contracts = this.#getLidoContracts(runtimeConfig.network);
    const [requestIdsRaw] = await callContract(
      runtimeConfig.providerUrl,
      contracts.withdrawalQueue,
      LIDO_WITHDRAWAL_QUEUE_INTERFACE,
      "getWithdrawalRequests",
      [normalizeAddress(ownerAddress, "ownerAddress")]
    );
    return Array.isArray(requestIdsRaw) ? requestIdsRaw.map((value) => BigInt(value)) : [];
  }

  async #getLidoWithdrawalStatuses(runtimeConfig, requestIds) {
    if (!Array.isArray(requestIds) || requestIds.length === 0) {
      return [];
    }
    const contracts = this.#getLidoContracts(runtimeConfig.network);
    const normalizedIds = requestIds.map((value) => BigInt(value));
    const [statusesRaw] = await callContract(
      runtimeConfig.providerUrl,
      contracts.withdrawalQueue,
      LIDO_WITHDRAWAL_QUEUE_INTERFACE,
      "getWithdrawalStatus",
      [normalizedIds]
    );
    const entries = Array.isArray(statusesRaw) ? statusesRaw : [];
    return entries.map((entry, index) => ({
      owner:
        /^0x[a-fA-F0-9]{40}$/.test(String(entry.owner ?? entry[2] ?? ZERO_ADDRESS).trim())
          ? String(entry.owner ?? entry[2] ?? ZERO_ADDRESS).trim().toLowerCase()
          : ZERO_ADDRESS,
      requestId: normalizedIds[index],
      amountOfStETH: BigInt(entry.amountOfStETH ?? entry[0] ?? 0),
      amountOfShares: BigInt(entry.amountOfShares ?? entry[1] ?? 0),
      timestamp: BigInt(entry.timestamp ?? entry[3] ?? 0),
      isFinalized: Boolean(entry.isFinalized ?? entry[4]),
      isClaimed: Boolean(entry.isClaimed ?? entry[5]),
    }));
  }

  #formatLidoWithdrawalStatus(status, stEthMetadata, wstEthMetadata) {
    const claimable = Boolean(status.isFinalized) && !Boolean(status.isClaimed);
    const amountOfWstEthRaw =
      status.amountOfShares > 0n && status.amountOfStETH > 0n
        ? status.amountOfShares
        : null;
    return {
      requestId: status.requestId.toString(),
      owner: status.owner,
      timestamp: status.timestamp.toString(),
      amountOfStETHRaw: status.amountOfStETH.toString(),
      amountOfStETHFormatted: formatUnits(status.amountOfStETH, stEthMetadata.decimals),
      amountOfSharesRaw: status.amountOfShares.toString(),
      amountOfSharesFormatted: formatUnits(status.amountOfShares, LIDO_STETH_DECIMALS),
      amountOfWstETHRaw: amountOfWstEthRaw !== null ? amountOfWstEthRaw.toString() : null,
      amountOfWstETHFormatted:
        amountOfWstEthRaw !== null ? formatUnits(amountOfWstEthRaw, wstEthMetadata.decimals) : null,
      isFinalized: Boolean(status.isFinalized),
      isClaimed: Boolean(status.isClaimed),
      claimable,
    };
  }

  async #quoteLidoOutputRaw({ runtimeConfig, operation, amount, fromAddress = ZERO_ADDRESS }) {
    const contracts = this.#getLidoContracts(runtimeConfig.network);
    const normalizedOperation = normalizeLidoOperation(operation);
    if (normalizedOperation === "stake_eth_for_wsteth") {
      const data = LIDO_REFERRAL_STAKER_INTERFACE.encodeFunctionData("stakeETH", [
        this.#getLidoReferralAddress(),
      ]);
      const raw = await ethCallTransaction(runtimeConfig.providerUrl, {
        from: normalizeAddress(fromAddress, "fromAddress"),
        to: contracts.referralStaker,
        data,
        value: toRpcHex(amount),
      });
      return decodeUint256Result(raw, "stakeETH");
    }
    const callData =
      normalizedOperation === "wrap_steth"
        ? LIDO_WSTETH_INTERFACE.encodeFunctionData("getWstETHByStETH", [amount])
        : LIDO_WSTETH_INTERFACE.encodeFunctionData("getStETHByWstETH", [amount]);
    const raw = await ethCall(runtimeConfig.providerUrl, contracts.wsteth.address, callData);
    return decodeUint256Result(
      raw,
      normalizedOperation === "wrap_steth" ? "getWstETHByStETH" : "getStETHByWstETH"
    );
  }

  async #buildLidoOperationPlan({
    account,
    runtimeConfig,
    address,
    request,
    tolerateOperationFeeFailure = false,
  }) {
    const contracts = this.#getLidoContracts(runtimeConfig.network);
    const nativeMetadata = {
      address: ZERO_ADDRESS,
      name: runtimeConfig.nativeSymbol === "ETH" ? "Ether" : runtimeConfig.nativeSymbol,
      symbol: runtimeConfig.nativeSymbol,
      decimals: 18,
      verified: true,
      source: "native-asset",
    };
    const [stEthMetadata, wstEthMetadata] = await Promise.all([
      this.#getLidoTokenMetadata(runtimeConfig, contracts.steth),
      this.#getLidoTokenMetadata(runtimeConfig, contracts.wsteth),
    ]);
    const inputTokenAddress =
      request.operation === "wrap_steth"
        ? contracts.steth.address
        : request.operation === "unwrap_wsteth"
          ? contracts.wsteth.address
          : ZERO_ADDRESS;
    const inputMetadata =
      request.operation === "wrap_steth"
        ? stEthMetadata
        : request.operation === "unwrap_wsteth"
          ? wstEthMetadata
          : nativeMetadata;
    const outputMetadata = request.operation === "unwrap_wsteth" ? stEthMetadata : wstEthMetadata;
    const spender = request.operation === "wrap_steth" ? contracts.wsteth.address : null;
    const currentAllowanceState =
      request.operation === "wrap_steth"
        ? await this.#getSwapAllowanceState({
            account,
            tokenAddress: contracts.steth.address,
            spender: contracts.wsteth.address,
          })
        : {
            currentAllowance: request.amount,
            error: null,
          };
    const approval =
      request.operation === "wrap_steth"
        ? await this.#buildLidoApprovalPlan({
            account,
            runtimeConfig,
            tokenAddress: contracts.steth.address,
            spender: contracts.wsteth.address,
            requiredAmount: request.amount,
            currentAllowance: currentAllowanceState.currentAllowance,
          })
        : {
            required: false,
            estimatedFee: 0n,
            steps: [],
          };
    if (request.operation === "wrap_steth" || request.operation === "unwrap_wsteth") {
      const balance = await this.#readTokenBalanceWithFallback({
        account,
        runtimeConfig,
        tokenAddress: inputTokenAddress,
        ownerAddress: address,
      });
      if (balance < request.amount) {
        throw createTaggedError(
          "Insufficient token balance for Lido operation.",
          "insufficient_funds",
          {
            network: runtimeConfig.network,
            tokenAddress: inputTokenAddress,
            ownerAddress: address,
            currentBalance: balance.toString(),
            requiredAmount: request.amount.toString(),
            protocol: "lido",
          }
        );
      }
    }

    const operationTx = this.#buildLidoOperationTransaction(runtimeConfig, request);
    const expectedOutputAmount = await this.#quoteLidoOutputRaw({
      runtimeConfig,
      operation: request.operation,
      amount: request.amount,
      fromAddress: address,
    });
    const operationFeeQuote = await this.#quoteSwapTransaction({
      account,
      runtimeConfig,
      from: address,
      swapTx: operationTx,
      tolerateFailure: tolerateOperationFeeFailure || approval.required,
      operationLabel: `lido ${request.operation}`,
    });
    const simulation = approval.required
      ? {
          ok: null,
          skipped: true,
          reason: "allowance_required",
        }
      : await this.#simulatePreparedTransaction({
          runtimeConfig,
          from: address,
          tx: operationTx,
          operationLabel: "Lido operation",
        });
    const operationTransaction = {
      to: operationTx.to,
      value: operationTx.value.toString(),
      dataHash: sha256Hex(String(operationTx.data || "")),
    };
    const quoteFingerprint = sha256Hex(
      JSON.stringify({
        chainId: runtimeConfig.chainId,
        network: runtimeConfig.network,
        from: address.toLowerCase(),
        protocol: "lido",
        operation: request.operation,
        inputToken: inputTokenAddress.toLowerCase(),
        outputToken: outputMetadata.address.toLowerCase(),
        amount: request.amount.toString(),
        outputAmount: expectedOutputAmount.toString(),
        operationTxTo: operationTransaction.to.toLowerCase(),
        operationTxValue: operationTransaction.value,
      })
    );
    return {
      quoteFingerprint,
      contracts,
      spender,
      inputTokenAddress,
      currentAllowance: currentAllowanceState.currentAllowance,
      allowanceReadError: currentAllowanceState.error,
      amount: request.amount,
      expectedOutputAmount,
      operationTx,
      operationFee: operationFeeQuote.fee,
      operationFeeError: operationFeeQuote.error,
      totalEstimatedFee:
        operationFeeQuote.fee !== null ? operationFeeQuote.fee + approval.estimatedFee : null,
      approval,
      inputMetadata,
      outputMetadata,
      simulation,
      operationTransaction,
    };
  }

  async #buildLidoWithdrawalPlan({
    account,
    runtimeConfig,
    address,
    request,
    tolerateOperationFeeFailure = false,
  }) {
    const contracts = this.#getLidoContracts(runtimeConfig.network);
    const [stEthMetadata, wstEthMetadata] = await Promise.all([
      this.#getLidoTokenMetadata(runtimeConfig, contracts.steth),
      this.#getLidoTokenMetadata(runtimeConfig, contracts.wsteth),
    ]);

    if (request.operation === "claim_withdrawal") {
      const status = await this.#getSingleLidoWithdrawalStatus(runtimeConfig, request.requestId);
      if (status.owner.toLowerCase() !== address.toLowerCase()) {
        throw createTaggedError(
          "Withdrawal request does not belong to the active wallet.",
          "lido_withdrawal_owner_mismatch",
          {
            requestId: request.requestId.toString(),
            owner: status.owner,
            activeAddress: address,
          }
        );
      }
      if (status.isClaimed) {
        throw createTaggedError(
          "Withdrawal request has already been claimed.",
          "lido_withdrawal_already_claimed",
          {
            requestId: request.requestId.toString(),
          }
        );
      }
      if (!status.isFinalized) {
        throw createTaggedError(
          "Withdrawal request is not finalized yet and cannot be claimed.",
          "lido_withdrawal_not_finalized",
          {
            requestId: request.requestId.toString(),
          }
        );
      }
      const operationTx = {
        to: contracts.withdrawalQueue,
        value: 0n,
        data: LIDO_WITHDRAWAL_QUEUE_INTERFACE.encodeFunctionData("claimWithdrawal", [
          request.requestId,
        ]),
      };
      const operationFeeQuote = await this.#quoteSwapTransaction({
        account,
        runtimeConfig,
        from: address,
        swapTx: operationTx,
        tolerateFailure: tolerateOperationFeeFailure,
        operationLabel: "lido claim_withdrawal",
      });
      const simulation = await this.#simulatePreparedTransaction({
        runtimeConfig,
        from: address,
        tx: operationTx,
        operationLabel: "Lido withdrawal claim",
      });
      const operationTransaction = {
        to: operationTx.to,
        value: "0",
        dataHash: sha256Hex(String(operationTx.data || "")),
      };
      const quoteFingerprint = sha256Hex(
        JSON.stringify({
          chainId: runtimeConfig.chainId,
          network: runtimeConfig.network,
          from: address.toLowerCase(),
          protocol: "lido",
          operation: request.operation,
          requestId: request.requestId.toString(),
          withdrawalQueue: contracts.withdrawalQueue.toLowerCase(),
        })
      );
      return {
        quoteFingerprint,
        contracts,
        spender: null,
        inputTokenAddress: ZERO_ADDRESS,
        currentAllowance: 0n,
        requiredAllowance: 0n,
        allowanceReadError: null,
        operationFee: operationFeeQuote.fee,
        operationFeeError: operationFeeQuote.error,
        totalEstimatedFee: operationFeeQuote.fee,
        approval: { required: false, estimatedFee: 0n, steps: [] },
        inputMetadata: null,
        queueAssetMetadata: stEthMetadata,
        withdrawalRequest: this.#formatLidoWithdrawalStatus(status, stEthMetadata, wstEthMetadata),
        simulation,
        operationTx,
        operationTransaction,
      };
    }

    const inputTokenAddress =
      request.operation === "request_withdrawal_steth" ? contracts.steth.address : contracts.wsteth.address;
    const inputMetadata =
      request.operation === "request_withdrawal_steth" ? stEthMetadata : wstEthMetadata;
    const spender = contracts.withdrawalQueue;
    const queuedStEthAmount =
      request.operation === "request_withdrawal_steth"
        ? request.amount
        : await this.#quoteLidoOutputRaw({
            runtimeConfig,
            operation: "unwrap_wsteth",
            amount: request.amount,
            fromAddress: address,
          });
    this.#assertLidoWithdrawalAmountWithinLimits(queuedStEthAmount);
    const balance = await this.#readTokenBalanceWithFallback({
      account,
      runtimeConfig,
      tokenAddress: inputTokenAddress,
      ownerAddress: address,
    });
    if (balance < request.amount) {
      throw createTaggedError(
        "Insufficient token balance for Lido withdrawal request.",
        "insufficient_funds",
        {
          network: runtimeConfig.network,
          tokenAddress: inputTokenAddress,
          ownerAddress: address,
          currentBalance: balance.toString(),
          requiredAmount: request.amount.toString(),
          protocol: "lido",
        }
      );
    }
    const allowanceState = await this.#getSwapAllowanceState({
      account,
      tokenAddress: inputTokenAddress,
      spender,
    });
    const approval = await this.#buildLidoApprovalPlan({
      account,
      runtimeConfig,
      tokenAddress: inputTokenAddress,
      spender,
      requiredAmount: request.amount,
      currentAllowance: allowanceState.currentAllowance,
    });
    const operationTx = {
      to: contracts.withdrawalQueue,
      value: 0n,
      data:
        request.operation === "request_withdrawal_steth"
          ? LIDO_WITHDRAWAL_QUEUE_INTERFACE.encodeFunctionData("requestWithdrawals", [
              [request.amount],
              address,
            ])
          : LIDO_WITHDRAWAL_QUEUE_INTERFACE.encodeFunctionData("requestWithdrawalsWstETH", [
              [request.amount],
              address,
            ]),
    };
    const operationFeeQuote = await this.#quoteSwapTransaction({
      account,
      runtimeConfig,
      from: address,
      swapTx: operationTx,
      tolerateFailure: tolerateOperationFeeFailure || approval.required,
      operationLabel: `lido ${request.operation}`,
    });
    const simulation = approval.required
      ? {
          ok: null,
          skipped: true,
          reason: "allowance_required",
        }
      : await this.#simulatePreparedTransaction({
          runtimeConfig,
          from: address,
          tx: operationTx,
          operationLabel: "Lido withdrawal request",
        });
    const operationTransaction = {
      to: operationTx.to,
      value: "0",
      dataHash: sha256Hex(String(operationTx.data || "")),
    };
    const quoteFingerprint = sha256Hex(
      JSON.stringify({
        chainId: runtimeConfig.chainId,
        network: runtimeConfig.network,
        from: address.toLowerCase(),
        protocol: "lido",
        operation: request.operation,
        inputToken: inputTokenAddress.toLowerCase(),
        inputAmount: request.amount.toString(),
        queuedStEthAmount: queuedStEthAmount.toString(),
        withdrawalQueue: contracts.withdrawalQueue.toLowerCase(),
      })
    );
    return {
      quoteFingerprint,
      contracts,
      spender,
      inputTokenAddress,
      currentAllowance: allowanceState.currentAllowance,
      requiredAllowance: request.amount,
      allowanceReadError: allowanceState.error,
      operationFee: operationFeeQuote.fee,
      operationFeeError: operationFeeQuote.error,
      totalEstimatedFee:
        operationFeeQuote.fee !== null ? operationFeeQuote.fee + approval.estimatedFee : null,
      approval,
      inputMetadata,
      queueAssetMetadata: stEthMetadata,
      queuedStEthAmount,
      simulation,
      operationTx,
      operationTransaction,
    };
  }

  #assertLidoWithdrawalAmountWithinLimits(amountOfStETH) {
    const normalizedAmount = BigInt(amountOfStETH || 0);
    if (normalizedAmount < LIDO_MIN_STETH_WITHDRAWAL_AMOUNT) {
      throw createTaggedError(
        "Lido withdrawal amount is below the minimum queue size.",
        "lido_withdrawal_amount_too_small",
        {
          minStEthAmountRaw: LIDO_MIN_STETH_WITHDRAWAL_AMOUNT.toString(),
          providedStEthAmountRaw: normalizedAmount.toString(),
        }
      );
    }
    if (normalizedAmount > LIDO_MAX_STETH_WITHDRAWAL_AMOUNT) {
      throw createTaggedError(
        "Lido withdrawal amount exceeds the maximum queue size.",
        "lido_withdrawal_amount_too_large",
        {
          maxStEthAmountRaw: LIDO_MAX_STETH_WITHDRAWAL_AMOUNT.toString(),
          providedStEthAmountRaw: normalizedAmount.toString(),
        }
      );
    }
  }

  async #getSingleLidoWithdrawalStatus(runtimeConfig, requestId) {
    const statuses = await this.#getLidoWithdrawalStatuses(runtimeConfig, [requestId]);
    if (!statuses.length || statuses[0].owner === ZERO_ADDRESS) {
      throw createTaggedError(
        "Lido withdrawal request was not found.",
        "lido_withdrawal_not_found",
        {
          requestId: BigInt(requestId).toString(),
        }
      );
    }
    return statuses[0];
  }

  #formatLidoWithdrawalResponse({ runtimeConfig, accountIndex, address, request, plan }) {
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      accountIndex,
      address,
      protocol: "lido",
      operation: request.operation,
      withdrawalQueue: plan.contracts.withdrawalQueue,
      operationRequest:
        request.operation === "claim_withdrawal"
          ? {
              requestId: request.requestId.toString(),
            }
          : {
              amount: request.amount.toString(),
            },
      inputAsset: plan.inputMetadata,
      queueAsset: plan.queueAssetMetadata,
      amountFormatted:
        request.operation !== "claim_withdrawal" &&
        plan.inputMetadata &&
        Number.isInteger(plan.inputMetadata.decimals)
          ? formatUnits(request.amount, plan.inputMetadata.decimals)
          : null,
      queuedStEthAmountRaw:
        plan.queuedStEthAmount !== undefined && plan.queuedStEthAmount !== null
          ? plan.queuedStEthAmount.toString()
          : null,
      queuedStEthAmountFormatted:
        plan.queuedStEthAmount !== undefined && plan.queuedStEthAmount !== null
          ? formatUnits(plan.queuedStEthAmount, LIDO_STETH_DECIMALS)
          : null,
      requestId: request.requestId ? request.requestId.toString() : null,
      withdrawalRequest: plan.withdrawalRequest || null,
      quoteFingerprint: plan.quoteFingerprint,
      estimatedFeeWei: plan.totalEstimatedFee !== null ? plan.totalEstimatedFee.toString() : null,
      estimatedOperationFeeWei: plan.operationFee !== null ? plan.operationFee.toString() : null,
      estimatedApprovalFeeWei: plan.approval.estimatedFee.toString(),
      feeEstimateAvailable: plan.operationFee !== null,
      feeEstimateError: plan.operationFeeError,
      allowance: {
        spender: plan.spender,
        currentAllowance: plan.currentAllowance.toString(),
        requiredAllowance: plan.requiredAllowance.toString(),
        approvalRequired: plan.approval.required,
        approvalSequence: plan.approval.steps,
        readError: plan.allowanceReadError,
      },
      simulation: plan.simulation,
      operationTransaction: plan.operationTransaction,
      source: "lido-contracts",
    };
  }

  #assertExpectedLidoWithdrawalFingerprint(expectedQuoteFingerprint, actualQuoteFingerprint) {
    if (!expectedQuoteFingerprint) {
      return;
    }
    if (expectedQuoteFingerprint !== actualQuoteFingerprint) {
      throw createTaggedError(
        "Lido withdrawal quote changed since preview. Generate a new preview and approval before execute.",
        "lido_withdrawal_quote_changed",
        {
          expectedQuoteFingerprint,
          actualQuoteFingerprint,
        }
      );
    }
  }

  async #executeLidoWithdrawalApprovalsIfNeeded({ account, runtimeConfig, plan }) {
    if (!plan.approval.required || !plan.spender || isZeroAddress(plan.inputTokenAddress)) {
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
        token: plan.inputTokenAddress,
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

  async #restoreAllowanceAfterFailedLidoWithdrawal({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    originalAllowance,
    approvalExecution,
  }) {
    if (!approvalExecution?.performed || !tokenAddress || isZeroAddress(tokenAddress) || !spender) {
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
        operationLabel: "lido withdrawal",
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

  #throwLidoWithdrawalFailureWithCleanup(error, cleanup) {
    if (cleanup?.attempted && cleanup.restored !== true) {
      throw createTaggedError(
        "Lido withdrawal failed after approval and automatic allowance restore did not complete.",
        "lido_withdrawal_cleanup_failed",
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

  #buildLidoOperationTransaction(runtimeConfig, request) {
    const contracts = this.#getLidoContracts(runtimeConfig.network);
    if (request.operation === "stake_eth_for_wsteth") {
      return {
        to: contracts.referralStaker,
        value: request.amount,
        data: LIDO_REFERRAL_STAKER_INTERFACE.encodeFunctionData("stakeETH", [
          this.#getLidoReferralAddress(),
        ]),
      };
    }
    return {
      to: contracts.wsteth.address,
      value: 0n,
      data:
        request.operation === "wrap_steth"
          ? LIDO_WSTETH_INTERFACE.encodeFunctionData("wrap", [request.amount])
          : LIDO_WSTETH_INTERFACE.encodeFunctionData("unwrap", [request.amount]),
    };
  }

  async #buildLidoApprovalPlan({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    requiredAmount,
    currentAllowance,
  }) {
    const steps = [];
    if (currentAllowance < requiredAmount) {
      steps.push({ type: "approve", amount: requiredAmount.toString() });
    }
    let estimatedFee = 0n;
    for (const step of steps) {
      const quote = await account.quoteSendTransaction(
        buildErc20ApproveTransaction(tokenAddress, spender, step.amount)
      );
      const fee = BigInt(quote.fee);
      this.#assertMaxFee(runtimeConfig, fee, `lido ${step.type}`);
      step.estimatedFeeWei = fee.toString();
      estimatedFee += fee;
    }
    return {
      required: steps.length > 0,
      estimatedFee,
      steps,
    };
  }

  #formatLidoOperationResponse({ runtimeConfig, accountIndex, address, request, plan }) {
    return {
      network: runtimeConfig.network,
      chainId: runtimeConfig.chainId,
      accountIndex,
      address,
      protocol: "lido",
      operation: request.operation,
      preferredPositionToken: "wstETH",
      operationRequest: {
        amount: request.amount.toString(),
      },
      inputAsset: plan.inputMetadata,
      outputAsset: plan.outputMetadata,
      amountFormatted:
        plan.inputMetadata && Number.isInteger(plan.inputMetadata.decimals)
          ? formatUnits(request.amount, plan.inputMetadata.decimals)
          : null,
      expectedOutputAmountRaw: plan.expectedOutputAmount.toString(),
      expectedOutputAmountFormatted:
        plan.outputMetadata && Number.isInteger(plan.outputMetadata.decimals)
          ? formatUnits(plan.expectedOutputAmount, plan.outputMetadata.decimals)
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
      contracts: {
        stETH: plan.contracts.steth.address,
        wstETH: plan.contracts.wsteth.address,
        referralStaker: plan.contracts.referralStaker,
        withdrawalQueue: plan.contracts.withdrawalQueue,
      },
      referralAddress: this.#getLidoReferralAddress(),
      simulation: plan.simulation,
      operationTransaction: plan.operationTransaction,
      source: "lido-contracts",
    };
  }

  #assertExpectedLidoFingerprint(expectedQuoteFingerprint, actualQuoteFingerprint) {
    if (!expectedQuoteFingerprint) {
      return;
    }
    if (expectedQuoteFingerprint !== actualQuoteFingerprint) {
      throw createTaggedError(
        "Lido quote changed since preview. Generate a new preview and approval before execute.",
        "lido_quote_changed",
        {
          expectedQuoteFingerprint,
          actualQuoteFingerprint,
        }
      );
    }
  }

  async #executeLidoApprovalsIfNeeded({ account, runtimeConfig, request, plan }) {
    if (!plan.approval.required || !plan.spender || isZeroAddress(plan.inputTokenAddress)) {
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
        token: plan.inputTokenAddress,
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

  async #restoreAllowanceAfterFailedLidoOperation({
    account,
    runtimeConfig,
    tokenAddress,
    spender,
    originalAllowance,
    approvalExecution,
  }) {
    if (!approvalExecution?.performed || !tokenAddress || isZeroAddress(tokenAddress) || !spender) {
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
        operationLabel: "lido",
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

  #throwLidoFailureWithCleanup(error, cleanup) {
    if (cleanup?.attempted && cleanup.restored !== true) {
      throw createTaggedError(
        "Lido operation failed after approval and automatic allowance restore did not complete.",
        "lido_cleanup_failed",
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
    operationLabel = "swap",
  }) {
    try {
      const quote = await account.quoteSendTransaction(swapTx);
      const fee = BigInt(quote.fee);
      this.#assertMaxFee(runtimeConfig, fee, operationLabel);
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
            operationLabel,
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
                operationLabel,
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
            operationLabel,
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

  async #quotePreparedTransactionFromRpc({ runtimeConfig, from, tx, operationLabel = "swap" }) {
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
    this.#assertMaxFee(runtimeConfig, fee, operationLabel);
    return {
      gasLimit,
      effectiveFeePerGas,
      fee,
    };
  }

  async #quotePreparedTransactionFromGasLimit({
    runtimeConfig,
    gasLimit,
    operationLabel = "swap",
  }) {
    const normalizedGasLimit = BigInt(gasLimit);
    const effectiveFeePerGas = await this.#getEffectiveGasPrice(runtimeConfig);
      const fee = normalizedGasLimit * effectiveFeePerGas;
    this.#assertMaxFee(runtimeConfig, fee, operationLabel);
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

  async #simulatePreparedTransaction({ runtimeConfig, from, tx, operationLabel = "Swap" }) {
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
        message: `${operationLabel} simulation failed: ${message}`,
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

export const __testables = {
  PERMIT2_ADDRESS,
  UNISWAP_SUPPORTED_CHAIN_IDS,
  UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK,
  normalizeUniswapTokenAddress,
  assertUniswapSupportedNetwork,
  assertValidNetwork,
  uniswapSlippagePercentFromBps,
  normalizeUniswapPermitData,
};
