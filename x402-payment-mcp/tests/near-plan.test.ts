import assert from "node:assert/strict";
import test from "node:test";
import { NearPlans } from "../src/near/plan.js";
import { RheaPools } from "../src/near/rhea.js";
import { memoryStore } from "./near-fakes.js";
import { describeNearTransaction, nearFingerprint, renormalizeNearTransaction } from "../src/near/transaction.js";

const SELF = "c1f18b054c4273bc6e13111282f3acdff9b7c9f352ed4f0840f1f792b0d46bf4";
const PK = "ed25519:E45JqeiCWmQhodkZoy7sx1qEE4jcBVZpBE4goYXKtN2o";
const USDC = "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1";
const REF = "v2.ref-finance.near";
const NEAR = 10n ** 24n;

// RPC fake: views answered from a mutable table keyed by "contract.method".
function chain(views: Record<string, (args: any) => unknown>) {
  const calls: string[] = [];
  return { calls, rpc: { callFunction: async (c: string, m: string, a: any) => { calls.push(`${c}.${m}`); const f = views[`${c}.${m}`]; if (!f) throw new Error(`no view ${c}.${m}`); return { result: f(a) }; } } };
}

function setup(views: Record<string, (args: any) => unknown>, outcomes: string[] = [], available = NEAR) {
  const { store, ops } = memoryStore();
  const { rpc, calls } = chain(views);
  const accounts: any = { account: async () => ({ userId: "u1", accountId: SELF, publicKey: PK, network: "mainnet" }), rpc, config: { network: "mainnet", previewTtlSeconds: 600 } };
  const executed: { receiverId: string; methods: string[]; parent: string | undefined }[] = [];
  const operations: any = {
    estimate: async (_a: string, txs: any[]) => txs.map(tx => {
      const deposit = tx.actions.reduce((t: bigint, a: any) => t + BigInt(a.deposit ?? a.amount ?? "0"), 0n);
      return { deposit, gas: 0n, maxFee: 10n ** 21n, prepay: 10n ** 21n, creates: false, creationCharge: 0n, gasPrice: 1n, available, warnings: [], descriptions: describeNearTransaction(tx), minGasPurchasePrice: 1n };
    }),
    execute: async (u: string, id: string, purpose: string, kind: string, _w: string, parent?: string) => {
      const o = await store.reserve(u, id, kind as any, purpose, parent);
      // Same binding check as NearOperations.execute (store reorders keys like JSONB).
      if (nearFingerprint(o.network, o.accountId, o.publicKey, renormalizeNearTransaction({ receiverId: o.receiverId, actions: o.actions })) !== o.fingerprint) throw new Error("preview binding mismatch");
      executed.push({ receiverId: o.receiverId, methods: o.actions.map((a: any) => a.method), parent });
      const status = outcomes.shift() ?? "confirmed";
      await store.update(u, id, { status: status as any });
      return { operation_id: id, status, transaction_hash: `h${executed.length}`, failed_receipts: status === "partial" ? 1 : 0, ...(status === "partial" ? { status: "confirmed" } : {}) };
    },
    status: async (_u: string, id: string) => ({ operation_id: id, status: "confirmed", transaction_hash: "late", failed_receipts: 0 }),
  };
  const plans = new NearPlans(accounts, operations, store);
  return { plans, rhea: new RheaPools(accounts, plans), store, ops, executed, calls };
}

const fc = (method_name: string, args: Record<string, unknown> = {}, deposit_yocto = "0") => ({ type: "function_call" as const, method_name, args, deposit_yocto, gas: "30000000000000" });

test("near_plan: one preview for several receivers, totals, steps run in order as child near_tx ops of the running plan", async () => {
  const { plans, executed, ops } = setup({ [`${REF}.get_deposits`]: () => ({ [USDC]: "10000" }) });
  const prev: any = await plans.prepare("u1", { title: "two steps", steps: [
    { title: "deposit", transaction: { receiver_id: USDC, actions: [fc("ft_transfer_call", { receiver_id: REF, amount: "10000", msg: "" }, "1")] } },
    { title: "use", transaction: { receiver_id: REF, actions: [fc("add_stable_liquidity", { pool_id: 1, amounts: ["0", "10000"], min_shares: "1" }, "5000000000000000000000")] },
      checks: [{ label: "Rhea USDC >= 0.01", contract_id: REF, method_name: "get_deposits", args: { account_id: SELF }, path: [USDC], op: "gte", value: "10000" }] },
  ] });
  assert.equal(prev.kind, "near_plan"); assert.equal(prev.steps.length, 2);
  assert.equal(prev.total_attached_near, "0.005000000000000000000001");
  assert.deepEqual(prev.steps[1].checks_before_signing, ["Rhea USDC >= 0.01"]);
  const r: any = await plans.execute("u1", prev.operation_id, "test plan");
  assert.equal(r.status, "confirmed"); assert.equal(r.steps_done, 2);
  assert.deepEqual(executed.map(e => [e.receiverId, e.methods[0], e.parent]), [[USDC, "ft_transfer_call", prev.operation_id], [REF, "add_stable_liquidity", prev.operation_id]]);
  assert.equal(ops.get(prev.operation_id)!.status, "confirmed");
  await assert.rejects(plans.execute("u1", prev.operation_id, "again"), /already consumed/);
});

test("near_plan: a failing check stops before signing that step; a failed step or failed receipts stop the rest", async () => {
  const s1 = setup({ [`${REF}.get_deposits`]: () => ({ [USDC]: "9999" }) });
  const steps = [
    { title: "deposit", transaction: { receiver_id: USDC, actions: [fc("ft_transfer_call", { receiver_id: REF, amount: "10000", msg: "" }, "1")] } },
    { title: "use", transaction: { receiver_id: REF, actions: [fc("add_stable_liquidity", {}, "1")] }, checks: [{ label: "Rhea USDC >= 0.01", contract_id: REF, method_name: "get_deposits", args: {}, path: [USDC], op: "gte" as const, value: "10000" }] },
  ];
  const a: any = await s1.plans.execute("u1", (await s1.plans.prepare("u1", { title: "test", steps }) as any).operation_id, "p");
  assert.equal(a.status, "failed"); assert.equal(s1.executed.length, 1);
  assert.match(a.reason, /stopped before step 2 .*got 9999, need gte 10000/);

  const s2 = setup({ [`${REF}.get_deposits`]: () => ({ [USDC]: "10000" }) }, ["partial"]);
  const b: any = await s2.plans.execute("u1", (await s2.plans.prepare("u1", { title: "test", steps }) as any).operation_id, "p");
  assert.equal(b.status, "failed"); assert.equal(s2.executed.length, 1); assert.match(b.reason, /failed receipts/);

  const s3 = setup({}, ["failed"]);
  const c: any = await s3.plans.execute("u1", (await s3.plans.prepare("u1", { title: "test", steps }) as any).operation_id, "p");
  assert.equal(c.status, "failed"); assert.equal(s3.executed.length, 1);
});

test("near_plan: unknown step outcome blocks other operations until near_plan_status reconciles it", async () => {
  const { plans, executed, ops, store } = setup({ [`${REF}.get_deposits`]: () => ({ [USDC]: "10000" }) }, ["unknown"]);
  const steps = [
    { title: "step a", transaction: { receiver_id: USDC, actions: [fc("ft_transfer_call", { receiver_id: REF, amount: "1", msg: "" }, "1")] } },
    { title: "step b", transaction: { receiver_id: REF, actions: [fc("x", {}, "1")] } },
  ];
  const id = (await plans.prepare("u1", { title: "test", steps }) as any).operation_id;
  const r: any = await plans.execute("u1", id, "p");
  assert.equal(r.status, "unknown"); assert.equal(executed.length, 1);
  const other = (await plans.prepare("u1", { title: "test 2", steps }) as any).operation_id;
  await assert.rejects(plans.execute("u1", other, "p"), /unresolved NEAR operation/);
  const s: any = await plans.status("u1", id);
  assert.equal(s.status, "failed"); assert.match(s.reason, /stopped at step 1: confirmed; later steps were not signed/);
  assert.equal(ops.get(id)!.status, "failed");
  // a child cannot be executed on its own as a plan step once the plan is not running
  const child = [...ops.values()].find(o => (o.plan as any)?.near_plan === id)!;
  await assert.rejects(store.reserve("u1", child.id, "near_tx", "x", id), /already consumed|not a step of a running plan/);
});

test("near_plan: refuses a plan the wallet cannot fund", async () => {
  const { plans } = setup({}, [], 10n ** 21n);
  await assert.rejects(plans.prepare("u1", { title: "test", steps: [{ title: "big", transaction: { receiver_id: REF, actions: [fc("storage_deposit", {}, NEAR.toString())] } }] }), /insufficient NEAR for the whole plan/);
});

const DEGEN = { pool_kind: "DEGEN_SWAP", token_account_ids: ["wrap.near", USDC], amounts: ["77773784687110412336242082273", "265175707531"] };
const meta = { "wrap.near.ft_metadata": () => ({ symbol: "wNEAR", decimals: 24 }), [`${USDC}.ft_metadata`]: () => ({ symbol: "USDC", decimals: 6 }) };

test("rhea_lp_prepare: new account gets storage for account + 2 tokens, NEAR wrapped (with wrap.near registration), auto amount at pool ratio, checks before the add", async () => {
  const { rhea } = setup({
    ...meta,
    [`${REF}.get_pool`]: () => DEGEN,
    [`${REF}.predict_add_degen_liquidity`]: (a: any) => { assert.deepEqual(a.degens, null); return "22815482535074897740382"; },
    [`${REF}.get_user_storage_state`]: () => null,
    [`${REF}.get_deposits`]: () => { throw new Error("not registered"); },
    [`${REF}.get_pool_shares`]: () => "0",
    "wrap.near.ft_balance_of": () => "0",
    [`${USDC}.ft_balance_of`]: () => "1495326",
    "wrap.near.storage_balance_of": () => null,
    "wrap.near.storage_balance_bounds": () => ({ min: "1250000000000000000000" }),
  });
  const p: any = await rhea.prepareAdd("u1", { pool_id: 5515, amounts: { usdc: "0.01", NEAR: "auto" } });
  const wnear = 10000n * 77773784687110412336242082273n / 265175707531n;
  assert.deepEqual(p.add.map((a: any) => a.token), ["wNEAR", "USDC"]);
  assert.equal(p.rhea_storage_deposit_near, "0.00398");
  assert.equal(p.steps.length, 4);
  assert.deepEqual(p.steps[0].actions.map((a: any) => a.method_name), ["storage_deposit", "register_tokens"]);
  assert.equal(p.steps[0].attached_near, "0.003980000000000000000001");
  assert.deepEqual([p.steps[1].receiver_id, ...p.steps[1].actions.map((a: any) => a.method_name)], ["wrap.near", "storage_deposit", "near_deposit", "ft_transfer_call"]);
  assert.equal(p.steps[1].actions[2].args.amount, wnear.toString());
  assert.equal(p.steps[2].actions[0].args.amount, "10000");
  const add = p.steps[3].actions[0];
  assert.equal(add.method_name, "add_stable_liquidity");
  assert.equal(add.args.min_shares, (22815482535074897740382n * 9900n / 10000n).toString());
  assert.equal(p.steps[3].checks_before_signing.length, 3);
});

test("rhea_lp_prepare: registered account with Rhea balance skips storage and deposits only the missing part; simple pools use need_amounts; errors are explicit", async () => {
  const views = {
    ...meta,
    [`${REF}.get_pool`]: () => ({ ...DEGEN, pool_kind: "SIMPLE_POOL" }),
    [`${REF}.predict_add_simple_liquidity`]: (a: any) => ({ need_amounts: [a.amounts[0], a.amounts[1] === "10000" ? "9000" : a.amounts[1]], mint_shares: "500" }),
    [`${REF}.get_user_storage_state`]: () => ({ deposit: "5000000000000000000000", usage: "3980000000000000000000" }),
    [`${REF}.get_deposits`]: () => ({ "wrap.near": "0", [USDC]: "4000" }),
    [`${REF}.get_pool_shares`]: () => "0",
    "wrap.near.ft_balance_of": () => (10n ** 22n).toString(),
    [`${USDC}.ft_balance_of`]: () => "1495326",
    "wrap.near.storage_balance_of": () => ({ total: "1", available: "0" }),
    "wrap.near.storage_balance_bounds": () => ({ min: "1" }),
  };
  const { rhea } = setup(views);
  const p: any = await rhea.prepareAdd("u1", { pool_id: 4512, amounts: { NEAR: "0.003", USDC: "0.01" } });
  assert.equal(p.rhea_storage_deposit_near, undefined);
  assert.deepEqual(p.steps.map((s: any) => s.receiver_id), ["wrap.near", USDC, REF]);
  assert.deepEqual(p.steps[0].actions.map((a: any) => a.method_name), ["ft_transfer_call"]);    // wallet already has wNEAR
  assert.equal(p.steps[1].actions[0].args.amount, "5000");                                     // 9000 needed - 4000 on Rhea
  assert.deepEqual(p.steps[2].actions[0].args.min_amounts, ["2970000000000000000000", "8910"]);
  assert.equal(p.steps[2].actions[0].method_name, "add_liquidity");
  await assert.rejects(rhea.prepareAdd("u1", { pool_id: 4512, amounts: { USDC: "0.01" } }), /simple pools need every token/);
  await assert.rejects(rhea.prepareAdd("u1", { pool_id: 4512, amounts: { DOGE: "1" } }), /not a token of pool 4512/);
  await assert.rejects(rhea.prepareAdd("u1", { pool_id: 4512, amounts: { NEAR: "0.003", USDC: "5" } }), /not enough USDC in the wallet/);
  const dcl = setup({ [`${REF}.get_pool`]: () => ({ ...DEGEN, pool_kind: "DCL" }) });
  await assert.rejects(dcl.rhea.prepareAdd("u1", { pool_id: 1, amounts: { USDC: "1" } }), /only simple, stable, rated and degen/);
});

test("rhea_lp_exit_prepare: remove + withdraw of every token in ONE transaction, wallet registered first where needed", async () => {
  const { rhea } = setup({
    ...meta,
    [`${REF}.get_pool`]: () => DEGEN,
    [`${REF}.get_pool_shares`]: () => "22815320953590359906836",
    [`${REF}.predict_remove_liquidity`]: () => ["2898496501296008298265", "9882"],
    [`${REF}.get_deposits`]: () => ({ "wrap.near": "0", [USDC]: "0" }),
    [`${USDC}.storage_balance_of`]: () => null,
    [`${USDC}.storage_balance_bounds`]: () => ({ min: "1250000000000000000000" }),
  });
  const p: any = await rhea.prepareExit("u1", { pool_id: 5515 });
  assert.equal(p.steps.length, 2);
  assert.deepEqual([p.steps[0].receiver_id, p.steps[0].actions[0].method_name], [USDC, "storage_deposit"]);
  const last = p.steps[1];
  assert.deepEqual(last.actions.map((a: any) => a.method_name), ["remove_liquidity", "withdraw", "withdraw"]);
  assert.deepEqual(last.actions[0].args.min_amounts, [(2898496501296008298265n * 9900n / 10000n).toString(), "9783"]);
  assert.deepEqual(last.actions.slice(1).map((a: any) => [a.args.token_id, a.args.amount, a.args.skip_unwrap_near]), [["wrap.near", "0", false], [USDC, "0", false]]);
  assert.equal(p.receive[0].token, "NEAR (unwrapped)");
  await assert.rejects(rhea.prepareExit("u1", { pool_id: 5515, shares: "99999999999999999999999999" }), /shares must be between/);
});
