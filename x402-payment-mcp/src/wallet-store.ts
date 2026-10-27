import { randomUUID } from "node:crypto";
import type { Pool } from "pg";
import type { Address, Hex } from "viem";
import type { CallDescription, NormalizedCall, WalletNetwork } from "./transaction-builder.js";
import type { SwapPlan } from "./swap-plan.js";

export type SmartWalletRecord = { ownerName: string; ownerAddress: Address; accountName: string; address: Address };
export type OperationState = "prepared" | "reserved" | "signing" | "submitted" | "confirmed" | "failed" | "unknown";
export type WalletOperation = {
  id: string; userId: string; network: WalletNetwork; address: Address;
  calls: NormalizedCall[]; descriptions: CallDescription[]; fingerprint: string;
  simulation: Record<string, unknown>; expiresAt: Date; status: OperationState;
  userOpHash: Hex | null; transactionHash: Hex | null; error: string | null;
  kind?: "calls" | "swap"; swapPlan?: SwapPlan | null;
};
export class WalletStore {
  constructor(readonly pool: Pool) {}
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
    await this.pool.query(`INSERT INTO wallet_operations(id,user_id,network,address,calls,descriptions,fingerprint,simulation,expires_at,kind,swap_plan) VALUES($1,$2,$3,$4,$5,$6,$7,$8,now()+($9*interval '1 second'),$10,$11)`, [id, p.userId, p.network, p.address, JSON.stringify(p.calls), JSON.stringify(p.descriptions), p.fingerprint, JSON.stringify(p.simulation), ttl, p.kind ?? "calls", p.swapPlan ? JSON.stringify(p.swapPlan) : null]);
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
  async beforeSigning(id: string, userOpHash: Hex) {
    const r = await this.pool.query(`UPDATE wallet_operations SET status='signing',user_op_hash=$2,updated_at=now() WHERE id=$1 AND (status='reserved' OR (status='signing' AND user_op_hash IS NULL)) AND expires_at>now() RETURNING id`, [id, userOpHash]);
    if (!r.rowCount) throw new Error("operation is no longer available for signing");
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
  return { id: x.id, userId: x.user_id, network: x.network, address: x.address, calls: x.calls, descriptions: x.descriptions, fingerprint: x.fingerprint, simulation: x.simulation, expiresAt: new Date(x.expires_at), status: x.status, userOpHash: x.user_op_hash ?? null, transactionHash: x.transaction_hash ?? null, error: x.error ?? null, kind: x.kind ?? "calls", swapPlan: x.swap_plan ?? null };
}
