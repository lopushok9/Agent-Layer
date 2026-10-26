import assert from "node:assert/strict";
import test from "node:test";
import { TransactionService } from "../src/transactions.js";
import { transactionFingerprint } from "../src/transaction-builder.js";
import type { WalletOperation } from "../src/wallet-store.js";

const address = "0x1111111111111111111111111111111111111111";
const target = "0x2222222222222222222222222222222222222222";
const hash = `0x${"a".repeat(64)}` as const;
function harness() {
  const calls = [{ to: target, value: "0", data: "0x" }] as const;
  const p: WalletOperation = { id: "id", userId: "alice", network: "base", address, calls: [...calls], descriptions: [], fingerprint: transactionFingerprint("base", address, [...calls]), simulation: { asset_changes: [] }, expiresAt: new Date(Date.now() + 600_000), status: "prepared", userOpHash: null, transactionHash: null, error: null };
  let signed = 0; let mode: "ok" | "timeout" | "pre-sign-failure" = "ok"; let assetChanges: unknown[] = [];
  const store = {
    operation: async (user: string) => user === "alice" ? p : null,
    reserve: async (user: string) => { if (user !== "alice") throw new Error("not found"); if (p.status !== "prepared") throw new Error("consumed"); p.status = "reserved"; return p; },
    beforeSigning: async (_id: string, h: any) => { p.userOpHash = h; p.status = "signing"; },
    finish: async (_id: string, state: any, tx: any = null) => { p.status = state; p.transactionHash = tx; },
  };
  const wallets = {
    account: async () => ({ address, owners: [{ address: target }] }),
    simulate: async () => ({ asset_changes: assetChanges }),
    send: async (_user: any, _network: any, _calls: any, _id: any, before: any) => {
      if (mode === "pre-sign-failure") throw new Error("prepare failed");
      await before(hash); signed++;
      if (mode === "timeout") throw new Error("lost response");
      return { userOpHash: hash };
    },
    operation: async () => { throw new Error("provider offline"); },
  };
  const service = new TransactionService(wallets as any, store as any, { withPaymentLock: async (_user, fn) => fn() }, 600);
  return { p, service, signed: () => signed, mode: (m: typeof mode) => { mode = m; }, changes: () => { assetChanges = ["changed"]; } };
}
test("successful preview executes once, another user cannot execute or read it", async () => {
  const h = harness();
  await assert.rejects(h.service.execute("bob", "id", "test"), /not found/);
  await assert.rejects(h.service.status("bob", "id"), /not found/);
  assert.equal((await h.service.execute("alice", "id", "test")).status, "submitted");
  assert.equal(h.p.userOpHash, hash); assert.equal(h.signed(), 1);
  await assert.rejects(h.service.execute("alice", "id", "again"), /consumed/);
});
test("lost response after signing stays unknown and polling never signs again", async () => {
  const h = harness(); h.mode("timeout");
  assert.equal((await h.service.execute("alice", "id", "test")).status, "unknown");
  assert.equal((await h.service.status("alice", "id")).status, "unknown");
  await assert.rejects(h.service.execute("alice", "id", "retry"), /consumed/);
  assert.equal(h.signed(), 1);
});
test("tampered plan and changed simulation fail before owner signing", async () => {
  const h = harness(); h.p.calls[0]!.value = "123";
  await assert.rejects(h.service.execute("alice", "id", "test"), /no longer matches/);
  assert.equal(h.signed(), 0);
  const changed = harness(); changed.changes();
  await assert.rejects(changed.service.execute("alice", "id", "test"), /differ from preview/);
  assert.equal(changed.signed(), 0);
});
