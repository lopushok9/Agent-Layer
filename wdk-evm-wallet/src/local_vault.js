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

function assertNonNegativeInteger(value, fieldName) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${fieldName} must be a non-negative integer.`);
  }
  return parsed;
}

function sanitizeLabel(label) {
  const normalized = String(label ?? "").trim();
  return normalized || "EVM Wallet";
}

function assertValidNetwork(network, fieldName = "network") {
  const normalized = assertNonEmptyString(network, fieldName).toLowerCase();
  if (!["ethereum", "sepolia", "base", "base-sepolia"].includes(normalized)) {
    throw new Error(`${fieldName} must be one of: ethereum, sepolia, base, base-sepolia.`);
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
  cipher.setAAD(Buffer.from(`wdk-evm-wallet:${walletId}:v${VAULT_VERSION}`, "utf8"));
  const ciphertext = Buffer.concat([
    cipher.update(Buffer.from(seedPhrase, "utf8")),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();
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
  decipher.setAAD(Buffer.from(`wdk-evm-wallet:${walletId}:v${VAULT_VERSION}`, "utf8"));
  decipher.setAuthTag(tag);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return plaintext.toString("utf8");
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

export class LocalEvmVault {
  constructor(config) {
    this.config = config;
    this._unlocked = new Map();
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
    await this.unlockWallet({ walletId: wallet.walletId, password, timeoutSeconds: 0 });
    return {
      ...wallet,
      unlocked: true,
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
    await this.unlockWallet({ walletId: wallet.walletId, password, timeoutSeconds: 0 });
    return {
      ...wallet,
      unlocked: true,
      unlockExpiresAt: null,
    };
  }

  async listWallets() {
    this.#sweepExpiredUnlocked();
    const registry = await this.#loadRegistry();
    return registry.wallets.map((wallet) => {
      const unlocked = this._unlocked.get(wallet.walletId);
      return {
        ...wallet,
        unlocked: Boolean(unlocked),
        unlockExpiresAt: unlocked ? unlocked.expiresAt : null,
      };
    });
  }

  async getWallet({ walletId }) {
    this.#sweepExpiredUnlocked();
    const wallet = await this.#getWalletMetadata(assertNonEmptyString(walletId, "walletId"));
    const unlocked = this._unlocked.get(wallet.walletId);
    return {
      ...wallet,
      unlocked: Boolean(unlocked),
      unlockExpiresAt: unlocked ? unlocked.expiresAt : null,
    };
  }

  async unlockWallet({ walletId, password, timeoutSeconds }) {
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
    const ttl =
      timeoutSeconds === undefined || timeoutSeconds === null
        ? this.config.unlockTimeoutSeconds
        : assertNonNegativeInteger(timeoutSeconds, "timeoutSeconds");
    const expiresAt = ttl === 0 ? null : new Date(Date.now() + ttl * 1000).toISOString();
    this._unlocked.set(walletId, {
      seedPhrase: secret,
      expiresAt,
    });
    return {
      walletId,
      label: metadata.label,
      unlocked: true,
      unlockExpiresAt: expiresAt,
    };
  }

  async lockWallet({ walletId }) {
    this._unlocked.delete(assertNonEmptyString(walletId, "walletId"));
    return {
      walletId,
      unlocked: false,
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

    const unlocked = this._unlocked.get(id);
    if (unlocked) {
      this._unlocked.set(id, {
        seedPhrase,
        expiresAt: unlocked.expiresAt,
      });
    }

    return {
      walletId: id,
      label: metadata.label,
      passwordChanged: true,
      updatedAt,
      unlocked: Boolean(this._unlocked.get(id)),
      unlockExpiresAt: this._unlocked.get(id)?.expiresAt ?? null,
    };
  }

  async resolveSeedPhrase({ walletId, seedPhrase }) {
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
    this.#sweepExpiredUnlocked();
    const unlocked = this._unlocked.get(id);
    if (!unlocked) {
      throw new Error("Wallet is locked. Unlock it first or provide seedPhrase explicitly.");
    }
    return {
      seedPhrase: unlocked.seedPhrase,
      source: "local-vault",
      walletId: id,
      unlockExpiresAt: unlocked.expiresAt,
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

  #sweepExpiredUnlocked() {
    const now = Date.now();
    for (const [walletId, state] of this._unlocked.entries()) {
      if (state.expiresAt && Date.parse(state.expiresAt) <= now) {
        this._unlocked.delete(walletId);
      }
    }
  }
}
