import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

import WDK from "@tetherto/wdk";

const scryptAsync = promisify(crypto.scrypt);

const REGISTRY_FILE = "registry.json";
const WALLETS_DIR = "wallets";
const VAULT_VERSION = 1;

function assertNonEmptyString(value, fieldName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${fieldName} is required.`);
  }
  return value.trim();
}

function assertPositiveInteger(value, fieldName) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${fieldName} must be a positive integer.`);
  }
  return parsed;
}

function sanitizeLabel(label) {
  const normalized = String(label ?? "").trim();
  return normalized || "BTC Wallet";
}

function assertValidNetwork(network, fieldName = "network") {
  const normalized = assertNonEmptyString(network, fieldName);
  if (!["bitcoin", "testnet", "regtest"].includes(normalized)) {
    throw new Error(`${fieldName} must be one of: bitcoin, testnet, regtest.`);
  }
  return normalized;
}

async function deriveKey(password, salt) {
  return scryptAsync(password, salt, 32, {
    N: 1 << 15,
    r: 8,
    p: 1,
    maxmem: 64 * 1024 * 1024,
  });
}

async function encryptSeedPhrase({ seedPhrase, password, walletId }) {
  const salt = crypto.randomBytes(16);
  const iv = crypto.randomBytes(12);
  const key = await deriveKey(password, salt);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from(`wdk-btc-wallet:${walletId}:v${VAULT_VERSION}`, "utf8"));
  const ciphertext = Buffer.concat([
    cipher.update(Buffer.from(seedPhrase, "utf8")),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();
  key.fill(0);
  return {
    version: VAULT_VERSION,
    kdf: {
      name: "scrypt",
      salt: salt.toString("base64"),
      N: 1 << 15,
      r: 8,
      p: 1,
    },
    cipher: {
      name: "aes-256-gcm",
      iv: iv.toString("base64"),
      tag: tag.toString("base64"),
    },
    ciphertext: ciphertext.toString("base64"),
  };
}

async function decryptSeedPhrase({ encrypted, password, walletId }) {
  const salt = Buffer.from(encrypted.kdf.salt, "base64");
  const iv = Buffer.from(encrypted.cipher.iv, "base64");
  const tag = Buffer.from(encrypted.cipher.tag, "base64");
  const ciphertext = Buffer.from(encrypted.ciphertext, "base64");
  const key = await deriveKey(password, salt);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAAD(Buffer.from(`wdk-btc-wallet:${walletId}:v${VAULT_VERSION}`, "utf8"));
  decipher.setAuthTag(tag);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  key.fill(0);
  // The returned string is an unavoidable transient (V8 strings are immutable);
  // the derived key and plaintext buffers are zeroized so no zeroizable secret lingers.
  const seedPhrase = plaintext.toString("utf8");
  plaintext.fill(0);
  return seedPhrase;
}

async function decryptSeedPhraseWithPasswordCheck(args) {
  try {
    return await decryptSeedPhrase(args);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (
      message.includes("authenticate data") ||
      message.includes("unable to authenticate") ||
      message.includes("Unsupported state")
    ) {
      throw new Error("Invalid password.");
    }
    throw error;
  }
}

export class LocalBtcVault {
  constructor(config) {
    this.config = config;
  }

  async createWallet({
    label = "",
    password,
    words = 12,
    revealSeedPhrase = false,
    network,
  }) {
    const count = assertPositiveInteger(words, "words");
    if (count !== 12) {
      throw new Error("Only 12-word wallet creation is currently supported.");
    }
    const seedPhrase = WDK.getRandomSeedPhrase();
    const wallet = await this.#storeWallet({
      label,
      password,
      seedPhrase,
      source: "created",
      network,
    });
    return {
      ...wallet,
      unlocked: false,
      unlockExpiresAt: null,
      ...(revealSeedPhrase ? { seedPhrase } : {}),
    };
  }

  async importWallet({ label = "", password, seedPhrase, network }) {
    const mnemonic = assertNonEmptyString(seedPhrase, "seedPhrase");
    if (!WDK.isValidSeed(mnemonic)) {
      throw new Error("seedPhrase must be a valid BIP-39 seed phrase.");
    }
    const wallet = await this.#storeWallet({
      label,
      password,
      seedPhrase: mnemonic,
      source: "imported",
      network,
    });
    return {
      ...wallet,
      unlocked: false,
      unlockExpiresAt: null,
    };
  }

  async listWallets() {
    const registry = await this.#loadRegistry();
    return registry.wallets.map((wallet) => ({
      ...wallet,
      unlocked: false,
      unlockExpiresAt: null,
    }));
  }

  async getWallet({ walletId }) {
    const wallet = await this.#getWalletMetadata(assertNonEmptyString(walletId, "walletId"));
    return {
      ...wallet,
      unlocked: false,
      unlockExpiresAt: null,
    };
  }

  // Deprecated: the wallet now uses a decrypt-on-demand model and never holds a
  // plaintext seed in memory between requests. This endpoint only verifies the
  // password so callers get feedback; it does not persist any unlocked state.
  async unlockWallet({ walletId, password }) {
    const metadata = await this.#getWalletMetadata(assertNonEmptyString(walletId, "walletId"));
    const encrypted = await this.#loadEncryptedWallet(walletId);
    const secret = await decryptSeedPhraseWithPasswordCheck({
      encrypted,
      password: assertNonEmptyString(password, "password"),
      walletId,
    });
    if (!WDK.isValidSeed(secret)) {
      throw new Error("Decrypted wallet seed phrase is invalid.");
    }
    return {
      walletId,
      label: metadata.label,
      unlocked: false,
      unlockExpiresAt: null,
      deprecated: true,
    };
  }

  // Deprecated no-op: the wallet is always sealed at rest in the decrypt-on-demand model.
  async lockWallet({ walletId }) {
    return {
      walletId: assertNonEmptyString(walletId, "walletId"),
      unlocked: false,
      deprecated: true,
    };
  }

  async revealSeedPhrase({ walletId, password }) {
    const id = assertNonEmptyString(walletId, "walletId");
    const metadata = await this.#getWalletMetadata(id);
    const encrypted = await this.#loadEncryptedWallet(id);
    const seedPhrase = await decryptSeedPhraseWithPasswordCheck({
      encrypted,
      password: assertNonEmptyString(password, "password"),
      walletId: id,
    });
    if (!WDK.isValidSeed(seedPhrase)) {
      throw new Error("Decrypted wallet seed phrase is invalid.");
    }
    return {
      walletId: id,
      label: metadata.label,
      seedPhrase,
    };
  }

  async changePassword({ walletId, currentPassword, newPassword }) {
    const id = assertNonEmptyString(walletId, "walletId");
    const safeCurrentPassword = assertNonEmptyString(currentPassword, "currentPassword");
    const safeNewPassword = assertNonEmptyString(newPassword, "newPassword");
    const metadata = await this.#getWalletMetadata(id);
    const encrypted = await this.#loadEncryptedWallet(id);
    const seedPhrase = await decryptSeedPhraseWithPasswordCheck({
      encrypted,
      password: safeCurrentPassword,
      walletId: id,
    });
    if (!WDK.isValidSeed(seedPhrase)) {
      throw new Error("Decrypted wallet seed phrase is invalid.");
    }
    const reencrypted = await encryptSeedPhrase({
      seedPhrase,
      password: safeNewPassword,
      walletId: id,
    });
    await fs.writeFile(this.#walletFilePath(id), JSON.stringify(reencrypted, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });

    const registry = await this.#loadRegistry();
    const index = registry.wallets.findIndex((wallet) => wallet.walletId === id);
    if (index === -1) {
      throw new Error(`Unknown walletId: ${id}`);
    }
    const updatedAt = new Date().toISOString();
    registry.wallets[index] = {
      ...registry.wallets[index],
      updatedAt,
    };
    await this.#saveRegistry(registry);

    return {
      walletId: id,
      label: metadata.label,
      passwordChanged: true,
      updatedAt,
      unlocked: false,
      unlockExpiresAt: null,
    };
  }

  // Decrypt-on-demand: the seed is decrypted just-in-time for a single signing
  // request from the supplied password, never persisted between requests.
  async resolveSeedPhrase({ walletId, seedPhrase, password }) {
    if (typeof seedPhrase === "string" && seedPhrase.trim()) {
      if (!WDK.isValidSeed(seedPhrase.trim())) {
        throw new Error("seedPhrase must be a valid BIP-39 seed phrase.");
      }
      return {
        seedPhrase: seedPhrase.trim(),
        source: "request",
        walletId: null,
      };
    }
    const id = assertNonEmptyString(walletId, "walletId");
    if (typeof password !== "string" || !password.trim()) {
      throw new Error("Wallet is locked. Provide password or seedPhrase explicitly.");
    }
    await this.#getWalletMetadata(id);
    const encrypted = await this.#loadEncryptedWallet(id);
    const secret = await decryptSeedPhraseWithPasswordCheck({
      encrypted,
      password: password.trim(),
      walletId: id,
    });
    if (!WDK.isValidSeed(secret)) {
      throw new Error("Decrypted wallet seed phrase is invalid.");
    }
    return {
      seedPhrase: secret,
      source: "local-vault-jit",
      walletId: id,
    };
  }

  async #storeWallet({ label, password, seedPhrase, source, network }) {
    const safePassword = assertNonEmptyString(password, "password");
    await this.#ensureLayout();

    const walletId = crypto.randomUUID();
    const now = new Date().toISOString();
    const encrypted = await encryptSeedPhrase({
      seedPhrase,
      password: safePassword,
      walletId,
    });
    const entry = {
      walletId,
      label: sanitizeLabel(label),
      createdAt: now,
      updatedAt: now,
      network: assertValidNetwork(network ?? this.config.network, "network"),
      bip: this.config.bip,
      source,
    };

    await fs.writeFile(this.#walletFilePath(walletId), JSON.stringify(encrypted, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });
    const registry = await this.#loadRegistry();
    registry.wallets.push(entry);
    await this.#saveRegistry(registry);

    return {
      walletId,
      label: entry.label,
      createdAt: entry.createdAt,
      updatedAt: entry.updatedAt,
      network: entry.network,
      bip: entry.bip,
      source: entry.source,
    };
  }

  async #getWalletMetadata(walletId) {
    const registry = await this.#loadRegistry();
    const wallet = registry.wallets.find((item) => item.walletId === walletId);
    if (!wallet) {
      throw new Error(`Unknown walletId: ${walletId}`);
    }
    return wallet;
  }

  async #loadEncryptedWallet(walletId) {
    const raw = await fs.readFile(this.#walletFilePath(walletId), "utf8");
    return JSON.parse(raw);
  }

  async #ensureLayout() {
    await fs.mkdir(this.config.dataDir, { recursive: true, mode: 0o700 });
    await fs.mkdir(path.join(this.config.dataDir, WALLETS_DIR), {
      recursive: true,
      mode: 0o700,
    });
    try {
      await fs.access(this.#registryPath());
    } catch {
      await this.#saveRegistry({
        version: VAULT_VERSION,
        wallets: [],
      });
    }
  }

  async #loadRegistry() {
    await this.#ensureLayout();
    const raw = await fs.readFile(this.#registryPath(), "utf8");
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.wallets)) {
      throw new Error("Vault registry is invalid.");
    }
    return parsed;
  }

  async #saveRegistry(registry) {
    await fs.writeFile(this.#registryPath(), JSON.stringify(registry, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });
  }

  #walletFilePath(walletId) {
    return path.join(this.config.dataDir, WALLETS_DIR, `${walletId}.json`);
  }

  #registryPath() {
    return path.join(this.config.dataDir, REGISTRY_FILE);
  }
}
