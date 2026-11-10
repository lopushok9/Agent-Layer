import { createCipheriv, createDecipheriv, createHash, createPrivateKey, createPublicKey, generateKeyPairSync, randomBytes, sign as edSign, verify as edVerify, type KeyObject } from "node:crypto";
import { baseDecode, baseEncode } from "@near-js/utils";

// A NEAR account key that never leaves the service. Each signer exposes only
// its 32-byte ed25519 public key and a sign() used by the transaction builder
// after a preview was confirmed; no MCP tool can reach sign() with free input.
export type NearSignerKind = "sealed_key" | "cdp_solana";
export interface NearKeySigner {
  readonly kind: NearSignerKind;
  readonly publicKey: Uint8Array;
  sign(message: Uint8Array): Promise<Uint8Array>;
}

export const nearPublicKey = (raw: Uint8Array) => `ed25519:${baseEncode(raw)}`;
// Implicit account ID: lowercase hex of the ed25519 public key. The account
// exists on chain once it receives NEAR; until then it has no access key.
export const implicitAccountId = (raw: Uint8Array) => Buffer.from(raw).toString("hex");

export function ed25519PublicKeyObject(raw: Uint8Array): KeyObject {
  if (raw.length !== 32) throw new Error("ed25519 public key must be 32 bytes");
  return createPublicKey({ key: { kty: "OKP", crv: "Ed25519", x: Buffer.from(raw).toString("base64url") }, format: "jwk" });
}
export function verifyEd25519(raw: Uint8Array, message: Uint8Array, signature: Uint8Array): boolean {
  if (signature.length !== 64) return false;
  try { return edVerify(null, message, ed25519PublicKeyObject(raw), signature); } catch { return false; }
}

// Every signer output is checked against its own public key before it is
// attached to a transaction, so a provider that signs a different encoding of
// the message (or another key) fails closed and nothing is broadcast.
async function signVerified(signer: { publicKey: Uint8Array }, message: Uint8Array, produce: () => Promise<Uint8Array>): Promise<Uint8Array> {
  const signature = await produce();
  if (!verifyEd25519(signer.publicKey, message, signature)) throw new Error("NEAR signer returned a signature that does not verify for this account key; nothing was broadcast");
  return signature;
}

// ---- Sealed server key: AES-256-GCM, bound to the user by AAD. ----
const SEAL_VERSION = "v1";
const aad = (userId: string) => Buffer.from(`near-account-key:${SEAL_VERSION}:${userId}`);
function requireKey(key: string | undefined): Buffer {
  const k = key ? Buffer.from(key, "base64") : Buffer.alloc(0);
  if (k.length !== 32) throw new Error("NEAR_KEY_ENCRYPTION_KEY is not configured");
  return k;
}
export function sealSecret(pkcs8: Buffer, key: string | undefined, userId: string): string {
  const iv = randomBytes(12), cipher = createCipheriv("aes-256-gcm", requireKey(key), iv);
  cipher.setAAD(aad(userId));
  const body = Buffer.concat([cipher.update(pkcs8), cipher.final()]);
  return [SEAL_VERSION, iv.toString("base64"), body.toString("base64"), cipher.getAuthTag().toString("base64")].join(".");
}
export function openSecret(sealed: string, key: string | undefined, userId: string): Buffer {
  const [v, iv, body, tag] = sealed.split(".");
  if (v !== SEAL_VERSION || !iv || !body || !tag) throw new Error("invalid sealed NEAR key");
  const decipher = createDecipheriv("aes-256-gcm", requireKey(key), Buffer.from(iv, "base64"));
  decipher.setAAD(aad(userId)); decipher.setAuthTag(Buffer.from(tag, "base64"));
  return Buffer.concat([decipher.update(Buffer.from(body, "base64")), decipher.final()]);
}

export function generateSealedKey(key: string | undefined, userId: string): { publicKey: Uint8Array; sealed: string } {
  requireKey(key);
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const raw = Buffer.from(publicKey.export({ format: "jwk" }).x!, "base64url");
  return { publicKey: new Uint8Array(raw), sealed: sealSecret(privateKey.export({ format: "der", type: "pkcs8" }), key, userId) };
}

export class SealedKeySigner implements NearKeySigner {
  readonly kind = "sealed_key" as const;
  readonly publicKey: Uint8Array;
  private constructor(private privateKey: KeyObject, publicKey: Uint8Array) { this.publicKey = publicKey; }
  static open(sealed: string, key: string | undefined, userId: string, expectedPublicKey: Uint8Array): SealedKeySigner {
    const privateKey = createPrivateKey({ key: openSecret(sealed, key, userId), format: "der", type: "pkcs8" });
    const raw = new Uint8Array(Buffer.from(createPublicKey(privateKey).export({ format: "jwk" }).x!, "base64url"));
    if (Buffer.compare(Buffer.from(raw), Buffer.from(expectedPublicKey)) !== 0) throw new Error("sealed NEAR key does not match the registered account key");
    return new SealedKeySigner(privateKey, raw);
  }
  sign(message: Uint8Array): Promise<Uint8Array> {
    return signVerified(this, message, async () => new Uint8Array(edSign(null, message, this.privateKey)));
  }
}

// ---- CDP-managed Solana account (ed25519) as the NEAR key. ----
// The private key stays inside CDP. CDP's signMessage takes a string; whether
// raw bytes can be passed (and in which encoding) is verified by
// scripts/near-probe-cdp-signer.ts. Signatures are verified before use either way.
export type CdpMessageEncoding = "base64" | "hex" | "utf8";
export type CdpSolanaApi = {
  getOrCreateAccount(options: { name: string }): Promise<{ address: string }>;
  signMessage(options: { address: string; message: string; idempotencyKey?: string }): Promise<{ signature: string }>;
};
export function cdpNearAccountName(userId: string): string {
  // CDP names: 2-36 alphanumerics and hyphens. Separate namespace from EVM wallets.
  return `near-v1-${createHash("sha256").update(userId).digest("hex").slice(0, 24)}`;
}
export function encodeCdpMessage(message: Uint8Array, encoding: CdpMessageEncoding): string {
  if (encoding === "base64") return Buffer.from(message).toString("base64");
  if (encoding === "hex") return Buffer.from(message).toString("hex");
  return Buffer.from(message).toString("utf8");
}
export function decodeCdpSignature(signature: string): Uint8Array {
  const bytes = /^(0x)?[0-9a-fA-F]{128}$/.test(signature) ? Buffer.from(signature.replace(/^0x/, ""), "hex") : Buffer.from(baseDecode(signature));
  if (bytes.length !== 64) throw new Error("CDP returned a malformed ed25519 signature");
  return new Uint8Array(bytes);
}

export class CdpSolanaSigner implements NearKeySigner {
  readonly kind = "cdp_solana" as const;
  private constructor(private api: CdpSolanaApi, readonly address: string, readonly publicKey: Uint8Array, private encoding: CdpMessageEncoding) {}
  static async forName(api: CdpSolanaApi, name: string, encoding: CdpMessageEncoding, expectedPublicKey?: Uint8Array): Promise<CdpSolanaSigner> {
    const account = await api.getOrCreateAccount({ name });
    const raw = new Uint8Array(baseDecode(account.address));
    if (raw.length !== 32) throw new Error("CDP Solana address is not a 32-byte ed25519 key");
    if (expectedPublicKey && Buffer.compare(Buffer.from(raw), Buffer.from(expectedPublicKey)) !== 0) throw new Error("CDP NEAR key does not match the registered account key");
    return new CdpSolanaSigner(api, account.address, raw, encoding);
  }
  sign(message: Uint8Array): Promise<Uint8Array> {
    return signVerified(this, message, async () => decodeCdpSignature((await this.api.signMessage({ address: this.address, message: encodeCdpMessage(message, this.encoding) })).signature));
  }
}
