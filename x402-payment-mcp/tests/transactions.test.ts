import assert from "node:assert/strict";
import test from "node:test";
import { TransactionService } from "../src/transactions.js";
import { transactionFingerprint } from "../src/transaction-builder.js";
import { encodeAbiParameters, encodeEventTopics, parseAbi } from "viem";
import { entryPoint06Address } from "viem/account-abstraction";
import type { WalletOperation } from "../src/wallet-store.js";

const address = "0x1111111111111111111111111111111111111111";
const target = "0x2222222222222222222222222222222222222222";
const hash = `0x${"a".repeat(64)}` as const;
function harness() {
  const calls = [{ to: target, value: "0", data: "0x" }] as const;
  const p: WalletOperation = { id: "id", userId: "alice", network: "base", address, calls: [...calls], descriptions: [], fingerprint: transactionFingerprint("base", address, [...calls]), simulation: { asset_changes: [], network_fee: { approved_max_prefund_wei: "1000" } }, expiresAt: new Date(Date.now() + 600_000), status: "prepared", userOpHash: null, transactionHash: null, error: null };
  const ceilings: bigint[] = []; let signed = 0; let mode: "ok" | "timeout" | "pre-sign-failure" = "ok"; let assetChanges: unknown[] = [];
  const store = {
    operation: async (user: string) => user === "alice" ? p : null,
    reserve: async (user: string) => { if (user !== "alice") throw new Error("not found"); if (p.status !== "prepared") throw new Error("consumed"); p.status = "reserved"; return p; },
    beforeSigning: async (_id: string, h: any) => { p.userOpHash = h; p.status = "signing"; },
    finish: async (_id: string, state: any, tx: any = null) => { p.status = state; p.transactionHash = tx; },
    interruptedOperations: async () => [],
    failInterrupted: async () => {},
  };
  const wallets = {
    account: async () => ({ address, owners: [{ address: target }] }),
    simulate: async () => ({ asset_changes: assetChanges }),
    send: async (_user: any, _network: any, _calls: any, _id: any, before: any, options: any) => {
      ceilings.push(options.maxPrefundWei);
      if (mode === "pre-sign-failure") throw new Error("prepare failed");
      await before(hash); signed++;
      if (mode === "timeout") throw new Error("lost response");
      return { userOpHash: hash };
    },
    operation: async () => { throw new Error("provider offline"); },
  };
  const service = new TransactionService(wallets as any, store as any, { withPaymentLock: async (_user, fn) => fn() }, 600);
  return { p, service, wallets, ceilings, signed: () => signed, mode: (m: typeof mode) => { mode = m; }, changes: () => { assetChanges = ["changed"]; } };
}
test("successful preview executes once, another user cannot execute or read it", async () => {
  const h = harness();
  await assert.rejects(h.service.execute("bob", "id", "test"), /not found/);
  await assert.rejects(h.service.status("bob", "id"), /not found/);
  assert.equal((await h.service.execute("alice", "id", "test")).status, "submitted");
  assert.equal(h.p.userOpHash, hash); assert.equal(h.signed(), 1);
  await assert.rejects(h.service.execute("alice", "id", "again"), /consumed/);
});

test("outer transaction success cannot confirm a missing or reverted UserOperation event", async () => {
  const h = harness(); await h.service.execute("alice", "id", "test");
  const txHash = `0x${"b".repeat(64)}` as const;
  (h.wallets as any).operation = async () => ({ network: "base", status: "complete", transactionHash: txHash });
  let logs: any[] = [];
  (h.wallets as any).rpc = () => ({ getTransactionReceipt: async () => ({ status: "success", logs }) });
  assert.equal((await h.service.status("alice", "id")).status, "submitted", "missing event is not confirmation");
  const abi = parseAbi(["event UserOperationEvent(bytes32 indexed userOpHash, address indexed sender, address indexed paymaster, uint256 nonce, bool success, uint256 actualGasCost, uint256 actualGasUsed)"]);
  const event = (success: boolean) => ({ address: entryPoint06Address, topics: encodeEventTopics({ abi, eventName: "UserOperationEvent", args: { userOpHash: hash, sender: address, paymaster: target } }), data: encodeAbiParameters([{ type: "uint256" }, { type: "bool" }, { type: "uint256" }, { type: "uint256" }], [0n, success, 100n, 100n]) });
  logs = [{ ...event(true), address: target }];
  assert.equal((await h.service.status("alice", "id")).status, "submitted", "a forged event from another contract must be ignored");
  logs = [event(false)];
  assert.equal((await h.service.status("alice", "id")).status, "failed");
  assert.equal(h.signed(), 1);
});
test("lost response after signing stays unknown and polling never signs again", async () => {
  const h = harness(); h.mode("timeout");
  assert.equal((await h.service.execute("alice", "id", "test")).status, "unknown");
  assert.equal((await h.service.status("alice", "id")).status, "unknown");
  await assert.rejects(h.service.execute("alice", "id", "retry"), /consumed/);
  assert.equal(h.signed(), 1);
});
test("an expired prepared operation still marked signed by CDP remains unresolved and cannot be retried", async () => {
  const h = harness(); h.mode("timeout");
  await h.service.execute("alice", "id", "test");
  (h.wallets as any).operation = async () => ({ network: "base", status: "signed", expiresAt: "2000-01-01T00:00:00Z" });
  const result = await h.service.status("alice", "id");
  assert.equal(result.status, "unknown");
  assert.deepEqual(result.provider_state, { status: "signed", prepared_expires_at: "2000-01-01T00:00:00Z" });
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


test("legacy provider failure without an onchain event cannot unlock a signed operation", async () => {
  const h = harness(); h.mode("timeout"); await h.service.execute("alice", "id", "test");
  (h.wallets as any).operation = async () => ({ network: "base", status: "failed" });
  assert.equal((await h.service.status("alice", "id")).status, "unknown");
  assert.equal(h.signed(), 1);
});

test("execution passes the approved network fee ceiling and refuses previews without one", async () => {
  const h = harness();
  await h.service.execute("alice", "id", "test");
  assert.deepEqual(h.ceilings, [1000n]);
  const legacy = harness(); delete (legacy.p.simulation as any).network_fee;
  await assert.rejects(legacy.service.execute("alice", "id", "test"), /no approved network fee maximum/);
  assert.equal(legacy.signed(), 0); assert.equal(legacy.p.status, "failed");
});
test("preview records the estimated prefund and a doubled approval ceiling", async () => {
  const h = harness();
  let created: any;
  (h.wallets as any).estimateNetworkFee = async () => 400n;
  (h.wallets as any).simulate = async () => ({ asset_changes: [] });
  (h.service as any).store.createOperation = async (p: any) => { created = p; return { ...h.p, ...p, id: "new", status: "prepared" }; };
  await h.service.prepare("alice", { network: "base", calls: [{ to: "0x3333333333333333333333333333333333333333", value: "1" }] });
  assert.equal(created.simulation.network_fee.estimated_max_prefund_wei, "400");
  assert.equal(created.simulation.network_fee.approved_max_prefund_wei, "800");
});

test("a route preview's stored output floor lets execution accept a lower fresh output, never one below the floor", async () => {
  const out = "0x4444444444444444444444444444444444444444";
  const change = (diff: string) => [{ token: { address: out }, value: { pre: "0", post: diff, diff } }];
  for (const [fresh, ok] of [["996", true], ["994", false]] as const) {
    const h = harness();
    h.p.simulation = { ...h.p.simulation, asset_changes: change("1000"), asset_floors: { [out]: "995" } };
    (h.wallets as any).simulate = async () => ({ asset_changes: change(fresh) });
    if (ok) assert.equal((await h.service.execute("alice", "id", "route")).status, "submitted");
    else await assert.rejects(h.service.execute("alice", "id", "route"), /simulated asset changes differ/);
  }
});
