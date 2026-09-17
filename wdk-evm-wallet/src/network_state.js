import fs from "node:fs/promises";
import path from "node:path";

const NETWORK_FILE = "network.json";

function assertValidNetwork(network, fieldName = "network") {
  const normalized = String(network ?? "").trim().toLowerCase();
  const aliases = {
    mainnet: "ethereum",
    eth: "ethereum",
    "eth-mainnet": "ethereum",
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

export class EvmNetworkState {
  constructor(config) {
    this.config = config;
  }

  async getActiveNetwork() {
    const state = await this.#loadState();
    return state.network;
  }

  async getNetworkInfo(networkOverride = undefined) {
    const activeNetwork = networkOverride
      ? assertValidNetwork(networkOverride)
      : await this.getActiveNetwork();
    return {
      activeNetwork,
      profiles: this.config.networkProfiles,
      selectedProfile: this.config.networkProfiles[activeNetwork],
    };
  }

  async setActiveNetwork({ network }) {
    const nextNetwork = assertValidNetwork(network);
    await this.#ensureLayout();
    await fs.writeFile(this.#statePath(), JSON.stringify({ network: nextNetwork }, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });
    return this.getNetworkInfo(nextNetwork);
  }

  async resolveRuntimeConfig(networkOverride = undefined) {
    const activeNetwork = networkOverride
      ? assertValidNetwork(networkOverride, "network")
      : await this.getActiveNetwork();
    const profile = this.config.networkProfiles[activeNetwork];
    return {
      ...this.config,
      network: activeNetwork,
      chainId: profile.chainId,
      providerUrl: profile.providerUrl,
      nativeSymbol: profile.nativeSymbol,
    };
  }

  async #ensureLayout() {
    await fs.mkdir(this.config.dataDir, { recursive: true, mode: 0o700 });
    try {
      await fs.access(this.#statePath());
    } catch {
      await fs.writeFile(
        this.#statePath(),
        JSON.stringify({ network: this.config.network }, null, 2),
        { encoding: "utf8", mode: 0o600 }
      );
    }
  }

  async #loadState() {
    await this.#ensureLayout();
    const raw = await fs.readFile(this.#statePath(), "utf8");
    const parsed = JSON.parse(raw);
    return {
      network: assertValidNetwork(parsed.network),
    };
  }

  #statePath() {
    return path.join(this.config.dataDir, NETWORK_FILE);
  }
}
