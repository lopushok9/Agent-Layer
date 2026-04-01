import WDK from "@tetherto/wdk";
import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

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

function assertValidHash(value, fieldName) {
  const hash = assertNonEmptyString(value, fieldName);
  if (!/^0x[a-fA-F0-9]{64}$/.test(hash)) {
    throw new Error(`${fieldName} must be a valid 32-byte transaction hash.`);
  }
  return hash;
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

async function rpcRequest(providerUrl, method, params = []) {
  const response = await fetch(providerUrl, {
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
  if (!response.ok) {
    throw new Error(`RPC request failed with HTTP ${response.status}.`);
  }
  const payload = await response.json();
  if (payload?.error) {
    throw new Error(payload.error.message || `RPC ${method} failed.`);
  }
  return payload.result;
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

  async getBalance({ seedPhrase, accountIndex = 0, network }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
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
    });
  }

  async getTokenBalance({ seedPhrase, tokenAddress, accountIndex = 0, network }) {
    return this.#withAccount({ seedPhrase, accountIndex, network }, async (account, runtimeConfig) => {
      const address = await account.getAddress();
      const token = normalizeAddress(tokenAddress, "tokenAddress");
      const balance = await account.getTokenBalance(token);
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        address,
        tokenAddress: token,
        balance,
        source: "wdk-wallet-evm",
      };
    });
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
      const quote = await account.quoteTransfer(transfer);
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        transfer,
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
      const result = await account.transfer(transfer);
      return {
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        accountIndex,
        transfer,
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
}
