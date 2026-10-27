import { randomUUID } from "node:crypto";
import type { Pool } from "pg";
import type { Address, Hex } from "viem";
import type { CallDescription, NormalizedCall, WalletNetwork } from "./transaction-builder.js";
import type { SwapPlan } from "./swap-plan.js";

import { sealOperation, openOperation, validateOperation, type PreparedOperation, type OperationProof } from "./user-operation.js";

export type SmartWalletRecord = { ownerName: string; ownerAddress: Address; accountName: string; address: Address };
export type CancelPlan = { targetId: string; targetHash: Hex; targetNonce: string; entryPoint: Address; fromBlock: string };
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
      const pending = await c.query(`SELECT id FROM wallet_operations WHERE user_id=$1 AND network=$2 AND status IN ('reserved','signing','submitted','unknown') LIMIT 1`, [userId, x.network]);
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
      const other = await c.query("SELECT id FROM wallet_operations WHERE user_id=$1 AND network=$2 AND status IN ('reserved','signing','submitted','unknown') AND id<>$3 LIMIT 1", [userId, x.network, plan.targetId]);
      if (other.rowCount) throw new Error("another unresolved operation prevents cancellation");
      const saved = await c.query("UPDATE wallet_operations SET status='reserved',purpose=$3,consumed_at=now(),updated_at=now() WHERE id=$1 AND user_id=$2 AND expires_at>now() RETURNING *", [id, userId, purpose]);
      if (!saved.rows[0]) throw new Error("preview expired; prepare a new operation");
      await c.query("COMMIT"); return mapOperation(saved.rows[0]);
    } catch (e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
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
  async finish(id: string, status: OperationState, hash: Hex | null = null, error: string | null = null) {
    await this.pool.query(`UPDATE wallet_operations SET status=$2,transaction_hash=COALESCE($3,transaction_hash),error=$4,updated_at=now() WHERE id=$1 AND status IN ('reserved','signing','submitted','unknown')`, [id, status, hash, error]);
  }
}
function mapOperation(x: Record<string, any>): WalletOperation {
  return { id: x.id, userId: x.user_id, network: x.network, address: x.address, calls: x.calls, descriptions: x.descriptions, fingerprint: x.fingerprint, simulation: x.simulation, expiresAt: new Date(x.expires_at), status: x.status, userOpHash: x.user_op_hash ?? null, transactionHash: x.transaction_hash ?? null, error: x.error ?? null, cancelPlan: x.cancel_plan ?? null, proof: x.operation_proof ?? null, kind: x.kind ?? "calls", swapPlan: x.swap_plan ?? null };
}
