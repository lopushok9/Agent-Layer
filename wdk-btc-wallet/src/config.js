import os from "node:os";
import path from "node:path";

const DEFAULTS = {
  host: "127.0.0.1",
  port: 8080,
  network: "bitcoin",
  bip: 84,
  unlockTimeoutSeconds: 0,
};

const DEFAULT_NETWORK_PROFILES = {
  bitcoin: {
    electrumProtocol: "tcp",
    electrumHost: "electrum.blockstream.info",
    electrumPort: 50001,
  },
  testnet: {
    electrumProtocol: "tcp",
    electrumHost: "blockstream.info",
    electrumPort: 143,
  },
  regtest: {
    electrumProtocol: "tcp",
    electrumHost: "127.0.0.1",
    electrumPort: 60401,
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

export function loadConfig(env = process.env) {
  const host = String(env.HOST ?? DEFAULTS.host).trim() || DEFAULTS.host;
  const network = String(env.WDK_BTC_NETWORK ?? DEFAULTS.network).trim() || DEFAULTS.network;
  if (!["bitcoin", "testnet", "regtest"].includes(network)) {
    throw new Error("WDK_BTC_NETWORK must be one of: bitcoin, testnet, regtest.");
  }

  const bip = parseInteger(env.WDK_BTC_BIP, DEFAULTS.bip, "WDK_BTC_BIP");
  if (![44, 84].includes(bip)) {
    throw new Error("WDK_BTC_BIP must be either 44 or 84.");
  }
  const dataDir =
    String(env.WDK_BTC_DATA_DIR ?? "").trim() ||
    path.join(os.homedir(), ".openclaw", "wdk-btc-wallet");

  const networkProfiles = Object.fromEntries(
    Object.entries(DEFAULT_NETWORK_PROFILES).map(([name, defaults]) => {
      const prefix = `WDK_BTC_${name.toUpperCase()}_ELECTRUM_`;
      const electrumProtocol =
        String(env[`${prefix}PROTOCOL`] ?? defaults.electrumProtocol).trim().toLowerCase() ||
        defaults.electrumProtocol;
      if (!["tcp", "tls", "ssl", "ws"].includes(electrumProtocol)) {
        throw new Error(
          `${prefix}PROTOCOL must be one of: tcp, tls, ssl, ws.`
        );
      }
      const electrumHost =
        String(env[`${prefix}HOST`] ?? defaults.electrumHost).trim() || defaults.electrumHost;
      const electrumPort = parseInteger(
        env[`${prefix}PORT`],
        defaults.electrumPort,
        `${prefix}PORT`
      );
      return [
        name,
        {
          electrumProtocol,
          electrumHost,
          electrumPort,
        },
      ];
    })
  );

  return {
    host,
    port: parseInteger(env.PORT, DEFAULTS.port, "PORT"),
    network,
    bip,
    dataDir,
    unlockTimeoutSeconds: parseNonNegativeInteger(
      env.WDK_BTC_UNLOCK_TIMEOUT_SECONDS,
      DEFAULTS.unlockTimeoutSeconds,
      "WDK_BTC_UNLOCK_TIMEOUT_SECONDS"
    ),
    networkProfiles,
  };
}
