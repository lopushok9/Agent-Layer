import assert from "node:assert/strict";
import test from "node:test";
import { Swaps } from "../src/swaps.js";

const ETH = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const input = { network: "base" as const, from_token: ETH, to_token: USDC, from_amount_atomic: "10000000000000000", slippage_bps: 50 };
function harness(opts: { ensoFails?: boolean; noEnso?: boolean; op?: any } = {}) {
  const calls: string[] = [], seen: any[] = [];
  const cdp = { preview: async (...a: any[]) => { calls.push("cdp.preview"); seen.push(a); return { operation_id: "cdp-op" } as any; }, execute: async () => { calls.push("cdp.execute"); return { status: "submitted" } as any; }, operation: async () => opts.op ?? null };
  const enso = { preview: async (...a: any[]) => { calls.push("enso.preview"); seen.push(a); if (opts.ensoFails) throw new Error("no route found"); return { operation_id: "enso-op", route: { provider: "enso" } } as any; } };
  const transactions = { execute: async () => { calls.push("tx.execute"); return { status: "submitted" } as any; } };
  return { swaps: new Swaps(cdp, opts.noEnso ? undefined : enso, transactions), calls, seen };
}

test("a swap is routed by Enso with the same tokens, amount and slippage", async () => {
  const h = harness();
  const r: any = await h.swaps.preview("u", input);
  assert.deepEqual(h.calls, ["enso.preview"]);
  assert.deepEqual(h.seen[0][1], { network: "base", token_in: ETH, amount_in: input.from_amount_atomic, token_out: USDC, slippage_bps: 50 });
  assert.equal(r.provider, "enso"); assert.equal(r.operation_id, "enso-op"); assert.match(r.next_step, /swap_execute/);
});

test("CDP is used when Enso cannot route, is absent, or slippage is zero", async () => {
  const failed = harness({ ensoFails: true }), r: any = await failed.swaps.preview("u", input);
  assert.deepEqual(failed.calls, ["enso.preview", "cdp.preview"]);
  assert.equal(r.provider, "cdp"); assert.ok(r.enso_unavailable, "the reason is reported");
  const none = harness({ noEnso: true }), r2: any = await none.swaps.preview("u", input);
  assert.deepEqual(none.calls, ["cdp.preview"]); assert.equal(r2.enso_unavailable, undefined);
  const zero = harness(), r3: any = await zero.swaps.preview("u", { ...input, slippage_bps: 0 });
  assert.deepEqual(zero.calls, ["cdp.preview"], "Enso would widen a zero tolerance to 1 bp"); assert.match(r3.enso_unavailable, /1 bp/);
});

test("swap_execute runs an Enso route as its prepared calls and a CDP swap as a managed swap, nothing else", async () => {
  const enso = harness({ op: { kind: "calls", simulation: { route: { provider: "enso" } } } });
  await enso.swaps.execute("u", "id", "swap"); assert.deepEqual(enso.calls, ["tx.execute"]);
  const cdp = harness({ op: { kind: "swap", simulation: {} } });
  await cdp.swaps.execute("u", "id", "swap"); assert.deepEqual(cdp.calls, ["cdp.execute"]);
  const action = harness({ op: { kind: "calls", simulation: { route: { provider: "enso", protocol: "aave-v3" } } } });
  await assert.rejects(action.swaps.execute("u", "id", "swap"), /not a swap preview/); assert.deepEqual(action.calls, []);
  // A plain transaction preview goes to the managed-swap path, whose store
  // refuses an operation of another kind.
  const plain = harness({ op: { kind: "calls", simulation: {} } });
  await plain.swaps.execute("u", "id", "swap"); assert.deepEqual(plain.calls, ["cdp.execute"]);
});
