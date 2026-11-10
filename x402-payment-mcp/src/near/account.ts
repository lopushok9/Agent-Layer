import { baseDecode } from "@near-js/utils";
import type { NearConfig } from "./config.js";
import { CdpSolanaSigner, cdpNearAccountName, generateSealedKey, implicitAccountId, nearPublicKey, SealedKeySigner, type CdpSolanaApi, type NearKeySigner } from "./keys.js";
import type { NearRpc } from "./rpc.js";
import type { NearAccountRecord, NearStore } from "./store.js";
import { formatNear } from "./units.js";

// Storage staking: 10^19 yoctoNEAR per byte (protocol storage_amount_per_byte).
export const STORAGE_BYTE_COST = 10n ** 19n;

// One NEAR implicit account per user and network, created on first use. The
// account key is either a sealed server key or a CDP-managed ed25519 key; it is
// a new identity that existing AgentLayer wallets never fund or sign for.
export class NearAccountService {
  constructor(readonly config: NearConfig, private store: Pick<NearStore, "account" | "saveAccount">, readonly rpc: NearRpc, private cdp?: CdpSolanaApi) {}

  async account(userId: string): Promise<NearAccountRecord> {
    const existing = await this.store.account(userId, this.config.network);
    if (existing) return existing;
    if (this.config.signer === "cdp_solana") {
      if (!this.cdp) throw new Error("CDP signer is not configured");
      const name = cdpNearAccountName(userId);
      const signer = await CdpSolanaSigner.forName(this.cdp, name, this.config.cdpMessageEncoding);
      return this.store.saveAccount({ userId, network: this.config.network, accountId: implicitAccountId(signer.publicKey), publicKey: nearPublicKey(signer.publicKey), signerKind: "cdp_solana", cdpAccountName: name, sealedKey: null });
    }
    const { publicKey, sealed } = generateSealedKey(this.config.keyEncryptionKey, userId);
    return this.store.saveAccount({ userId, network: this.config.network, accountId: implicitAccountId(publicKey), publicKey: nearPublicKey(publicKey), signerKind: "sealed_key", cdpAccountName: null, sealedKey: sealed });
  }

  // Opens the signer recorded for the account (not the current default), and
  // proves it still matches the registered key and implicit account ID.
  async signer(record: NearAccountRecord): Promise<NearKeySigner> {
    const expected = publicKeyBytes(record.publicKey);
    if (implicitAccountId(expected) !== record.accountId) throw new Error("NEAR account registry mismatch");
    if (record.signerKind === "sealed_key") return SealedKeySigner.open(record.sealedKey!, this.config.keyEncryptionKey, record.userId, expected);
    if (!this.cdp) throw new Error("CDP signer is not configured");
    return CdpSolanaSigner.forName(this.cdp, record.cdpAccountName!, this.config.cdpMessageEncoding, expected);
  }

  async status(userId: string) {
    const record = await this.account(userId);
    await this.rpc.assertNetwork();
    const [view, keys] = await Promise.all([this.rpc.viewAccount(record.accountId), this.rpc.viewAccessKeyList(record.accountId)]);
    const ours = keys.find(k => k.public_key === record.publicKey);
    const others = keys.filter(k => k.public_key !== record.publicKey).map(k => ({ public_key: k.public_key, permission: k.access_key.permission }));
    const amount = BigInt(view?.amount ?? "0"), locked = BigInt(view?.locked ?? "0");
    const storageLocked = BigInt(view?.storage_usage ?? 0) * STORAGE_BYTE_COST;
    const available = amount > storageLocked ? amount - storageLocked : 0n;
    return {
      product: "agentlayer_near_omni_account",
      network: this.config.network,
      account_id: record.accountId,
      account_type: "near_implicit",
      public_key: record.publicKey,
      signing: record.signerKind === "cdp_solana" ? "managed_cdp_ed25519" : "managed_sealed_server_key",
      exists_on_chain: Boolean(view),
      balance: { total_yocto: amount.toString(), total_near: formatNear(amount), staked_yocto: locked.toString(), storage_locked_yocto: storageLocked.toString(), available_yocto: available.toString(), available_near: formatNear(available) },
      storage_usage_bytes: view?.storage_usage ?? 0,
      service_key_active: ours ? ours.access_key.permission === "FullAccess" : false,
      ...(others.length ? { other_access_keys: others, warning: "This account has access keys not created by AgentLayer." } : {}),
      receive: view
        ? `Send NEAR or NEP-141 tokens on NEAR ${this.config.network} to ${record.accountId}.`
        : `Account is not active yet. Send at least 0.01 NEAR on NEAR ${this.config.network} to ${record.accountId}; the first deposit creates it. This is a new AgentLayer NEAR account, separate from your Base/Ethereum wallets.`,
      custody: "Service-managed key: AgentLayer signs only operations you confirmed from an exact preview. This is not a self-custodial wallet.",
    };
  }
}

export function publicKeyBytes(publicKey: string): Uint8Array {
  if (!publicKey.startsWith("ed25519:")) throw new Error("unsupported NEAR key type");
  const raw = new Uint8Array(baseDecode(publicKey.slice("ed25519:".length)));
  if (raw.length !== 32) throw new Error("invalid NEAR public key");
  return raw;
}
