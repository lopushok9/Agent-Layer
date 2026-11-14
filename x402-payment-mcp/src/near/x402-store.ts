import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from "node:crypto";
import { NearPublicError } from "./operations.js";
import type { Pool } from "pg";
import type { PaymentPlan } from "./x402.js";

export type PaymentState = "prepared" | "reserved" | "signing" | "signed" | "sending" | "settled" | "failed" | "unknown" | "expired" | "cancelled";
export type NearPayment = { id: string; userId: string; amount: string; plan: PaymentPlan; status: PaymentState; purpose: string | null; result: Record<string, unknown> | null; expiresAt: Date };
export interface NearPaymentStore {
  create(userId: string, amount: string, plan: PaymentPlan, ttl: number): Promise<NearPayment>;
  get(userId: string, id: string): Promise<NearPayment | null>;
  reserve(userId: string, id: string, purpose: string, dailyLimit: bigint | null): Promise<NearPayment>;
  update(userId: string, id: string, status: PaymentState, plan: PaymentPlan, result?: Record<string, unknown>): Promise<NearPayment>;
}

// Call reserve/update under Store.withPaymentLock. Reservation also takes the
// legacy ledger's transaction lock, so both backends share the daily budget.
export class NearX402Store implements NearPaymentStore {
  constructor(private pool: Pool, private secret: string) {
    if (Buffer.from(secret, "base64").length !== 32) throw new Error("NEAR x402 storage encryption key must be 32 bytes");
  }
  async create(userId: string, amount: string, plan: PaymentPlan, ttl: number) {
    const id = randomUUID();
    await this.pool.query("INSERT INTO near_x402_payments(id,user_id,amount,payload,expires_at) VALUES($1,$2,$3,$4,now()+($5*interval '1 second'))", [id, userId, amount, this.seal(userId, id, plan), ttl]);
    return (await this.get(userId, id))!;
  }
  async get(userId: string, id: string): Promise<NearPayment | null> {
    const r = await this.pool.query("SELECT * FROM near_x402_payments WHERE user_id=$1 AND id=$2", [userId, id]);
    return r.rows[0] ? this.map(r.rows[0]) : null;
  }
  async reserve(userId: string, id: string, purpose: string, dailyLimit: bigint | null) {
    const c = await this.pool.connect();
    try {
      await c.query("BEGIN");
      await c.query("SELECT pg_advisory_xact_lock(hashtext($1))", [userId]);
      const r = await c.query("SELECT * FROM near_x402_payments WHERE user_id=$1 AND id=$2 FOR UPDATE", [userId, id]);
      const row = r.rows[0];
      if (!row) throw new NearPublicError("payment preview not found for this user");
      if (row.status !== "prepared") throw new NearPublicError("payment preview already consumed; use x402_status, never pay again");
      const pending = await c.query("SELECT id FROM near_x402_payments WHERE user_id=$1 AND status IN ('reserved','signing','signed','sending','unknown') LIMIT 1", [userId]);
      if (pending.rowCount) throw new NearPublicError("an unresolved NEAR x402 payment exists; use x402_status before another payment");
      if (dailyLimit !== null) {
        const spent = await c.query("SELECT COALESCE(sum(amount::numeric),0)::text total FROM (SELECT amount::numeric AS amount FROM payments WHERE user_id=$1 AND created_at>now()-interval '24 hours' AND status IN ('reserved','settled','unknown') UNION ALL SELECT amount::numeric AS amount FROM near_x402_payments WHERE user_id=$1 AND reserved_at>now()-interval '24 hours' AND status IN ('reserved','signing','signed','sending','settled','unknown')) spends", [userId]);
        if (BigInt(spent.rows[0].total) + BigInt(row.amount) > dailyLimit) throw new NearPublicError("daily spend limit exceeded");
      }
      const saved = await c.query("UPDATE near_x402_payments SET status='reserved',purpose=$3,reserved_at=now(),updated_at=now() WHERE user_id=$1 AND id=$2 AND expires_at>now() RETURNING *", [userId, id, purpose]);
      if (!saved.rowCount) throw new NearPublicError("payment preview expired; prepare a new preview");
      await c.query("COMMIT");
      return this.map(saved.rows[0]);
    } catch (e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
  }
  async update(userId: string, id: string, status: PaymentState, plan: PaymentPlan, result?: Record<string, unknown>) {
    const r = await this.pool.query("UPDATE near_x402_payments SET status=$3,payload=$4,result=COALESCE($5,result),updated_at=now() WHERE user_id=$1 AND id=$2 RETURNING *", [userId, id, status, this.seal(userId, id, plan), result ? JSON.stringify(result) : null]);
    if (!r.rowCount) throw new NearPublicError("payment not found for this user");
    return this.map(r.rows[0]);
  }
  private map(r: any): NearPayment {
    return { id: r.id, userId: r.user_id, amount: r.amount, plan: this.open(r.user_id, r.id, r.payload), status: r.status, purpose: r.purpose, result: r.result, expiresAt: new Date(r.expires_at) };
  }
  private seal(userId: string, id: string, value: PaymentPlan) {
    const iv = randomBytes(12), cipher = createCipheriv("aes-256-gcm", Buffer.from(this.secret, "base64"), iv);
    cipher.setAAD(Buffer.from(`near-x402:v1:${userId}:${id}`));
    const body = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
    return ["v1", iv.toString("base64"), body.toString("base64"), cipher.getAuthTag().toString("base64")].join(".");
  }
  private open(userId: string, id: string, value: string): PaymentPlan {
    const [v, iv, body, tag] = value.split(".");
    if (v !== "v1" || !iv || !body || !tag) throw new Error("invalid encrypted NEAR x402 payment");
    const decipher = createDecipheriv("aes-256-gcm", Buffer.from(this.secret, "base64"), Buffer.from(iv, "base64"));
    decipher.setAAD(Buffer.from(`near-x402:v1:${userId}:${id}`)); decipher.setAuthTag(Buffer.from(tag, "base64"));
    return JSON.parse(Buffer.concat([decipher.update(Buffer.from(body, "base64")), decipher.final()]).toString("utf8"));
  }
}
