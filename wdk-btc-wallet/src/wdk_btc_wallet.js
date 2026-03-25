import WDK from "@tetherto/wdk";
import WalletManagerBtc, {
  ElectrumSsl,
  ElectrumTcp,
  ElectrumTls,
  ElectrumWs,
} from "@tetherto/wdk-wallet-btc";

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
  const normalized = String(network).trim();
  if (!["bitcoin", "testnet", "regtest"].includes(normalized)) {
    throw new Error(`${fieldName} must be one of: bitcoin, testnet, regtest.`);
  }
  return normalized;
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

function assertPositiveInteger(value, fieldName) {
  const parsed = assertNonNegativeInteger(value, fieldName);
  if (parsed <= 0) {
    throw new Error(`${fieldName} must be greater than zero.`);
  }
  return parsed;
}

function buildElectrumClient(config) {
  const clientConfig = {
    host: config.electrumHost,
    port: config.electrumPort,
  };
  if (config.electrumProtocol === "tcp") {
    return new ElectrumTcp(clientConfig);
  }
  if (config.electrumProtocol === "tls") {
    return new ElectrumTls(clientConfig);
  }
  if (config.electrumProtocol === "ssl") {
    return new ElectrumSsl(clientConfig);
  }
  if (config.electrumProtocol === "ws") {
    return new ElectrumWs(clientConfig);
  }
  throw new Error(`Unsupported Electrum protocol: ${config.electrumProtocol}`);
}

async function maybeDispose(value) {
  if (value && typeof value.dispose === "function") {
    await value.dispose();
  }
  if (value && typeof value.close === "function") {
    await value.close();
  }
}

export class WdkBtcWalletService {
  constructor(config) {
    this.config = config;
  }

  generateSeedPhrase(words = 12) {
    const count = assertPositiveInteger(words, "words");
    if (count !== 12) {
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

  async resolveAddress({ seedPhrase, accountIndex = 0, derivationPath = "", network }) {
    return this.#withAccount(
      { seedPhrase, accountIndex, derivationPath, network },
      async (account, runtimeConfig) => ({
      network: runtimeConfig.network,
      bip: runtimeConfig.bip,
      accountIndex: derivationPath ? null : accountIndex,
      derivationPath: derivationPath || null,
      address: await account.getAddress(),
      source: "wdk-wallet-btc",
      })
    );
  }

  async getBalance({ seedPhrase, accountIndex = 0, derivationPath = "", network }) {
    return this.#withAccount({ seedPhrase, accountIndex, derivationPath, network }, async (
      account,
      runtimeConfig
    ) => {
      const address = await account.getAddress();
      const balance = await account.getBalance();
      return {
        network: runtimeConfig.network,
        bip: runtimeConfig.bip,
        accountIndex: derivationPath ? null : accountIndex,
        derivationPath: derivationPath || null,
        address,
        balance,
        source: "wdk-wallet-btc",
      };
    });
  }

  async getTransfers({
    seedPhrase,
    accountIndex = 0,
    derivationPath = "",
    network,
    direction = "all",
    limit = 10,
    skip = 0,
  }) {
    return this.#withAccount(
      { seedPhrase, accountIndex, derivationPath, network },
      async (account, runtimeConfig) => {
      if (!["incoming", "outgoing", "all"].includes(direction)) {
        throw new Error("direction must be one of: incoming, outgoing, all.");
      }
      const options = {
        direction,
        limit: assertNonNegativeInteger(limit, "limit"),
        skip: assertNonNegativeInteger(skip, "skip"),
      };
      const address = await account.getAddress();
      const transfers = await account.getTransfers(options);
      return {
        network: runtimeConfig.network,
        bip: runtimeConfig.bip,
        accountIndex: derivationPath ? null : accountIndex,
        derivationPath: derivationPath || null,
        address,
        options,
        transfers,
        source: "wdk-wallet-btc",
      };
      }
    );
  }

  async getMaxSpendable({
    seedPhrase,
    accountIndex = 0,
    derivationPath = "",
    network,
    feeRate,
  }) {
    return this.#withAccount(
      { seedPhrase, accountIndex, derivationPath, network },
      async (account, runtimeConfig) => {
      const address = await account.getAddress();
      const options = {};
      if (feeRate !== undefined) {
        options.feeRate = assertPositiveInteger(feeRate, "feeRate");
      }
      const maxSpendable = await account.getMaxSpendable(options);
      return {
        network: runtimeConfig.network,
        bip: runtimeConfig.bip,
        accountIndex: derivationPath ? null : accountIndex,
        derivationPath: derivationPath || null,
        address,
        options,
        maxSpendable,
        source: "wdk-wallet-btc",
      };
      }
    );
  }

  async getFeeRates({ seedPhrase = "", network } = {}) {
    return this.#withWallet(
      { seedPhrase: seedPhrase || WDK.getRandomSeedPhrase(), network },
      async (wallet, runtimeConfig) => {
      const feeRates = await wallet.getFeeRates();
      return {
        network: runtimeConfig.network,
        feeRates,
        source: "wdk-wallet-btc",
      };
      }
    );
  }

  async quoteTransfer({
    seedPhrase,
    to,
    value,
    accountIndex = 0,
    derivationPath = "",
    network,
    feeRate,
    confirmationTarget,
  }) {
    return this.#withAccount(
      { seedPhrase, accountIndex, derivationPath, network },
      async (account, runtimeConfig) => {
      const tx = this.#buildTransaction({ to, value, feeRate, confirmationTarget });
      const quote = await account.quoteSendTransaction(tx);
      return {
        network: runtimeConfig.network,
        bip: runtimeConfig.bip,
        accountIndex: derivationPath ? null : accountIndex,
        derivationPath: derivationPath || null,
        transaction: tx,
        quote,
        source: "wdk-wallet-btc",
      };
      }
    );
  }

  async sendTransfer({
    seedPhrase,
    to,
    value,
    accountIndex = 0,
    derivationPath = "",
    network,
    feeRate,
    confirmationTarget,
  }) {
    return this.#withAccount(
      { seedPhrase, accountIndex, derivationPath, network },
      async (account, runtimeConfig) => {
      if (typeof account.sendTransaction !== "function") {
        throw new Error("The current WDK BTC account does not expose sendTransaction.");
      }
      const tx = this.#buildTransaction({ to, value, feeRate, confirmationTarget });
      const result = await account.sendTransaction(tx);
      return {
        network: runtimeConfig.network,
        bip: runtimeConfig.bip,
        accountIndex: derivationPath ? null : accountIndex,
        derivationPath: derivationPath || null,
        transaction: tx,
        result,
        source: "wdk-wallet-btc",
      };
      }
    );
  }

  #buildTransaction({ to, value, feeRate, confirmationTarget }) {
    const tx = {
      to: assertNonEmptyString(to, "to"),
      value: assertPositiveInteger(value, "value"),
    };
    if (feeRate !== undefined) {
      tx.feeRate = assertPositiveInteger(feeRate, "feeRate");
    }
    if (confirmationTarget !== undefined) {
      tx.confirmationTarget = assertPositiveInteger(
        confirmationTarget,
        "confirmationTarget"
      );
    }
    return tx;
  }

  #resolveRuntimeConfig(networkOverride) {
    const network = assertValidNetwork(networkOverride) || this.config.network;
    const profile = this.config.networkProfiles?.[network];
    if (!profile) {
      throw new Error(`Missing Electrum profile for network: ${network}`);
    }
    return {
      ...this.config,
      network,
      electrumProtocol: profile.electrumProtocol,
      electrumHost: profile.electrumHost,
      electrumPort: profile.electrumPort,
    };
  }

  async #withWallet({ seedPhrase, network }, callback) {
    const mnemonic = assertValidSeedPhrase(seedPhrase);
    const runtimeConfig = this.#resolveRuntimeConfig(network);
    const client = buildElectrumClient(runtimeConfig);
    const wallet = new WalletManagerBtc(mnemonic, {
      client,
      network: runtimeConfig.network,
      bip: runtimeConfig.bip,
    });
    try {
      return await callback(wallet, runtimeConfig);
    } finally {
      await maybeDispose(wallet);
      await maybeDispose(client);
    }
  }

  async #withAccount({ seedPhrase, accountIndex, derivationPath, network }, callback) {
    return this.#withWallet({ seedPhrase, network }, async (wallet, runtimeConfig) => {
      const account = derivationPath
        ? await wallet.getAccountByPath(assertNonEmptyString(derivationPath, "derivationPath"))
        : await wallet.getAccount(assertNonNegativeInteger(accountIndex, "accountIndex"));
      return await callback(account, runtimeConfig);
    });
  }
}
