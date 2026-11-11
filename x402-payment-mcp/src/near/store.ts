import { randomUUID } from "node:crypto";
import type { Pool } from "pg";
import type { NearSignerKind } from "./keys.js";
import type { NormalizedNearAction } from "./transaction.js";

export type NearNetwork = "mainnet" | "testnet";
export type NearAccountRecord = { userId: string; network: NearNetwork; accountId: string; publicKey: string; signerKind: NearSignerKind; cdpAccountName: string | null; sealedKey: string | null };
export type NearOperationState = "prepared" | "reserved" | "signing" | "submitted" | "confirmed" | "failed" | "unknown";
export type NearOperationKind = "near_tx" | "chain_signature" | "intents_swap" | "intents_trade";
export type NearOperation = {
  id: string; userId: string; network: NearNetwork; accountId: string; publicKey: string; kind: NearOperationKind;
  receiverId: string; actions: NormalizedNearAction[]; descriptions: unknown[]; plan: Record<string, unknown> | null;
  fingerprint: string; expiresAt: Date; status: NearOperationState; purpose: string | null;
  nonce: string | null; txHash: string | null; signedTx: string | null; outcome: unknown; result: unknown; error: string | null; createdAt: Date;
};
export const UNRESOLVED: NearOperationState[] = ["reserved", "signing", "submitted", "unknown"];

export class NearStore {
  constructor(readonly pool: Pool) {}

  async account(userId: string, network: NearNetwork): Promise<NearAccountRecord | null> {
    const r = await this.pool.query("SELECT * FROM near_accounts WHERE user_id=$1 AND network=$2", [userId, network]);
    return r.rows[0] ? mapAccount(r.rows[0]) : null;
  }

  // First writer wins; a concurrent creation for the same user must end with
  // the stored record, never with two keys for one user.
  async saveAccount(a: NearAccountRecord): Promise<NearAccountRecord> {
    await this.pool.query(`INSERT INTO near_accounts(user_id,network,account_id,public_key,signer_kind,cdp_account_name,sealed_key) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(user_id,network) DO NOTHING`, [a.userId, a.network, a.accountId, a.publicKey, a.signerKind, a.cdpAccountName, a.sealedKey]);
    const stored = await this.account(a.userId, a.network);
    if (!stored) throw new Error("NEAR account registry write failed");
    return stored;
  }

  async createOperation(p: Pick<NearOperation, "userId" | "network" | "accountId" | "publicKey" | "kind" | "receiverId" | "actions" | "descriptions" | "plan" | "fingerprint">, ttlSeconds: number): Promise<NearOperation> {
    const id = randomUUID();
    await this.pool.query(`INSERT INTO near_operations(id,user_id,network,account_id,public_key,kind,receiver_id,actions,descriptions,plan,fingerprint,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,now()+($12*interval '1 second'))`,
      [id, p.userId, p.network, p.accountId, p.publicKey, p.kind, p.receiverId, JSON.stringify(p.actions), JSON.stringify(p.descriptions), p.plan ? JSON.stringify(p.plan) : null, p.fingerprint, ttlSeconds]);
    return (await this.operation(p.userId, id))!;
  }

  async operation(userId: string, id: string): Promise<NearOperation | null> {
    const r = await this.pool.query("SELECT * FROM near_operations WHERE user_id=$1 AND id=$2", [userId, id]);
    return r.rows[0] ? mapOperation(r.rows[0]) : null;
  }

  async recent(userId: string, limit: number): Promise<NearOperation[]> {
    const r = await this.pool.query("SELECT * FROM near_operations WHERE user_id=$1 AND status<>'prepared' ORDER BY created_at DESC LIMIT $2", [userId, limit]);
    return r.rows.map(mapOperation);
  }

  // Consumes a preview exactly once. Execution is serialized per account: an
  // unresolved operation blocks the next one, so nonces never race and an
  // unknown outcome is reconciled before anything else is signed.
  async reserve(userId: string, id: string, kind: NearOperationKind, purpose: string): Promise<NearOperation> {
    const c = await this.pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", [`near-operation:${userId}`]);
      const r = await c.query("SELECT * FROM near_operations WHERE id=$1 AND user_id=$2 FOR UPDATE", [id, userId]);
      const x = r.rows[0];
      if (!x) throw new Error("operation not found for this user");
      if (x.kind !== kind) throw new Error("operation type does not match this execution tool");
      if (x.status !== "prepared" || x.consumed_at) throw new Error("preview already consumed; check near_operation_status, never submit it again");
      const pending = await c.query("SELECT id FROM near_operations WHERE user_id=$1 AND network=$2 AND account_id=$3 AND status = ANY($4) LIMIT 1", [userId, x.network, x.account_id, UNRESOLVED]);
      if (pending.rowCount) throw new Error("an unresolved NEAR operation exists for this account; reconcile it with near_operation_status first");
      const saved = await c.query("UPDATE near_operations SET status='reserved',purpose=$3,consumed_at=now(),updated_at=now() WHERE id=$1 AND user_id=$2 AND expires_at>now() RETURNING *", [id, userId, purpose]);
      if (!saved.rows[0]) throw new Error("preview expired; prepare a new operation");
      await c.query("COMMIT");
      return mapOperation(saved.rows[0]);
    } catch (e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
  }

  // Written before broadcast: a crash after this point leaves a hash to
  // reconcile, never an untracked signed transaction.
  async markSigning(userId: string, id: string, nonce: string, txHash: string, signedTx: string) {
    const r = await this.pool.query("UPDATE near_operations SET status='signing',nonce=$3,tx_hash=$4,signed_tx=$5,updated_at=now() WHERE id=$1 AND user_id=$2 AND status='reserved' RETURNING id", [id, userId, nonce, txHash, signedTx]);
    if (!r.rowCount) throw new Error("operation is no longer available for signing");
  }

  async update(userId: string, id: string, p: { status: NearOperationState; outcome?: unknown; result?: unknown; error?: string | null }) {
    await this.pool.query("UPDATE near_operations SET status=$3,outcome=COALESCE($4,outcome),result=COALESCE($5,result),error=$6,updated_at=now() WHERE id=$1 AND user_id=$2", [id, userId, p.status, p.outcome === undefined ? null : JSON.stringify(p.outcome), p.result === undefined ? null : JSON.stringify(p.result), p.error ?? null]);
  }
}

function mapAccount(x: any): NearAccountRecord {
  return { userId: x.user_id, network: x.network, accountId: x.account_id, publicKey: x.public_key, signerKind: x.signer_kind, cdpAccountName: x.cdp_account_name, sealedKey: x.sealed_key };
}
function mapOperation(x: any): NearOperation {
  return { id: x.id, userId: x.user_id, network: x.network, accountId: x.account_id, publicKey: x.public_key, kind: x.kind, receiverId: x.receiver_id, actions: x.actions, descriptions: x.descriptions, plan: x.plan, fingerprint: x.fingerprint, expiresAt: new Date(x.expires_at), status: x.status, purpose: x.purpose, nonce: x.nonce, txHash: x.tx_hash, signedTx: x.signed_tx, outcome: x.outcome, result: x.result, error: x.error, createdAt: new Date(x.created_at) };
}
