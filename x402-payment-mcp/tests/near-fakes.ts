import { randomUUID } from "node:crypto";
import type { NearAccountRecord, NearOperation, NearStore } from "../src/near/store.js";

// Same contract as NearStore.reserve/markSigning, in memory.
export function memoryStore() {
  const accounts = new Map<string, NearAccountRecord>(), ops = new Map<string, NearOperation & { consumed?: boolean }>();
  const store = {
    async account(u: string, n: string) { return accounts.get(`${u}:${n}`) ?? null; },
    async saveAccount(a: NearAccountRecord) { const k = `${a.userId}:${a.network}`; if (!accounts.has(k)) accounts.set(k, a); return accounts.get(k)!; },
    async createOperation(p: any, ttl: number) { const op = { ...jsonb(p), id: randomUUID(), expiresAt: new Date(Date.now() + ttl * 1000), status: "prepared", purpose: null, nonce: null, txHash: null, signedTx: null, outcome: null, result: null, error: null, createdAt: new Date() }; ops.set(op.id, op); return structuredClone(op); },
    async operation(u: string, id: string) { const o = ops.get(id); return o && o.userId === u ? structuredClone(o) : null; },
    async recent() { return [...ops.values()]; },
    async reserve(u: string, id: string, kind: string, purpose: string, parentPlanId?: string) {
      const o = ops.get(id);
      if (!o || o.userId !== u) throw new Error("operation not found for this user");
      if (o.kind !== kind) throw new Error("operation type does not match this execution tool");
      if (o.status !== "prepared" || o.consumed) throw new Error("preview already consumed; check near_operation_status, never submit it again");
      if ([...ops.values()].some(x => x.userId === u && x.id !== parentPlanId && ["reserved", "signing", "submitted", "unknown"].includes(x.status))) throw new Error("an unresolved NEAR operation exists for this account; reconcile it with near_operation_status first");
      if (parentPlanId) { const p = ops.get(parentPlanId); if (!p || p.kind !== "near_plan" || p.status !== "submitted") throw new Error("operation is not a step of a running plan"); }
      if (o.expiresAt < new Date()) throw new Error("preview expired; prepare a new operation");
      Object.assign(o, { status: "reserved", consumed: true, purpose }); return structuredClone(o);
    },
    async markSigning(u: string, id: string, nonce: string, txHash: string, signedTx: string) { const o = ops.get(id)!; if (o.status !== "reserved") throw new Error("operation is no longer available for signing"); Object.assign(o, { status: "signing", nonce, txHash, signedTx }); },
    async update(u: string, id: string, p: any) { const o = ops.get(id)!; Object.assign(o, { status: p.status, ...(p.outcome !== undefined ? { outcome: p.outcome } : {}), ...(p.result !== undefined ? { result: p.result } : {}), error: p.error ?? null }); },
  };
  return { store: store as unknown as NearStore, ops };
}

// Postgres JSONB returns object keys sorted by length, then bytewise.
function jsonb(v: any): any {
  if (Array.isArray(v)) return v.map(jsonb);
  if (v && typeof v === "object" && !(v instanceof Date)) {
    return Object.fromEntries(Object.keys(v).sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0)).map(k => [k, jsonb(v[k])]));
  }
  return v;
}
