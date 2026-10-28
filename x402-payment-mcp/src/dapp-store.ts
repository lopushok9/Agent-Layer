import { randomUUID } from "node:crypto";
import type { Pool } from "pg";
import type { Address } from "viem";
import type { WalletNetwork } from "./transaction-builder.js";

export type DappApp = { name: string; url: string; description?: string; icons?: string[] };
export type DappVerification = { validation: "VALID" | "INVALID" | "UNKNOWN"; origin?: string; is_scam?: boolean };
export type DappProposal = { id: string; userId: string; pairingTopic: string; params: Record<string, any>; verification: DappVerification; expiresAt: Date; status: "pending" | "approved" | "rejected" };
export type DappSession = { topic: string; userId: string; address: Address; app: DappApp; verification: DappVerification; expiresAt: Date; endedAt: Date | null };
export type DappRequestStatus = "pending" | "prepared" | "submitted" | "responded" | "rejected" | "expired";
export type DappRequest = { id: string; userId: string; topic: string; rpcId: string; method: string; network: WalletNetwork; params: unknown; status: DappRequestStatus; operationId: string | null; signatureId: string | null; expiresAt: Date | null; error: string | null; createdAt: Date };

export class DappStore {
  constructor(private pool: Pool) {}
  async saveProposal(p: Omit<DappProposal, "status">) {
    await this.pool.query(`INSERT INTO dapp_proposals(id,user_id,pairing_topic,params,verification,expires_at) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(id) DO NOTHING`, [p.id, p.userId, p.pairingTopic, JSON.stringify(p.params), JSON.stringify(p.verification), p.expiresAt]);
  }
  async proposal(userId: string, id: string): Promise<DappProposal | null> {
    const r = await this.pool.query("SELECT * FROM dapp_proposals WHERE user_id=$1 AND id=$2", [userId, id]);
    const x = r.rows[0];
    return x ? { id: x.id, userId: x.user_id, pairingTopic: x.pairing_topic, params: x.params, verification: x.verification, expiresAt: x.expires_at, status: x.status } : null;
  }
  // Single use: only one approval or rejection can move a proposal out of pending.
  async settleProposal(userId: string, id: string, status: "approved" | "rejected") {
    const r = await this.pool.query("UPDATE dapp_proposals SET status=$3 WHERE user_id=$1 AND id=$2 AND status='pending' RETURNING id", [userId, id, status]);
    return Boolean(r.rowCount);
  }
  async saveSession(s: Omit<DappSession, "endedAt">) {
    await this.pool.query(`INSERT INTO dapp_sessions(topic,user_id,address,app,verification,expires_at) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(topic) DO NOTHING`, [s.topic, s.userId, s.address, JSON.stringify(s.app), JSON.stringify(s.verification), s.expiresAt]);
  }
  async session(topic: string): Promise<DappSession | null> {
    const r = await this.pool.query("SELECT * FROM dapp_sessions WHERE topic=$1", [topic]);
    return r.rows[0] ? mapSession(r.rows[0]) : null;
  }
  async sessions(userId: string): Promise<DappSession[]> {
    const r = await this.pool.query("SELECT * FROM dapp_sessions WHERE user_id=$1 AND ended_at IS NULL AND expires_at>now() ORDER BY created_at DESC", [userId]);
    return r.rows.map(mapSession);
  }
  async endSession(topic: string) {
    await this.pool.query("UPDATE dapp_sessions SET ended_at=now() WHERE topic=$1 AND ended_at IS NULL", [topic]);
    await this.pool.query("UPDATE dapp_requests SET status='expired',error='session ended',updated_at=now() WHERE session_topic=$1 AND status IN ('pending','prepared')", [topic]);
  }
  // The relay can redeliver a request; (session, JSON-RPC id) makes it one row.
  async saveRequest(r: Omit<DappRequest, "id" | "status" | "operationId" | "signatureId" | "error" | "createdAt">): Promise<DappRequest | null> {
    const id = randomUUID();
    const x = await this.pool.query(`INSERT INTO dapp_requests(id,user_id,session_topic,rpc_id,method,network,params,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(session_topic,rpc_id) DO NOTHING RETURNING *`, [id, r.userId, r.topic, r.rpcId, r.method, r.network, JSON.stringify(r.params), r.expiresAt]);
    return x.rows[0] ? mapRequest(x.rows[0]) : null;
  }
  async request(userId: string, id: string): Promise<DappRequest | null> {
    const r = await this.pool.query("SELECT * FROM dapp_requests WHERE user_id=$1 AND id=$2", [userId, id]);
    return r.rows[0] ? mapRequest(r.rows[0]) : null;
  }
  async requestByOperation(userId: string, operationId: string): Promise<DappRequest | null> {
    const r = await this.pool.query("SELECT * FROM dapp_requests WHERE user_id=$1 AND operation_id=$2", [userId, operationId]);
    return r.rows[0] ? mapRequest(r.rows[0]) : null;
  }
  async openRequests(userId: string): Promise<DappRequest[]> {
    await this.pool.query("UPDATE dapp_requests SET status='expired',updated_at=now() WHERE user_id=$1 AND status IN ('pending','prepared') AND expires_at<=now()", [userId]);
    const r = await this.pool.query("SELECT * FROM dapp_requests WHERE user_id=$1 AND status IN ('pending','prepared','submitted') ORDER BY created_at", [userId]);
    return r.rows.map(mapRequest);
  }
  async attachPreview(userId: string, id: string, link: { operationId: string } | { signatureId: string }) {
    const r = await this.pool.query(`UPDATE dapp_requests SET status='prepared',operation_id=$3,signature_id=$4,error=NULL,updated_at=now() WHERE user_id=$1 AND id=$2 AND status IN ('pending','prepared') RETURNING id`, [userId, id, "operationId" in link ? link.operationId : null, "signatureId" in link ? link.signatureId : null]);
    if (!r.rowCount) throw new Error("app request is no longer open");
  }
  // from: the states this transition may leave; a lost race changes nothing.
  async setRequestStatus(id: string, status: DappRequestStatus, from: DappRequestStatus[], error: string | null = null) {
    const r = await this.pool.query("UPDATE dapp_requests SET status=$2,error=$4,updated_at=now() WHERE id=$1 AND status=ANY($3) RETURNING id", [id, status, from, error]);
    return Boolean(r.rowCount);
  }
}

function mapSession(x: Record<string, any>): DappSession {
  return { topic: x.topic, userId: x.user_id, address: x.address, app: x.app, verification: x.verification, expiresAt: x.expires_at, endedAt: x.ended_at };
}
function mapRequest(x: Record<string, any>): DappRequest {
  return { id: x.id, userId: x.user_id, topic: x.session_topic, rpcId: x.rpc_id, method: x.method, network: x.network, params: x.params, status: x.status, operationId: x.operation_id, signatureId: x.signature_id, expiresAt: x.expires_at, error: x.error, createdAt: x.created_at };
}
