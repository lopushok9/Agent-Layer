import { getAddress, hashMessage, hashTypedData, hexToBytes, isAddressEqual, isErc6492Signature, isHex, maxUint256, size, validateTypedData, type Address, type Hex, type TypedDataDefinition } from "viem";
import { parseSiweMessage } from "viem/siwe";
import { z } from "zod";
import type { ContractMetadata, ClearSigning } from "./contract-metadata.js";
import { chainIds, jsonValue, walletNetwork, type WalletNetwork } from "./transaction-builder.js";
import type { SmartWalletService } from "./smart-wallet.js";
import type { WalletSignature, WalletStore } from "./wallet-store.js";

const PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3";
const typedDataInput = z.strictObject({
  domain: z.record(z.string(), z.unknown()),
  types: z.record(z.string(), z.array(z.strictObject({ name: z.string().min(1).max(100), type: z.string().min(1).max(100) })).max(64)).refine(t => Object.keys(t).length <= 32, "too many types"),
  primaryType: z.string().min(1).max(100),
  message: z.record(z.string(), z.unknown()),
});
export const signatureInput = z.strictObject({
  network: walletNetwork,
  typed_data: typedDataInput.optional().describe("EIP-712 typed data as passed to eth_signTypedData_v4"),
  message: z.string().min(1).max(10_000).optional().describe("UTF-8 text to sign with personal_sign (EIP-191)"),
  message_hex: z.string().regex(/^0x(?:[0-9a-fA-F]{2})+$/).max(20_002).optional().describe("Raw bytes to sign with personal_sign (EIP-191)"),
}).refine(v => [v.typed_data, v.message, v.message_hex].filter(x => x !== undefined).length === 1, "provide exactly one of typed_data, message or message_hex");
export type SignatureInput = z.input<typeof signatureInput>;
export type SignaturePayload = { kind: "typed_data"; typedData: z.infer<typeof typedDataInput> } | { kind: "message"; message: string } | { kind: "message"; raw: Hex };
export type SignatureDescription = { summary: string; authorizations: string[]; warnings: string[]; siwe?: Record<string, unknown>; clear_signing?: ClearSigning; message_text?: string; typed_data?: unknown };

// eth_sign of arbitrary hashes is never offered: MetaMask and Rabby block it
// because a hash can be a transaction. Everything here is EIP-191 or EIP-712,
// and the Coinbase Smart Wallet then wraps it in its replay-safe
// CoinbaseSmartWalletMessage(bytes32), bound to this account and chain.
export function payload(input: SignatureInput): { network: WalletNetwork; payload: SignaturePayload } {
  if (JSON.stringify(input).length > 60_000) throw new Error("signature input is too large");
  const p = signatureInput.parse(input);
  if (p.typed_data) return { network: p.network, payload: { kind: "typed_data", typedData: p.typed_data } };
  if (p.message !== undefined) return { network: p.network, payload: { kind: "message", message: p.message } };
  return { network: p.network, payload: { kind: "message", raw: p.message_hex as Hex } };
}

export function signatureDigest(p: SignaturePayload): Hex {
  if (p.kind === "typed_data") return hashTypedData(definition(p.typedData));
  return hashMessage("raw" in p ? { raw: p.raw } : p.message);
}

export function definition(t: z.infer<typeof typedDataInput>): TypedDataDefinition {
  // eth_signTypedData_v4 payloads include EIP712Domain; viem derives it from domain.
  const { EIP712Domain: _domain, ...types } = t.types;
  return { domain: t.domain, types, primaryType: t.primaryType, message: t.message } as unknown as TypedDataDefinition;
}

export async function describeSignature(network: WalletNetwork, account: Address, owner: Address | undefined, p: SignaturePayload, contracts: ContractMetadata | null): Promise<SignatureDescription> {
  const warnings = ["An off-chain signature can be used by whoever receives it, later and without another confirmation. Sign only for the app the user is using now."];
  if (p.kind === "message") return describeMessage(network, account, p, warnings);
  const def = definition(p.typedData);
  try { validateTypedData(def as Parameters<typeof validateTypedData>[0]); hashTypedData(def); } catch (e) { throw new Error(`invalid EIP-712 typed data: ${e instanceof Error ? e.message.split("\n")[0] : String(e)}`); }
  const domain = p.typedData.domain, message = p.typedData.message;
  if (domain.chainId !== undefined && BigInt(domain.chainId as string | number | bigint) !== BigInt(chainIds[network])) throw new Error(`typed data is for chain ${String(domain.chainId)}, not ${network}; prepare it on that network`);
  if (domain.chainId === undefined) warnings.push("The domain has no chainId: the app could accept this signature on other chains where this account exists.");
  const verifying = typeof domain.verifyingContract === "string" ? getAddress(domain.verifyingContract) : undefined;
  // A request in the account's own domain is how replay-safe wrapping would be
  // bypassed; no app needs it, so it is refused instead of explained.
  if (p.typedData.primaryType === "CoinbaseSmartWalletMessage" || (verifying && [account, owner].some(a => a && isAddressEqual(a, verifying)))) throw new Error("typed data addressed to this wallet or its owner is refused");
  const authorizations = authorizationsOf(p.typedData.primaryType, verifying, message);
  const clear = contracts ? await contracts.describeTypedData(network, { ...p.typedData, domain: domain as never, types: p.typedData.types as never }, account) : null;
  return {
    summary: `EIP-712 ${p.typedData.primaryType}${typeof domain.name === "string" ? ` for ${domain.name.slice(0, 80)}` : ""}${verifying ? ` (${verifying})` : ""}`,
    authorizations, warnings: [...warnings, ...(authorizations.length ? ["This signature grants token access or an order on its own; no transaction preview will follow."] : [])],
    ...(clear ? { clear_signing: clear } : {}),
    typed_data: jsonValue({ domain, primaryType: p.typedData.primaryType, message }),
  };
}

function describeMessage(network: WalletNetwork, account: Address, p: Extract<SignaturePayload, { kind: "message" }>, warnings: string[]): SignatureDescription {
  let text = "message" in p ? p.message : undefined;
  if ("raw" in p) {
    // fatal: invalid UTF-8 must stay opaque bytes, not become U+FFFD "text".
    const decoded = (() => { try { return new TextDecoder("utf-8", { fatal: true }).decode(hexToBytes(p.raw)); } catch { return undefined; } })();
    if (decoded !== undefined && /^[\P{Cc}\n\r\t]*$/u.test(decoded)) text = decoded;
    else warnings.push(size(p.raw) === 32 ? "These bytes look like a hash: their meaning cannot be shown. Refuse unless the app documents exactly what they are." : "Opaque bytes: their meaning cannot be shown.");
  }
  // EIP-4361: the wallet, not the site, checks the address and chain, as MetaMask's
  // SIWE domain-binding check does. Callers that know the requesting origin also
  // compare it with siwe.domain.
  const siwe = text ? parseSiweMessage(text) : {};
  if (siwe.address && siwe.domain) {
    if (!isAddressEqual(siwe.address, account)) throw new Error("Sign-In with Ethereum message is for a different address");
    if (siwe.chainId !== undefined && siwe.chainId !== chainIds[network]) throw new Error(`Sign-In with Ethereum message is for chain ${siwe.chainId}, not ${network}`);
    if (siwe.expirationTime && siwe.expirationTime.getTime() < Date.now()) throw new Error("Sign-In with Ethereum message has expired");
    warnings.push(`Signs the user in to ${siwe.domain}. Confirm that is the site the user is using.`);
    return { summary: `Sign-In with Ethereum to ${siwe.domain}`, authorizations: [], warnings, siwe: jsonValue(siwe) as Record<string, unknown>, ...(text ? { message_text: text } : {}) };
  }
  return { summary: text ? "personal_sign text message" : "personal_sign raw bytes", authorizations: [], warnings, ...(text ? { message_text: text } : {}) };
}

// The well-known off-chain authorizations wallets single out (Rabby's and
// MetaMask's permit/Permit2/Seaport signature alerts): each moves funds later
// without a transaction from this account.
function authorizationsOf(primaryType: string, verifying: Address | undefined, m: Record<string, unknown>): string[] {
  const int = (v: unknown) => { try { return typeof v === "string" || typeof v === "number" || typeof v === "bigint" ? BigInt(v) : undefined; } catch { return undefined; } };
  const amount = (v: unknown) => { const n = int(v); return n === undefined ? String(v) : n >= maxUint256 / 2n ? "an unlimited amount" : n.toString(); };
  const until = (v: unknown) => { const n = int(v); return n === undefined ? "" : n === 0n ? " with no expiry" : n > 10n ** 11n ? " with a far-future expiry" : ` until ${new Date(Number(n) * 1000).toISOString()}`; };
  const token = verifying ? `token ${verifying}` : "the token";
  const out: string[] = [];
  if (verifying && isAddressEqual(verifying, PERMIT2)) {
    const details = m.details as Record<string, unknown> | Record<string, unknown>[] | undefined;
    const permitted = m.permitted as Record<string, unknown> | Record<string, unknown>[] | undefined;
    for (const d of [details, permitted].flat().filter(Boolean) as Record<string, unknown>[]) out.push(`Permit2 lets ${String(m.spender)} take ${amount(d.amount)} of token ${String(d.token)}${until(d.expiration ?? m.deadline ?? m.sigDeadline)}.`);
    if (!out.length) out.push(`Permit2 authorization ${primaryType} for spender ${String(m.spender)}.`);
  } else if (primaryType === "Permit" && "spender" in m) {
    if ("allowed" in m) out.push(`${m.allowed ? "Allows" : "Revokes"} ${String(m.spender)} to spend ${m.allowed ? "an unlimited amount" : "nothing"} of ${token}${until(m.expiry)}.`);
    else out.push(`Allows ${String(m.spender)} to spend ${amount(m.value)} of ${token}${until(m.deadline)}.`);
  } else if (primaryType === "OrderComponents" && Array.isArray(m.offer)) {
    out.push(`Seaport order: ${m.offer.length} offered item(s) can leave this wallet whenever someone fulfils it${until(m.endTime)}.`);
  } else {
    for (const key of ["spender", "operator", "delegatee", "delegate"]) if (key in m) out.push(`Names ${key} ${String(m[key])}; this may authorize that address to act for this wallet.`);
  }
  return out;
}

export function signatureFormat(signature: Hex) {
  return isHex(signature) && isErc6492Signature(signature) ? "erc6492_undeployed_account" : "erc1271_smart_account";
}

type SignBackend = Pick<SmartWalletService, "account" | "signTypedData" | "signMessage">;
type SignRepository = Pick<WalletStore, "createSignature" | "signature" | "reserveSignature" | "finishSignature">;

export class SignatureService {
  constructor(private wallets: SignBackend, private store: SignRepository, private ttl: number, private contracts: ContractMetadata | null = null) {}
  // origin: the requesting dApp's verified URL when known (WalletConnect). A SIWE
  // message for another domain is phishing for a session, so it is refused.
  async prepare(userId: string, input: SignatureInput, origin?: string) {
    const account = await this.wallets.account(userId);
    const p = payload(input);
    const description = await describeSignature(p.network, account.address, account.owners[0]?.address, p.payload, this.contracts);
    if (origin && typeof description.siwe?.domain === "string" && description.siwe.domain.toLowerCase() !== new URL(origin).host.toLowerCase()) throw new Error(`Sign-In with Ethereum domain ${description.siwe.domain} does not match the requesting app ${new URL(origin).host}`);
    const saved = await this.store.createSignature({ userId, network: p.network, address: account.address, payload: p.payload, digest: signatureDigest(p.payload), description }, this.ttl);
    return { ...publicSignature(saved), next_step: "Show the summary, authorizations, warnings and the full message to the user. After the user confirms this exact signature, call signature_execute once with its signature_id. Nothing has been signed." };
  }
  async execute(userId: string, id: string, purpose: string) {
    const s = await this.store.reserveSignature(userId, id, purpose);
    try {
      const account = await this.wallets.account(userId);
      if (account.address.toLowerCase() !== s.address.toLowerCase() || signatureDigest(s.payload) !== s.digest) throw new Error("signature preview no longer matches this wallet and message");
      const signature = s.payload.kind === "typed_data"
        ? await this.wallets.signTypedData(userId, s.network, definition(s.payload.typedData))
        : await this.wallets.signMessage(userId, s.network, "raw" in s.payload ? { raw: s.payload.raw } : s.payload.message);
      await this.store.finishSignature(s.id, "signed");
      return { signature_id: s.id, status: "signed", network: s.network, signer: s.address, digest: s.digest, signature, format: signatureFormat(signature), verification: "Verify with ERC-1271 isValidSignature on the smart account, or ERC-6492 (viem verifyHash) while it is undeployed. The owner EOA is not the signer." };
    } catch (error) {
      await this.store.finishSignature(s.id, "failed", error instanceof Error ? error.message.slice(0, 500) : String(error));
      throw error;
    }
  }
}

export function publicSignature(s: WalletSignature) {
  return { signature_id: s.id, kind: s.payload.kind, network: s.network, address: s.address, status: s.status, expires_at: s.expiresAt.toISOString(), digest: s.digest, ...s.description, error: s.error };
}
