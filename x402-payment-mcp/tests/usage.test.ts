import assert from "node:assert/strict";
import test from "node:test";
import { randomBytes } from "node:crypto";
import express from "express";
import { Store } from "../src/store.js";
import { clientBucket, scrubDetail } from "../src/usage.js";
import { statsRouter } from "../src/stats.js";

test("error details keep their shape but lose addresses, urls, emails, ids and numbers", () => {
  assert.equal(scrubDetail("insufficient balance: 0xD09d6F783A9840E5Ca35E134912765dc11C895A1 has 588000 wei, needs 9990000000000000"), "insufficient balance: 0x… has # wei, needs #");
  assert.equal(scrubDetail("GET https://api.example.com/v1/x?key=abc failed for a@b.co, op 3f1c2b9e-1111-4222-8333-444455556666"), "GET <url> failed for <email>, op <id>");
  assert.equal(scrubDetail("x".repeat(500))!.length, 160);
  assert.equal(scrubDetail(""), null);
  assert.deepEqual([clientBucket("pat:123"), clientBucket("abc"), clientBucket(null)], ["pat", "abc", null]);
});

test("the stats endpoint is off without a token and refuses a wrong one", async () => {
  const usage = { stats: async (days: number) => ({ window_days: days }) } as any;
  const serve = async (token: string | undefined) => { const app = express(); app.use(statsRouter({ STATS_TOKEN: token }, usage)); const s = app.listen(0); await new Promise(r => s.once("listening", r)); return { base: `http://127.0.0.1:${(s.address() as any).port}`, close: () => s.close() }; };
  const off = await serve(undefined);
  try { assert.equal((await fetch(`${off.base}/v1/stats`, { headers: { authorization: "Bearer anything" } })).status, 404); } finally { off.close(); }
  const token = randomBytes(24).toString("base64url");
  const on = await serve(token);
  try {
    assert.equal((await fetch(`${on.base}/v1/stats`)).status, 401);
    assert.equal((await fetch(`${on.base}/v1/stats?token=${token}`)).status, 401, "the token is not accepted in the URL");
    assert.equal((await fetch(`${on.base}/v1/stats`, { headers: { authorization: `Bearer ${token}x` } })).status, 401);
    assert.equal((await fetch(`${on.base}/v1/stats?days=0`, { headers: { authorization: `Bearer ${token}` } })).status, 400);
    const ok = await fetch(`${on.base}/v1/stats?days=7`, { headers: { authorization: `Bearer ${token}` } });
    assert.deepEqual([ok.status, ok.headers.get("cache-control"), await ok.json()], [200, "no-store", { window_days: 7 }]);
  } finally { on.close(); }
});

// Runs the real SQL against Postgres when TEST_DATABASE_URL is set; skipped otherwise.
const url = process.env.TEST_DATABASE_URL;
test("sign-ins and tool calls are recorded and aggregated", { skip: !url }, async () => {
  const store = new Store(url!);
  try {
    await store.migrate();
    const since = new Date();
    const subject = `usage-${randomBytes(6).toString("hex")}`;
    const user = await store.upsertIdentity("github", subject, "U", null);
    assert.equal(await store.upsertIdentity("github", subject, "U", null), user);
    store.usage.record({ kind: "tool", name: "wallet_status", userId: user, clientId: "pat:9", ok: true, ms: 12.4 });
    store.usage.record({ kind: "tool", name: "transaction_prepare", userId: user, clientId: "pat:9", ok: false, ms: 80, detail: "insufficient funds for 0xD09d6F783A9840E5Ca35E134912765dc11C895A1" });
    const rows = async () => (await store.pool.query(`SELECT kind,name,client_id,ok,ms,detail FROM usage_events WHERE user_id=$1 AND at>=$2 ORDER BY id`, [user, since])).rows;
    let events: any[] = [];
    for (let i = 0; i < 50 && events.length < 4; i++) { events = await rows(); if (events.length < 4) await new Promise(r => setTimeout(r, 20)); }
    // Recording is fire-and-forget, so rows may land in any order.
    const sorted = (v: unknown[][]) => v.map(x => JSON.stringify(x)).sort();
    assert.deepEqual(sorted(events.map(e => [e.kind, e.name, e.client_id, e.ok, e.detail])), sorted([
      ["auth", "github", null, true, "new_user"],
      ["auth", "github", null, true, null],
      ["tool", "wallet_status", "pat", true, null],
      ["tool", "transaction_prepare", "pat", false, "insufficient funds for 0x…"],
    ]));
    assert.equal(events.find(e => e.name === "wallet_status").ms, 12);

    const stats = await store.usage.stats(1);
    assert.ok(stats.users.total! >= 1 && stats.users.new! >= 1);
    assert.ok(stats.active_users.dau! >= 1);
    const prepare = stats.tools.find((t: any) => t.tool === "transaction_prepare") as any;
    assert.ok(prepare.calls >= 1 && prepare.errors >= 1 && typeof prepare.p50_ms === "number");
    assert.ok(stats.top_errors.some((e: any) => e.error === "insufficient funds for 0x…"));
    assert.ok(stats.clients.some((c: any) => c.client === "personal access token"));
    assert.ok((stats.auth.find((a: any) => a.event === "github") as any).new_users >= 1);
    assert.ok(stats.funnel.called_a_tool! >= 1);
    assert.ok(!JSON.stringify(stats).includes(user), "the report has no user ids");
  } finally { await store.pool.end(); }
});
