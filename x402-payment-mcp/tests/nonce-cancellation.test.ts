import assert from "node:assert/strict";
import test from "node:test";
import { randomBytes, randomUUID } from "node:crypto";
import { encodeAbiParameters, encodeEventTopics, parseAbi } from "viem";
import { entryPoint06Address } from "viem/account-abstraction";
import { Store } from "../src/store.js";
import { WalletStore, type CancelPlan } from "../src/wallet-store.js";
import { TransactionService } from "../src/transactions.js";
import { cancellationCalls, cancellationFingerprint } from "../src/nonce-cancellation.js";
import { operationHash, validateOperation, type PreparedOperation } from "../src/user-operation.js";
const address = "0x1111111111111111111111111111111111111111";
const tx = `0x${"a".repeat(64)}` as const, blockHash = `0x${"b".repeat(64)}` as const;
function original(): PreparedOperation { return { chainId: 8453, entryPoint: entryPoint06Address, blockNumber: "10", operation: { sender: address, nonce: 7n, initCode: "0x", callData: "0xabcd", callGasLimit: 100000n, verificationGasLimit: 150000n, preVerificationGas: 50000n, maxFeePerGas: 200n, maxPriorityFeePerGas: 100n, paymasterAndData: "0x", signature: "0x" } }; }
function plan(targetId: string): CancelPlan { const p = original(); return { targetId, targetHash: operationHash(p), targetNonce: "7", entryPoint: entryPoint06Address, fromBlock: "10" }; }

test("Postgres: cancellation bypass is restricted to its proven target, single use and one concurrent attempt", { skip: !process.env.TEST_DATABASE_URL }, async () => {
  const db = new Store(process.env.TEST_DATABASE_URL!);
  try {
    await db.migrate(); await db.migrate();
    const store = new WalletStore(db.pool, randomBytes(32).toString("base64"));
    const user = await db.upsertIdentity("github", randomUUID(), null, null);
    const other = await db.upsertIdentity("github", randomUUID(), null, null);
    const create = (kind: "calls" | "cancel", cancelPlan?: CancelPlan) => store.createOperation({ userId: user, network: "base", address, calls: [], descriptions: [], fingerprint: "test", simulation: {}, kind, ...(cancelPlan ? { cancelPlan } : {}) }, 600);
    const target = await create("calls"); await store.reserve(user, target.id, "original");
    await store.beforeSigning(target.id, operationHash(original()), original());
    await store.finish(target.id, "unknown");
    assert.deepEqual(await store.preparedOperation(user, target.id), original());
    assert.equal(await store.preparedOperation(other, target.id), null);
    const normal = await create("calls");
    await assert.rejects(store.reserve(user, normal.id, "blocked"), /unresolved/);
    const a = await create("cancel", plan(target.id)), b = await create("cancel", plan(target.id));
    await assert.rejects(store.reserve(user, a.id, "wrong tool"), /type/);
    await assert.rejects(store.reserveCancellation(other, a.id, "foreign"), /not found/);
    const results = await Promise.allSettled([store.reserveCancellation(user, a.id, "cancel"), store.reserveCancellation(user, b.id, "cancel")]);
    assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
    const reserved = results[0]!.status === "fulfilled" ? a : b;
    await assert.rejects(store.reserveCancellation(user, reserved.id, "replay"), /consumed/);
    const p = original(); p.operation.nonce = (1n << 64n);
    await store.beforeSigning(reserved.id, operationHash(p), p);
    await store.finish(reserved.id, "unknown");
    assert.equal((await store.operation(user, target.id))!.status, "unknown");
    await assert.rejects(store.reserve(user, normal.id, "still blocked"), /unresolved/);
    await store.finishCancellation(user, reserved.id, tx, "cancelled", null);
    assert.equal((await store.operation(user, target.id))!.status, "cancelled");
    assert.equal((await store.operation(user, reserved.id))!.status, "confirmed");
    assert.equal((await store.reserve(user, normal.id, "unblocked"))!.status, "reserved");
  } finally { await db.close(); }
});

function harness() {
  const prepared = original(), targetHash = operationHash(prepared), cp = plan("target");
  const cancellation = original(); cancellation.operation.nonce = 1n << 64n; cancellation.operation.callData = "0x1234";
  const cancelHash = operationHash(cancellation);
  const target: any = { id: "target", userId: "alice", network: "base", address, status: "unknown", kind: "swap", userOpHash: targetHash, proof: validateOperation(prepared, "base", address, targetHash) };
  const op: any = { ...target, id: "cancel", kind: "cancel", cancelPlan: cp, calls: cancellationCalls(cp), descriptions: [], fingerprint: cancellationFingerprint("base", address, cp), simulation: {}, expiresAt: new Date(Date.now() + 60000), userOpHash: cancelHash, proof: validateOperation(cancellation, "base", address, cancelHash) };
  const abi = parseAbi(["event UserOperationEvent(bytes32 indexed userOpHash,address indexed sender,address indexed paymaster,uint256 nonce,bool success,uint256 actualGasCost,uint256 actualGasUsed)"]);
  const log = (hash: typeof targetHash, nonce: bigint, success = true) => ({ address: entryPoint06Address, topics: encodeEventTopics({ abi, eventName: "UserOperationEvent", args: { userOpHash: hash, sender: address, paymaster: address } }), data: encodeAbiParameters([{ type: "uint256" }, { type: "bool" }, { type: "uint256" }, { type: "uint256" }], [nonce, success, 100n, 100n]) });
  const receipt: any = { status: "success", transactionHash: tx, blockNumber: 20n, blockHash, logs: [log(cancelHash, cancellation.operation.nonce)] };
  const state = { finalized: 19n, timestamp: 100n, nonce: 8n, deadline: 150n as bigint | null, oldIncluded: false, oldSuccess: true, searchFails: false, canonical: true, proof: true };
  const rpc: any = {
    getChainId: async () => 8453,
    getTransactionReceipt: async ({ hash }: any) => hash === tx ? receipt : { ...receipt, transactionHash: hash, logs: [log(targetHash, 7n, state.oldSuccess)] },
    getBlock: async ({ blockTag }: any) => blockTag === "finalized" ? { number: state.finalized, timestamp: state.timestamp } : { hash: state.canonical ? blockHash : tx },
    getBlockNumber: async () => 30n,
    readContract: async () => state.nonce,
    getLogs: async () => { if (state.searchFails) throw new Error("RPC search unavailable"); return state.oldIncluded ? [{ removed: false, transactionHash: blockHash }] : []; },
  };
  const store: any = {
    operation: async (user: string, id: string) => user === "alice" ? id === "target" ? target : op : null,
    preparedOperation: async () => state.proof ? prepared : null,
    permitExpiry: async () => state.deadline,
    finish: async (_id: string, status: string) => { op.status = status; },
    finishCancellation: async (_user: string, _id: string, _tx: string, status: string) => { op.status = "confirmed"; target.status = status; },
  };
  const wallets: any = { rpc: () => rpc, bundler: () => ({ getUserOperationReceipt: async () => ({ receipt }) }), account: async () => ({ address }) };
  const service = new TransactionService(wallets, store, { withPaymentLock: async (_u, f) => f() }, 600);
  return { service, target, op, state, receipt, store, wallets };
}
test("cancellation never unlocks before finality, nonce advance AND Permit2 expiry", async () => {
  const h = harness();
  await h.service.status("alice", "cancel"); assert.equal(h.target.status, "unknown");
  h.state.finalized = 25n; h.state.nonce = 7n;
  await h.service.status("alice", "cancel"); assert.equal(h.target.status, "unknown");
  h.state.nonce = 8n;
  await h.service.status("alice", "cancel"); assert.equal(h.target.status, "unknown", "Permit2 still valid");
  h.state.timestamp = 151n;
  await h.service.status("alice", "cancel"); assert.equal(h.target.status, "cancelled"); assert.equal(h.op.status, "confirmed");
});
test("failed search, reorg, absent nonce proof and forged events cannot unlock", async () => {
  for (const failure of ["search", "reorg", "proof", "event", "search_start"] as const) {
    const h = harness(); h.state.finalized = 25n; h.state.timestamp = 200n;
    if (failure === "search") h.state.searchFails = true;
    if (failure === "reorg") h.state.canonical = false;
    if (failure === "proof") h.state.proof = false;
    if (failure === "event") h.receipt.logs[0].address = address;
    if (failure === "search_start") h.op.cancelPlan.fromBlock = "21";
    await h.service.status("alice", "cancel"); assert.equal(h.target.status, "unknown", failure); assert.equal(h.op.status, "unknown", failure);
  }
});
test("original winning the race is reported as executed/reverted, never cancelled", async () => {
  for (const success of [true, false]) {
    const h = harness(); h.state.finalized = 25n; h.state.timestamp = 200n; h.state.oldIncluded = true; h.state.oldSuccess = success;
    await h.service.status("alice", "cancel"); assert.equal(h.target.status, success ? "confirmed" : "failed");
  }
});
test("legacy opaque CDP operation cannot generate a cancellation preview", async () => {
  const h = harness(); h.state.proof = false;
  await assert.rejects(h.service.prepareCancellation("alice", "target"), /nonce proof is unavailable/);
  await assert.rejects(h.service.prepareCancellation("bob", "target"), /no longer eligible/);
  assert.equal(h.target.status, "unknown");
});


test("cancellation execution consumes its own preview and signs only fixed nonce invalidation in lane 1", async () => {
  const h = harness(); h.op.status = "prepared"; h.state.nonce = 7n;
  let signed = 0;
  h.store.reserveCancellation = async (user: string, id: string) => {
    if (user !== "alice" || id !== "cancel") throw new Error("foreign preview");
    if (h.op.status !== "prepared") throw new Error("consumed");
    h.op.status = "reserved"; return h.op;
  };
  h.store.beforeSigning = async () => { h.op.status = "signing"; };
  h.op.simulation = { network_fee: { approved_max_prefund_wei: "5000" } };
  h.wallets.simulate = async () => ({});
  h.wallets.send = async (_u: string, _n: string, calls: unknown, id: string, before: any, key: bigint, maxPrefund: bigint) => {
    assert.equal(id, "cancel"); assert.equal(key, 1n); assert.equal(maxPrefund, 5000n); assert.deepEqual(calls, cancellationCalls(plan("target")));
    await before(h.op.userOpHash); signed++; return { userOpHash: h.op.userOpHash };
  };
  await assert.rejects(h.service.executeCancellation("bob", "cancel", "cancel"), /foreign/);
  assert.equal((await h.service.executeCancellation("alice", "cancel", "cancel")).status, "submitted");
  assert.equal(h.target.status, "unknown"); assert.equal(signed, 1);
  await assert.rejects(h.service.executeCancellation("alice", "cancel", "repeat"), /consumed/);
});
