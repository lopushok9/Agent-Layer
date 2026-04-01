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

  const networkProfiles = {
    ethereum: {
      ...DEFAULT_NETWORK_PROFILES.ethereum,
      providerUrl:
        String(env.WDK_EVM_ETHEREUM_RPC_URL ?? DEFAULT_NETWORK_PROFILES.ethereum.providerUrl).trim() ||
        DEFAULT_NETWORK_PROFILES.ethereum.providerUrl,
    },
    sepolia: {
      ...DEFAULT_NETWORK_PROFILES.sepolia,
      providerUrl:
        String(env.WDK_EVM_SEPOLIA_RPC_URL ?? DEFAULT_NETWORK_PROFILES.sepolia.providerUrl).trim() ||
        DEFAULT_NETWORK_PROFILES.sepolia.providerUrl,
    },
    base: {
      ...DEFAULT_NETWORK_PROFILES.base,
      providerUrl:
        String(env.WDK_EVM_BASE_RPC_URL ?? DEFAULT_NETWORK_PROFILES.base.providerUrl).trim() ||
        DEFAULT_NETWORK_PROFILES.base.providerUrl,
    },
    "base-sepolia": {
      ...DEFAULT_NETWORK_PROFILES["base-sepolia"],
      providerUrl:
        String(
          env.WDK_EVM_BASE_SEPOLIA_RPC_URL ?? DEFAULT_NETWORK_PROFILES["base-sepolia"].providerUrl
        ).trim() || DEFAULT_NETWORK_PROFILES["base-sepolia"].providerUrl,
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
    unlockTimeoutSeconds: parseNonNegativeInteger(
      env.WDK_EVM_UNLOCK_TIMEOUT_SECONDS,
      DEFAULTS.unlockTimeoutSeconds,
      "WDK_EVM_UNLOCK_TIMEOUT_SECONDS"
    ),
    transferMaxFeeWei: parseOptionalBigInt(
      env.WDK_EVM_TRANSFER_MAX_FEE_WEI,
      "WDK_EVM_TRANSFER_MAX_FEE_WEI"
    ),
    networkProfiles,
  };
}
