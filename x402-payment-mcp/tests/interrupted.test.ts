import assert from "node:assert/strict";
import test from "node:test";
import { resolveInterrupted } from "../src/interrupted.js";

const address = "0x1111111111111111111111111111111111111111";
function harness(rows: { id: string; status: any; permitDeadline: bigint | null | undefined }[], finalized = 100n) {
  const failed: string[] = []; let blockReads = 0;
  const store = { interruptedOperations: async () => rows, failInterrupted: async (_u: string, id: string) => { failed.push(id); } };
  const rpc = () => ({ getBlock: async ({ blockTag }: any) => { assert.equal(blockTag, "finalized"); blockReads++; return { timestamp: finalized }; } }) as any;
  return { run: () => resolveInterrupted(store, rpc, "alice", "base", address), failed, reads: () => blockReads };
}

test("a reservation without a UserOperation hash was never signed and is released immediately", async () => {
  const h = harness([{ id: "r", status: "reserved", permitDeadline: null }]);
  await h.run(); assert.deepEqual(h.failed, ["r"]); assert.equal(h.reads(), 0);
});

test("a swap that may hold a signed Permit2 is released only after a finalized block passes its deadline", async () => {
  const live = harness([{ id: "s", status: "unknown", permitDeadline: 100n }], 100n);
  await live.run(); assert.deepEqual(live.failed, [], "block.timestamp == deadline is still valid for Permit2");
  const expired = harness([{ id: "s", status: "unknown", permitDeadline: 100n }], 101n);
  await expired.run(); assert.deepEqual(expired.failed, ["s"]);
});

test("native-input swaps without Permit2 are released; missing signing context fails closed", async () => {
  const h = harness([{ id: "native", status: "signing", permitDeadline: null }, { id: "unknown-context", status: "unknown", permitDeadline: undefined }]);
  await h.run(); assert.deepEqual(h.failed, ["native"]); assert.equal(h.reads(), 0);
});
