import { createHash } from "node:crypto";
import { z } from "zod";
import { PublicKey, KeyType } from "@near-js/crypto";
import { actionCreators, createTransaction, encodeTransaction, Signature, SignedTransaction, type Transaction } from "@near-js/transactions";
import { baseDecode, baseEncode } from "@near-js/utils";
import { assertAccountId, formatNear, formatTgas, GAS_PER_TGAS, MAX_TRANSACTION_GAS, parseGas, parseYocto } from "./units.js";
import { nearPublicKey, type NearKeySigner } from "./keys.js";

// Universal NEAR transaction builder. Only value-moving actions an agent may
// legitimately need are exposed: Transfer and FunctionCall. Key management,
// deploy, stake and delete-account actions are deliberately not reachable from
// MCP, so an agent can never add a key to or delete the user's account.
export const MAX_ACTIONS = 10;
export const MAX_ARGS_BYTES = 16 * 1024;
export const DEFAULT_FUNCTION_CALL_GAS = 30n * GAS_PER_TGAS;

const yocto = z.string().regex(/^\d{1,40}$/, "integer yoctoNEAR string (1 NEAR = 10^24)");
const gas = z.string().regex(/^\d{1,20}$/, "integer gas string (1 TGas = 10^12)");
const methodName = z.string().min(1).max(256).regex(/^[A-Za-z_][A-Za-z0-9_]*$/, "invalid method name");

export const nearActionInput = z.discriminatedUnion("type", [
  z.strictObject({ type: z.literal("transfer"), amount_yocto: yocto.describe("NEAR to send in yoctoNEAR") }),
  z.strictObject({
    type: z.literal("function_call"),
    method_name: methodName,
    args: z.record(z.string(), z.unknown()).optional().describe("JSON arguments object; serialized exactly as shown in the preview"),
    args_base64: z.string().max(Math.ceil(MAX_ARGS_BYTES / 3) * 4).regex(/^[A-Za-z0-9+/]*={0,2}$/).optional().describe("Raw (non-JSON) argument bytes, base64. Use args for JSON contracts."),
    gas: gas.optional().describe("Prepaid gas; default 30 TGas (30000000000000)"),
    deposit_yocto: yocto.default("0").describe("Attached deposit in yoctoNEAR; many token methods require exactly 1"),
  }).refine(v => !(v.args && v.args_base64), "provide args or args_base64, not both"),
]);
export type NearActionInput = z.infer<typeof nearActionInput>;
export const nearTransactionInput = z.strictObject({
  receiver_id: z.string().min(2).max(64).describe("Contract or account that receives every action"),
  actions: z.array(nearActionInput).min(1).max(MAX_ACTIONS),
});
export type NearTransactionInput = z.infer<typeof nearTransactionInput>;

// Normalized, persisted form. args are the exact bytes that will be signed.
export type NormalizedNearAction =
  | { type: "transfer"; amount: string }
  | { type: "function_call"; method: string; args_base64: string; gas: string; deposit: string };
export type NormalizedNearTransaction = { receiverId: string; actions: NormalizedNearAction[] };

export function normalizeNearTransaction(input: NearTransactionInput): NormalizedNearTransaction {
  const receiverId = assertAccountId(input.receiver_id, "receiver_id");
  let totalGas = 0n;
  const actions = input.actions.map((a): NormalizedNearAction => {
    if (a.type === "transfer") {
      const amount = parseYocto(a.amount_yocto, "amount_yocto");
      if (amount === 0n) throw new Error("transfer amount must be positive");
      return { type: "transfer", amount: amount.toString() };
    }
    const bytes = a.args_base64 !== undefined ? Buffer.from(a.args_base64, "base64") : Buffer.from(JSON.stringify(a.args ?? {}), "utf8");
    if (bytes.length > MAX_ARGS_BYTES) throw new Error(`function call args exceed ${MAX_ARGS_BYTES} bytes`);
    const g = a.gas !== undefined ? parseGas(a.gas) : DEFAULT_FUNCTION_CALL_GAS;
    totalGas += g;
    return { type: "function_call", method: a.method_name, args_base64: bytes.toString("base64"), gas: g.toString(), deposit: parseYocto(a.deposit_yocto, "deposit_yocto").toString() };
  });
  if (totalGas > MAX_TRANSACTION_GAS) throw new Error("total prepaid gas exceeds 300 TGas");
  return { receiverId, actions };
}

export function totals(tx: NormalizedNearTransaction) {
  let deposit = 0n, gasTotal = 0n;
  for (const a of tx.actions) {
    if (a.type === "transfer") deposit += BigInt(a.amount);
    else { deposit += BigInt(a.deposit); gasTotal += BigInt(a.gas); }
  }
  return { deposit, gas: gasTotal };
}

// Human description shown in the preview. Decoded args are untrusted data.
export function describeNearTransaction(tx: NormalizedNearTransaction) {
  return tx.actions.map((a, index) => {
    if (a.type === "transfer") return { index, type: "transfer", receiver_id: tx.receiverId, amount_yocto: a.amount, amount_near: formatNear(BigInt(a.amount)) };
    const raw = Buffer.from(a.args_base64, "base64");
    let args: unknown;
    try { args = JSON.parse(raw.toString("utf8")); } catch { args = { base64: a.args_base64 }; }
    return { index, type: "function_call", contract_id: tx.receiverId, method_name: a.method, args, args_bytes: raw.length, gas: a.gas, gas_tgas: formatTgas(BigInt(a.gas)), deposit_yocto: a.deposit, deposit_near: formatNear(BigInt(a.deposit)), ...knownMethodNote(a.method, args, tx.receiverId) };
  });
}

function knownMethodNote(method: string, args: unknown, contract: string): { note?: string } {
  const a = (args && typeof args === "object" ? args : {}) as Record<string, unknown>;
  if (method === "ft_transfer" || method === "ft_transfer_call") return { note: `NEP-141 token ${contract}: sends raw amount ${String(a.amount)} to ${String(a.receiver_id)}${method === "ft_transfer_call" ? " and calls it with msg" : ""}. Amount is in the token's smallest unit.` };
  if (method === "storage_deposit") return { note: `Registers storage on ${contract} for ${String(a.account_id ?? "the signer")}; the attached deposit pays for it.` };
  if (method === "near_deposit") return { note: `Wraps the attached NEAR into ${contract}.` };
  if (method === "near_withdraw") return { note: `Unwraps ${String(a.amount)} yocto wNEAR from ${contract}.` };
  return {};
}

// Binding of a preview: network, signer account and key, and the exact actions.
export function nearFingerprint(network: string, signerId: string, publicKey: string, tx: NormalizedNearTransaction): string {
  return createHash("sha256").update(JSON.stringify(["near-tx:v1", network, signerId, publicKey, tx.receiverId, tx.actions])).digest("hex");
}

function toAction(a: NormalizedNearAction) {
  if (a.type === "transfer") return actionCreators.transfer(BigInt(a.amount));
  return actionCreators.functionCall(a.method, new Uint8Array(Buffer.from(a.args_base64, "base64")), BigInt(a.gas), BigInt(a.deposit));
}

export function buildNearTransaction(signerId: string, publicKey: Uint8Array, nonce: bigint, blockHash: string, tx: NormalizedNearTransaction): Transaction {
  const hash = baseDecode(blockHash);
  if (hash.length !== 32) throw new Error("invalid block hash");
  return createTransaction(signerId, PublicKey.from(nearPublicKey(publicKey)), tx.receiverId, nonce, tx.actions.map(toAction), hash);
}

// NEAR signs sha256(borsh(Transaction)); the transaction hash is that digest in base58.
export function transactionDigest(transaction: Transaction): Uint8Array {
  return new Uint8Array(createHash("sha256").update(encodeTransaction(transaction)).digest());
}

export async function signNearTransaction(transaction: Transaction, signer: NearKeySigner): Promise<{ hash: string; signedBase64: string }> {
  if (Buffer.compare(Buffer.from(transaction.publicKey.data), Buffer.from(signer.publicKey)) !== 0) throw new Error("transaction key does not match signer");
  const digest = transactionDigest(transaction);
  const data = await signer.sign(digest);
  const signed = new SignedTransaction({ transaction, signature: new Signature({ keyType: KeyType.ED25519, data }) });
  return { hash: baseEncode(digest), signedBase64: Buffer.from(encodeTransaction(signed)).toString("base64") };
}
