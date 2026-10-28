import { randomUUID } from "node:crypto";
import type { Pool } from "pg";
import type { Address, Hex } from "viem";
import type { CallDescription, NormalizedCall, WalletNetwork } from "./transaction-builder.js";
import type { SwapPlan } from "./swap-plan.js";

import { sealOperation, openOperation, validateOperation, type PreparedOperation, type OperationProof } from "./user-operation.js";

export type SmartWalletRecord = { ownerName: string; ownerAddress: Address; accountName: string; address: Address };
// replaces: an unresolved cancellation of the same target re-signed at its own
// nonce with higher fees (see alchemy-executor SendOptions.replace).
export type CancelPlan = { targetId: string; targetHash: Hex; targetNonce: string; entryPoint: Address; fromBlock: string; replaces?: { id: string; nonce: string; maxFeePerGas: string; maxPriorityFeePerGas: string } };
export type OperationState = "prepared" | "reserved" | "signing" | "submitted" | "confirmed" | "failed" | "unknown" | "cancelled";
export type WalletOperation = {
  id: string; userId: string; network: WalletNetwork; address: Address;
  calls: NormalizedCall[]; descriptions: CallDescription[]; fingerprint: string;
  simulation: Record<string, unknown>; expiresAt: Date; status: OperationState;
  userOpHash: Hex | null; transactionHash: Hex | null; error: string | null;
  proof?: OperationProof | null;
  cancelPlan?: CancelPlan | null;
  kind?: "calls" | "swap" | "cancel"; swapPlan?: SwapPlan | null;
};
export class WalletStore {
  constructor(readonly pool: Pool, private operationKey?: string) {}
  async wallet(userId: string): Promise<SmartWalletRecord | null> {
    const r = await this.pool.query("SELECT * FROM smart_wallets WHERE user_id=$1", [userId]);
    const x = r.rows[0];
    return x ? { ownerName: x.owner_name, ownerAddress: x.owner_address, accountName: x.account_name, address: x.address } : null;
  }
  async walletByAddress(userId: string, address: Address): Promise<SmartWalletRecord | null> {
    const r = await this.pool.query(`SELECT owner_name,owner_address,account_name,address FROM smart_wallets WHERE user_id=$1 AND lower(address)=lower($2)
      UNION ALL SELECT owner_name,owner_address,account_name,address FROM smart_wallet_history WHERE user_id=$1 AND lower(address)=lower($2) LIMIT 1`, [userId, address]);
    const x = r.rows[0];
    return x ? { ownerName: x.owner_name, ownerAddress: x.owner_address, accountName: x.account_name, address: x.address } : null;
  }
  // Temporarily disabled with the one-time operator script. Historical reads
  // and per-address operation guards remain active for existing wallets.
  /*
  // Operator-only: call under Store.withPaymentLock. No MCP endpoint exposes
  // replacement. Compare-and-swap plus an immutable archive makes retries safe.
  async replaceWallet(userId: string, expected: Address, next: SmartWalletRecord, requestId: string, reason: string) {
    if (next.address.toLowerCase() === expected.toLowerCase() || next.address.toLowerCase() === next.ownerAddress.toLowerCase()) throw new Error("replacement must be a distinct smart account");
    const c = await this.pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", [`smart-operation:${userId}`]);
      const r = await c.query("SELECT * FROM smart_wallets WHERE user_id=$1 FOR UPDATE", [userId]);
      const old = r.rows[0];
      if (!old) throw new Error("smart wallet not found for replacement");
      const prior = await c.query("SELECT * FROM smart_wallet_history WHERE replacement_request_id=$1", [requestId]);
      if (prior.rows[0]) {
        const p = prior.rows[0];
        if (p.user_id !== userId || p.address.toLowerCase() !== expected.toLowerCase() || p.replacement_address.toLowerCase() !== next.address.toLowerCase() || old.address.toLowerCase() !== next.address.toLowerCase() || old.owner_address.toLowerCase() !== next.ownerAddress.toLowerCase() || old.owner_name !== next.ownerName || old.account_name !== next.accountName) throw new Error("replacement request does not match current wallet");
        await c.query("COMMIT"); return;
      }
      if (old.address.toLowerCase() !== expected.toLowerCase()) throw new Error("active wallet changed; replacement stopped");
      const used = await c.query("SELECT address FROM smart_wallet_history WHERE lower(address)=lower($1) UNION ALL SELECT address FROM smart_wallets WHERE lower(address)=lower($1)", [next.address]);
      if (used.rowCount) throw new Error("replacement address is already registered");
      await c.query(`INSERT INTO smart_wallet_history(address,user_id,owner_name,owner_address,account_name,original_created_at,replacement_address,replacement_request_id,reason) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, [old.address,userId,old.owner_name,old.owner_address,old.account_name,old.created_at,next.address,requestId,reason]);
      await c.query("UPDATE smart_wallets SET owner_name=$2,owner_address=$3,account_name=$4,address=$5,created_at=now() WHERE user_id=$1", [userId,next.ownerName,next.ownerAddress,next.accountName,next.address]);
      await c.query("COMMIT");
    } catch (e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
  }
  */
  async saveWallet(userId: string, w: SmartWalletRecord) {
    await this.pool.query(`INSERT INTO smart_wallets(user_id,owner_name,owner_address,account_name,address) VALUES($1,$2,$3,$4,$5) ON CONFLICT(user_id) DO NOTHING`, [userId, w.ownerName, w.ownerAddress, w.accountName, w.address]);
    const actual = await this.wallet(userId);
    if (!actual || actual.address.toLowerCase() !== w.address.toLowerCase() || actual.ownerAddress.toLowerCase() !== w.ownerAddress.toLowerCase()) throw new Error("smart wallet registry mismatch");
  }
  async createOperation(p: Omit<WalletOperation, "id" | "expiresAt" | "status" | "userOpHash" | "transactionHash" | "error">, ttl: number) {
    const id = randomUUID();
    await this.pool.query(`INSERT INTO wallet_operations(id,user_id,network,address,calls,descriptions,fingerprint,simulation,expires_at,kind,swap_plan,cancel_plan) VALUES($1,$2,$3,$4,$5,$6,$7,$8,now()+($9*interval '1 second'),$10,$11,$12)`, [id, p.userId, p.network, p.address, JSON.stringify(p.calls), JSON.stringify(p.descriptions), p.fingerprint, JSON.stringify(p.simulation), ttl, p.kind ?? "calls", p.swapPlan ? JSON.stringify(p.swapPlan) : null, p.cancelPlan ? JSON.stringify(p.cancelPlan) : null]);
    return (await this.operation(p.userId, id))!;
  }
  async operation(userId: string, id: string): Promise<WalletOperation | null> {
    const r = await this.pool.query("SELECT * FROM wallet_operations WHERE user_id=$1 AND id=$2", [userId, id]);
    return r.rows[0] ? mapOperation(r.rows[0]) : null;
  }
  async reserve(userId: string, id: string, purpose: string, kind: "calls" | "swap" = "calls"): Promise<WalletOperation> {
    const c = await this.pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", [`smart-operation:${userId}`]);
      const r = await c.query(`SELECT * FROM wallet_operations WHERE id=$1 AND user_id=$2 FOR UPDATE`, [id, userId]);
      if (!r.rows[0]) throw new Error("operation not found for this user");
      const x = r.rows[0];
      if (x.kind !== kind) throw new Error("operation type does not match this execution tool");
      if (x.status !== "prepared" || x.consumed_at) throw new Error("preview already consumed; check transaction_status, never submit it again");
      const pending = await c.query(`SELECT id FROM wallet_operations WHERE user_id=$1 AND network=$2 AND lower(address)=lower($3) AND status IN ('reserved','signing','submitted','unknown') LIMIT 1`, [userId, x.network, x.address]);
      if (pending.rowCount) throw new Error("an unresolved operation exists on this network; reconcile it before another execution");
      const saved = await c.query(`UPDATE wallet_operations SET status='reserved',purpose=$3,consumed_at=now(),updated_at=now() WHERE id=$1 AND user_id=$2 AND expires_at>now() RETURNING *`, [id, userId, purpose]);
      if (!saved.rows[0]) throw new Error("preview expired; prepare a new operation");
      await c.query("COMMIT");
      return mapOperation(saved.rows[0]);
    } catch (e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
  }
  async reserveCancellation(userId: string, id: string, purpose: string): Promise<WalletOperation> {
    const c = await this.pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", [`smart-operation:${userId}`]);
      const r = await c.query("SELECT * FROM wallet_operations WHERE id=$1 AND user_id=$2 FOR UPDATE", [id, userId]);
      const x = r.rows[0], plan = x?.cancel_plan as CancelPlan | undefined;
      if (!x || x.kind !== "cancel" || !plan) throw new Error("cancellation preview not found for this user");
      if (x.status !== "prepared" || x.consumed_at) throw new Error("preview already consumed; check transaction_status, never submit it again");
      const target = await c.query("SELECT * FROM wallet_operations WHERE id=$1 AND user_id=$2 AND network=$3 FOR UPDATE", [plan.targetId, userId, x.network]);
      const t = target.rows[0];
      if (!t || t.address.toLowerCase() !== x.address.toLowerCase() || t.kind === "cancel" || !["signing","submitted","unknown"].includes(t.status) || t.user_op_hash !== plan.targetHash || t.operation_proof?.nonce !== plan.targetNonce || !t.operation_ciphertext) throw new Error("cancellation target is no longer eligible");
      if (plan.replaces) {
        const r2 = await c.query("SELECT * FROM wallet_operations WHERE id=$1 AND user_id=$2 FOR UPDATE", [plan.replaces.id, userId]);
        const y = r2.rows[0];
        if (!y || y.kind !== "cancel" || y.cancel_plan?.targetId !== plan.targetId || y.address.toLowerCase() !== x.address.toLowerCase() || !["signing","submitted","unknown"].includes(y.status) || y.operation_proof?.nonce !== plan.replaces.nonce) throw new Error("replaced cancellation is no longer pending");
      }
      // Versions of this cancellation at the replaced nonce are mutually exclusive
      // on chain, so they do not block a higher-fee version of themselves.
      const other = await c.query("SELECT id FROM wallet_operations WHERE user_id=$1 AND network=$2 AND status IN ('reserved','signing','submitted','unknown') AND id<>$3 AND lower(address)=lower($4) AND NOT ($5::text IS NOT NULL AND kind='cancel' AND cancel_plan->>'targetId'=$3::text AND operation_proof->>'nonce'=$5) LIMIT 1", [userId, x.network, plan.targetId, x.address, plan.replaces?.nonce ?? null]);
      if (other.rowCount) throw new Error("another unresolved operation prevents cancellation");
      const saved = await c.query("UPDATE wallet_operations SET status='reserved',purpose=$3,consumed_at=now(),updated_at=now() WHERE id=$1 AND user_id=$2 AND expires_at>now() RETURNING *", [id, userId, purpose]);
      if (!saved.rows[0]) throw new Error("preview expired; prepare a new operation");
      await c.query("COMMIT"); return mapOperation(saved.rows[0]);
    } catch (e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
  }
  async pendingCancellations(userId: string, targetId: string): Promise<WalletOperation[]> {
    const r = await this.pool.query("SELECT * FROM wallet_operations WHERE user_id=$1 AND kind='cancel' AND cancel_plan->>'targetId'=$2 AND status IN ('reserved','signing','submitted','unknown') ORDER BY created_at", [userId, targetId]);
    return r.rows.map(mapOperation);
  }
  async finishCancellation(userId: string, id: string, txHash: Hex, targetState: "cancelled" | "confirmed" | "failed", targetTx: Hex | null) {
    const c = await this.pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", [`smart-operation:${userId}`]);
      const r = await c.query("SELECT * FROM wallet_operations WHERE user_id=$1 AND id=$2 FOR UPDATE", [userId, id]);
      const x = r.rows[0], plan = x?.cancel_plan as CancelPlan | undefined;
      if (!plan || x.kind !== "cancel" || !["signing","submitted","unknown"].includes(x.status)) throw new Error("cancellation is no longer unresolved");
      const t = await c.query("SELECT * FROM wallet_operations WHERE user_id=$1 AND id=$2 FOR UPDATE", [userId, plan.targetId]);
      if (!t.rows[0] || t.rows[0].network !== x.network || t.rows[0].address.toLowerCase() !== x.address.toLowerCase() || t.rows[0].user_op_hash !== plan.targetHash || t.rows[0].operation_proof?.nonce !== plan.targetNonce) throw new Error("cancellation target proof mismatch");
      await c.query("UPDATE wallet_operations SET status=$3,transaction_hash=COALESCE($4,transaction_hash),error=$5,updated_at=now() WHERE user_id=$1 AND id=$2 AND status IN ('signing','submitted','unknown','confirmed','failed')", [userId, plan.targetId, targetState, targetTx, targetState === "cancelled" ? "Nonce invalidation verified in a finalized block; original operation was not included before cancellation." : targetState === "failed" ? "Original UserOperation reverted before cancellation." : null]);
      await c.query("UPDATE wallet_operations SET status='confirmed',transaction_hash=$3,error=NULL,updated_at=now() WHERE user_id=$1 AND id=$2", [userId, id, txHash]);
      // Other versions of this cancellation shared its nonce, so none can ever be included.
      if (x.operation_proof?.nonce) await c.query("UPDATE wallet_operations SET status='cancelled',error='Replaced: another version of this cancellation with the same nonce was included.',updated_at=now() WHERE user_id=$1 AND kind='cancel' AND id<>$2 AND cancel_plan->>'targetId'=$3 AND operation_proof->>'nonce'=$4 AND status IN ('reserved','signing','submitted','unknown')", [userId, id, plan.targetId, x.operation_proof.nonce]);
      await c.query("COMMIT");
    } catch (e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
  }
  async beforeSigning(id: string, userOpHash: Hex, prepared?: PreparedOperation) {
    let proof: OperationProof | null = null, sealed: string | null = null;
    if (prepared) {
      const row = await this.pool.query("SELECT user_id,network,address FROM wallet_operations WHERE id=$1", [id]);
      if (!row.rows[0]) throw new Error("operation not found for this user");
      proof = validateOperation(prepared, row.rows[0].network, row.rows[0].address, userOpHash);
      sealed = sealOperation(prepared, this.operationKey, id);
    }
    const r = await this.pool.query(`UPDATE wallet_operations SET status='signing',user_op_hash=$2,operation_proof=$3,operation_ciphertext=$4,updated_at=now() WHERE id=$1 AND (status='reserved' OR (status='signing' AND user_op_hash IS NULL)) AND expires_at>now() RETURNING id`, [id, userOpHash, proof ? JSON.stringify(proof) : null, sealed]);
    if (!r.rowCount) throw new Error("operation is no longer available for signing");
  }
  async preparedOperation(userId: string, id: string): Promise<PreparedOperation | null> {
    const r = await this.pool.query("SELECT * FROM wallet_operations WHERE user_id=$1 AND id=$2", [userId, id]);
    const x = r.rows[0];
    if (!x?.operation_ciphertext) return null;
    const p = openOperation(x.operation_ciphertext, this.operationKey, id);
    validateOperation(p, x.network, x.address, x.user_op_hash);
    return p;
  }
  async permitExpiry(userId: string, id: string): Promise<bigint | null> {
    const r = await this.pool.query("SELECT kind,execution_context FROM wallet_operations WHERE user_id=$1 AND id=$2", [userId, id]);
    const x = r.rows[0];
    if (!x) throw new Error("operation not found for this user");
    if (x.kind !== "swap") return null;
    if (!x.execution_context) throw new Error("swap signing context is missing");
    const permit = x.execution_context.permit2;
    if (!permit) return null;
    const deadline = permit.eip712?.message?.deadline;
    if (!/^\d+$/.test(String(deadline))) throw new Error("swap Permit2 deadline is unavailable");
    return BigInt(deadline);
  }
  async beforeSwapSigning(id: string, context: unknown) {
    const r = await this.pool.query(`UPDATE wallet_operations SET status='signing',execution_context=$2,updated_at=now() WHERE id=$1 AND status='reserved' AND kind='swap' AND expires_at>now() RETURNING id`, [id, JSON.stringify(context)]);
    if (!r.rowCount) throw new Error("operation is no longer available for signing");
  }
  // Rows that provably hold no owner-signed UserOperation: beforeSigning persists
  // the hash before any signature exists, so no hash means no UserOperation was
  // signed. A swap may still have signed Permit2; its deadline is returned so the
  // caller can wait for expiry. Callers must hold Store.withPaymentLock(userId):
  // every execution path reserves and signs under it, so nothing is in flight.
  async interruptedOperations(userId: string, network: WalletNetwork, address: Address) {
    const r = await this.pool.query(`SELECT id,kind,status,execution_context FROM wallet_operations WHERE user_id=$1 AND network=$2 AND lower(address)=lower($3) AND user_op_hash IS NULL AND (status='reserved' OR (kind='swap' AND status IN ('signing','unknown')))`, [userId, network, address]);
    return r.rows.map(x => ({ id: x.id as string, status: x.status as OperationState, permitDeadline: x.status === "reserved" ? null : permitDeadline(x.execution_context) }));
  }
  async failInterrupted(userId: string, id: string, reason: string) {
    await this.pool.query(`UPDATE wallet_operations SET status='failed',error=$3,updated_at=now() WHERE user_id=$1 AND id=$2 AND user_op_hash IS NULL AND (status='reserved' OR (kind='swap' AND status IN ('signing','unknown')))`, [userId, id, reason]);
  }
  async finish(id: string, status: OperationState, hash: Hex | null = null, error: string | null = null) {
    await this.pool.query(`UPDATE wallet_operations SET status=$2,transaction_hash=COALESCE($3,transaction_hash),error=$4,updated_at=now() WHERE id=$1 AND status IN ('reserved','signing','submitted','unknown')`, [id, status, hash, error]);
  }
}
// undefined: signing context missing, so nothing can be proven (fail closed).
// null: the quote needed no Permit2 (native ETH input), so nothing was signed.
function permitDeadline(context: any): bigint | null | undefined {
  if (!context || typeof context !== "object") return undefined;
  if (context.permit2 === undefined || context.permit2 === null) return null;
  const deadline = context.permit2?.eip712?.message?.deadline;
  return /^\d+$/.test(String(deadline)) ? BigInt(deadline) : undefined;
}
function mapOperation(x: Record<string, any>): WalletOperation {
  return { id: x.id, userId: x.user_id, network: x.network, address: x.address, calls: x.calls, descriptions: x.descriptions, fingerprint: x.fingerprint, simulation: x.simulation, expiresAt: new Date(x.expires_at), status: x.status, userOpHash: x.user_op_hash ?? null, transactionHash: x.transaction_hash ?? null, error: x.error ?? null, cancelPlan: x.cancel_plan ?? null, proof: x.operation_proof ?? null, kind: x.kind ?? "calls", swapPlan: x.swap_plan ?? null };
}
