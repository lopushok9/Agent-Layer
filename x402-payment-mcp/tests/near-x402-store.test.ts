import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import test from "node:test";
import { Store } from "../src/store.js";
import { NearX402Store } from "../src/near/x402-store.js";
import { NearStore } from "../src/near/store.js";
import { paymentWorld } from "./near-x402-fakes.js";

const dbUrl = process.env.TEST_DATABASE_URL;
const user = (db: Store) => db.upsertIdentity("github", `near-x402-${randomUUID()}`, null, null);
async function plan() {
  const w = paymentWorld();
  const p = await w.service.preview("u", { url: "https://api.example.com/data", headers: { authorization: "Bearer ENCRYPT-ME" }, body: { private_prompt: "SECRET-PROMPT" } });
  return w.rows.get(p.preview_id)!.plan;
}

test("Postgres NEAR x402: encrypted payload is bound to user/id, migrations replay safely and the operation kind is accepted", { skip: !dbUrl }, async () => {
  const db = new Store(dbUrl!);
  try {
    await db.migrate(); await db.migrate();
    const key = randomBytes(32).toString("base64"), store = new NearX402Store(db.pool, key);
    const u = await user(db), other = await user(db), p = await plan();
    const row = await store.create(u, "1000", p, 600);
    assert.deepEqual((await store.get(u, row.id))!.plan, p);
    assert.equal(await store.get(other, row.id), null);
    const raw = (await db.pool.query("SELECT payload FROM near_x402_payments WHERE id=$1", [row.id])).rows[0].payload;
    assert.doesNotMatch(raw, /ENCRYPT-ME|SECRET-PROMPT|private_prompt/);
    const second = await store.create(other, "1000", p, 600);
    await db.pool.query("UPDATE near_x402_payments SET payload=$2 WHERE id=$1", [second.id, raw]);
    await assert.rejects(store.get(other, second.id), /authenticate|Unsupported state/);
    const near = new NearStore(db.pool);
    const operation = await near.createOperation({ userId: u, network: "mainnet", accountId: p.accountId, publicKey: p.publicKey, kind: "x402_authorization", receiverId: "v1.signer", actions: [], descriptions: [], plan: { digest: "test" }, fingerprint: "f" }, 600, row.id);
    assert.equal(operation.id, row.id); assert.equal(operation.kind, "x402_authorization");
    await assert.rejects(new NearX402Store(db.pool, randomBytes(32).toString("base64")).get(u, row.id));
  } finally { await db.close(); }
});

test("Postgres NEAR x402: reservation is one-use, expires, isolates users and blocks another unresolved purchase", { skip: !dbUrl }, async () => {
  const db = new Store(dbUrl!);
  try {
    await db.migrate();
    const store = new NearX402Store(db.pool, randomBytes(32).toString("base64")), u = await user(db), other = await user(db), p = await plan();
    const one = await store.create(u, "1000", p, 600), two = await store.create(u, "1000", p, 600);
    await assert.rejects(store.reserve(other, one.id, "foreign purchase", null), /not found/);
    const results = await Promise.allSettled([store.reserve(u, one.id, "purchase once", null), store.reserve(u, one.id, "purchase twice", null)]);
    assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
    await assert.rejects(store.reserve(u, two.id, "next purchase", null), /unresolved/);
    await store.update(u, one.id, "unknown", p);
    await assert.rejects(store.reserve(u, two.id, "next purchase", null), /unresolved/);
    await store.update(u, one.id, "settled", p);
    await db.pool.query("UPDATE near_x402_payments SET expires_at=now()-interval '1 second' WHERE id=$1", [two.id]);
    await assert.rejects(store.reserve(u, two.id, "expired purchase", null), /expired/);
    assert.equal((await store.get(u, two.id))!.status, "prepared", "failed reservation is rolled back");
  } finally { await db.close(); }
});

test("Postgres NEAR x402: both wallet backends enforce the combined daily budget including unknown authorizations", { skip: !dbUrl }, async () => {
  const db = new Store(dbUrl!);
  try {
    await db.migrate();
    const store = new NearX402Store(db.pool, randomBytes(32).toString("base64")), u = await user(db), p = await plan();
    const row = await store.create(u, "1000", p, 600);
    await store.reserve(u, row.id, "NEAR payment", 1500n);
    await store.update(u, row.id, "unknown", p);
    const legacy = await db.createPreview({ userId: u, payerAddress: "0x1111111111111111111111111111111111111111", method: "GET", url: "https://api.example.com", headers: null, body: null, textBody: null, paymentRequired: null, fingerprint: "legacy", scheme: "exact", amount: "1000", payTo: "0x2222222222222222222222222222222222222222" }, 600);
    await assert.rejects(db.reservePayment(u, legacy.id, 1500n, "CDP purchase"), /daily spend limit/);
    await store.update(u, row.id, "expired", p);
    const saved = await db.reservePayment(u, legacy.id, 1500n, "CDP purchase");
    assert.ok(saved.paymentId);
    const next = await store.create(u, "1000", p, 600);
    await assert.rejects(store.reserve(u, next.id, "NEAR purchase", 1500n), /daily spend limit/);
    assert.equal((await store.get(u, next.id))!.status, "prepared");
  } finally { await db.close(); }
});

test("Postgres NEAR x402: concurrent reservations across backends cannot exceed the combined budget", { skip: !dbUrl }, async () => {
  const db = new Store(dbUrl!);
  try {
    await db.migrate();
    const store = new NearX402Store(db.pool, randomBytes(32).toString("base64")), u = await user(db), p = await plan();
    const near = await store.create(u, "1000", p, 600);
    const legacy = await db.createPreview({ userId: u, payerAddress: p.payer, method: "GET", url: p.url, headers: null, body: null, textBody: null, paymentRequired: null, fingerprint: "legacy", scheme: "exact", amount: "1000", payTo: p.terms.payTo }, 600);
    const results = await Promise.allSettled([
      store.reserve(u, near.id, "NEAR payment", 1500n),
      db.reservePayment(u, legacy.id, 1500n, "CDP payment"),
    ]);
    assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
    const failure = results.find(r => r.status === "rejected") as PromiseRejectedResult;
    assert.match(String(failure.reason), /daily spend limit/);
  } finally { await db.close(); }
});
