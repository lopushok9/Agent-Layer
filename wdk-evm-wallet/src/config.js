import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DEFAULTS = {
  host: "127.0.0.1",
  port: 8081,
  network: "sepolia",
  unlockTimeoutSeconds: 0,
};
const DEFAULT_PROVIDER_GATEWAY_URL = "https://agent-layer-production.up.railway.app";
const ENFORCED_GATEWAY_MAINNETS = new Set(["ethereum", "base"]);

const DEFAULT_NETWORK_PROFILES = {
  ethereum: {
    chainId: 1,
    providerUrl: "https://eth.drpc.org",
    nativeSymbol: "ETH",
  },
  sepolia: {
    chainId: 11155111,
    providerUrl: "https://sepolia.drpc.org",
    nativeSymbol: "ETH",
  },
  base: {
    chainId: 8453,
    providerUrl: "https://mainnet.base.org",
    nativeSymbol: "ETH",
  },
  "base-sepolia": {
    chainId: 84532,
    providerUrl: "https://sepolia.base.org",
    nativeSymbol: "ETH",
  },
};

const SUPPORTED_GATEWAY_PROVIDERS = new Set(["auto", "shared", "alchemy"]);

function parseProviderMode(value, fallback = "public") {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) {
    return fallback;
  }
  if (!["public", "gateway"].includes(normalized)) {
    throw new Error("WDK_EVM_RPC_PROVIDER_MODE must be either 'public' or 'gateway'.");
  }
  return normalized;
}

function parseGatewayProvider(value, fallback = "alchemy") {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) {
    return fallback;
  }
  if (!SUPPORTED_GATEWAY_PROVIDERS.has(normalized)) {
    throw new Error("WDK_EVM_RPC_GATEWAY_PROVIDER must be one of: auto, shared, alchemy.");
  }
  return normalized;
}

function parseInteger(value, fallback, fieldName) {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return fallback;
  }
  const parsed = Number.parseInt(normalized, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${fieldName} must be a positive integer.`);
  }
  return parsed;
}

function parseNonNegativeInteger(value, fallback, fieldName) {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return fallback;
  }
  const parsed = Number.parseInt(normalized, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${fieldName} must be a non-negative integer.`);
  }
  return parsed;
}

function parseOptionalBigInt(value, fieldName) {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return null;
  }
  if (!/^[0-9]+$/.test(normalized)) {
    throw new Error(`${fieldName} must be a base-10 integer string.`);
  }
  return BigInt(normalized);
}

function resolveOpenClawHome(env) {
  const configured = String(env.OPENCLAW_HOME ?? "").trim();
  if (!configured) {
    return path.join(os.homedir(), ".openclaw");
  }
  if (configured === "~") {
    return os.homedir();
  }
  if (configured.startsWith("~/")) {
    return path.join(os.homedir(), configured.slice(2));
  }
  return configured;
}

function ensureLocalAuthToken(tokenPath, configuredToken = "") {
  const direct = String(configuredToken ?? "").trim();
  if (direct) {
    return direct;
  }
  fs.mkdirSync(path.dirname(tokenPath), { recursive: true, mode: 0o700 });
  try {
    const existing = fs.readFileSync(tokenPath, "utf8").trim();
    if (existing) {
      fs.chmodSync(tokenPath, 0o600);
      return existing;
    }
  } catch {
    // Generate a new token below.
  }

  const generated = crypto.randomBytes(32).toString("hex");
  fs.writeFileSync(tokenPath, `${generated}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  fs.chmodSync(tokenPath, 0o600);
  return generated;
}

function normalizeNetworkKey(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  const aliases = {
    mainnet: "ethereum",
    eth: "ethereum",
    "eth-mainnet": "ethereum",
    "base-mainnet": "base",
    base_sepolia: "base-sepolia",
  };
  return aliases[normalized] || normalized;
}

function joinUrl(base, pathname) {
  const normalizedBase = String(base || "").trim();
  if (!normalizedBase) {
    return "";
  }
  const url = new URL(pathname.replace(/^\//, ""), normalizedBase.endsWith("/") ? normalizedBase : `${normalizedBase}/`);
  return url;
}

function buildGatewayEvmRpcUrl(baseUrl, network, provider, token) {
  const url = joinUrl(baseUrl, `/v1/evm/rpc/${network}`);
  if (!url) {
    return "";
  }
  if (provider && provider !== "auto") {
    url.searchParams.set("provider", provider);
  }
  if (String(token || "").trim()) {
    url.searchParams.set("token", String(token).trim());
  }
  return url.toString();
}

export function loadConfig(env = process.env) {
  const host = String(env.HOST ?? DEFAULTS.host).trim() || DEFAULTS.host;
  const network = normalizeNetworkKey(env.WDK_EVM_NETWORK ?? DEFAULTS.network) || DEFAULTS.network;
  if (!Object.hasOwn(DEFAULT_NETWORK_PROFILES, network)) {
    throw new Error(
      "WDK_EVM_NETWORK must be one of: ethereum, sepolia, base, base-sepolia."
    );
  }

  const openClawHome = resolveOpenClawHome(env);
  const dataDir =
    String(env.WDK_EVM_DATA_DIR ?? "").trim() ||
    path.join(openClawHome, "wdk-evm-wallet");
  const authTokenPath =
    String(env.WDK_EVM_LOCAL_TOKEN_PATH ?? "").trim() ||
    path.join(openClawHome, "wdk-evm-wallet", "local-auth-token");
  const providerMode = parseProviderMode(env.WDK_EVM_RPC_PROVIDER_MODE, "gateway");
  const providerGatewayUrl =
    String(env.PROVIDER_GATEWAY_URL ?? "").trim() || DEFAULT_PROVIDER_GATEWAY_URL;
  const providerGatewayToken = String(env.PROVIDER_GATEWAY_BEARER_TOKEN ?? "").trim();
  const gatewayProvider = parseGatewayProvider(env.WDK_EVM_RPC_GATEWAY_PROVIDER, "alchemy");

  function resolveProviderUrl(networkKey, envValue, fallbackUrl) {
    const direct = String(envValue ?? "").trim();
    if (ENFORCED_GATEWAY_MAINNETS.has(networkKey)) {
      const enforcedGatewayUrl = buildGatewayEvmRpcUrl(
        providerGatewayUrl,
        networkKey,
        "alchemy",
        providerGatewayToken
      );
      if (!enforcedGatewayUrl) {
        throw new Error(
          `PROVIDER_GATEWAY_URL is required for ${networkKey} mainnet RPC routing.`
        );
      }
      return enforcedGatewayUrl;
    }
    if (direct) {
      return direct;
    }
    if (
      providerMode === "gateway" &&
      providerGatewayUrl &&
      ["ethereum", "base"].includes(networkKey)
    ) {
      return (
        buildGatewayEvmRpcUrl(providerGatewayUrl, networkKey, gatewayProvider, providerGatewayToken) ||
        fallbackUrl
      );
    }
    return fallbackUrl;
  }

  const networkProfiles = {
    ethereum: {
      ...DEFAULT_NETWORK_PROFILES.ethereum,
      providerUrl: resolveProviderUrl(
        "ethereum",
        env.WDK_EVM_ETHEREUM_RPC_URL,
        DEFAULT_NETWORK_PROFILES.ethereum.providerUrl
      ),
    },
    sepolia: {
      ...DEFAULT_NETWORK_PROFILES.sepolia,
      providerUrl: resolveProviderUrl(
        "sepolia",
        env.WDK_EVM_SEPOLIA_RPC_URL,
        DEFAULT_NETWORK_PROFILES.sepolia.providerUrl
      ),
    },
    base: {
      ...DEFAULT_NETWORK_PROFILES.base,
      providerUrl: resolveProviderUrl(
        "base",
        env.WDK_EVM_BASE_RPC_URL,
        DEFAULT_NETWORK_PROFILES.base.providerUrl
      ),
    },
    "base-sepolia": {
      ...DEFAULT_NETWORK_PROFILES["base-sepolia"],
      providerUrl: resolveProviderUrl(
        "base-sepolia",
        env.WDK_EVM_BASE_SEPOLIA_RPC_URL,
        DEFAULT_NETWORK_PROFILES["base-sepolia"].providerUrl
      ),
    },
  };

  return {
    host,
    port: parseInteger(env.PORT, DEFAULTS.port, "PORT"),
    network,
    openClawHome,
    dataDir,
    authRequired: true,
    authTokenPath,
    authToken: ensureLocalAuthToken(authTokenPath, env.WDK_EVM_LOCAL_TOKEN),
    rpcProviderMode: providerMode,
    rpcGatewayUrl: providerGatewayUrl,
    rpcGatewayProvider: gatewayProvider,
    unlockTimeoutSeconds: parseNonNegativeInteger(
      env.WDK_EVM_UNLOCK_TIMEOUT_SECONDS,
      DEFAULTS.unlockTimeoutSeconds,
      "WDK_EVM_UNLOCK_TIMEOUT_SECONDS"
    ),
    transferMaxFeeWei: parseOptionalBigInt(
      env.WDK_EVM_TRANSFER_MAX_FEE_WEI,
      "WDK_EVM_TRANSFER_MAX_FEE_WEI"
    ),
    lifiApiBaseUrl: String(env.LIFI_API_BASE_URL ?? "").trim() || "https://li.quest/v1",
    lifiApiKey: String(env.LIFI_API_KEY ?? "").trim(),
    lifiIntegrator: String(env.LIFI_INTEGRATOR ?? "").trim() || "openclaw",
    lifiDefaultDenyBridges: String(env.LIFI_DEFAULT_DENY_BRIDGES ?? "").trim() || "mayan",
    lidoApiBaseUrl: String(env.LIDO_API_BASE_URL ?? "").trim() || "https://eth-api.lido.fi/v1",
    lidoReferralAddress: String(env.LIDO_REFERRAL_ADDRESS ?? "").trim(),
    uniswapTradingApiBaseUrl:
      String(env.UNISWAP_TRADING_API_BASE_URL ?? "").trim() ||
      "https://trade-api.gateway.uniswap.org/v1",
    uniswapApiKey: String(env.UNISWAP_API_KEY ?? "").trim(),
    uniswapRouterVersion: String(env.UNISWAP_ROUTER_VERSION ?? "").trim() || "2.0",
    // 300 bps (3%) default mirrors the Solana swap-intent floor. Active markets
    // (Base re-prices every block) drift during the multi-step preview -> approval
    // -> execute window; a 0.5% floor rejected ordinary drift. The quote
    // fingerprint binds only the swap intent, so this floor — not an exact-output
    // pin — is the real slippage guard. Override per-call or via env for tight swaps.
    uniswapDefaultSlippageBps: parseInteger(
      env.UNISWAP_DEFAULT_SLIPPAGE_BPS,
      300,
      "UNISWAP_DEFAULT_SLIPPAGE_BPS"
    ),
    networkProfiles,
  };
}
