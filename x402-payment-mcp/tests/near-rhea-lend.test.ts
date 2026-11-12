import assert from "node:assert/strict";
import test from "node:test";
import { NearPlans } from "../src/near/plan.js";
import { RheaLend, RHEA_LEND } from "../src/near/rhea-lend.js";
import { memoryStore } from "./near-fakes.js";
import { describeNearTransaction, nearFingerprint, renormalizeNearTransaction } from "../src/near/transaction.js";

const SELF = "c1f18b054c4273bc6e13111282f3acdff9b7c9f352ed4f0840f1f792b0d46bf4";
const PK = "ed25519:E45JqeiCWmQhodkZoy7sx1qEE4jcBVZpBE4goYXKtN2o";
const USDC = "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1";
const NEAR = 10n ** 24n;
const MIN = "100000000000000000000000"; // 0.1 NEAR

function asset(extra: number, over: Record<string, unknown> = {}) {
  return { supplied: { balance: "1000000000000000000000000000" }, borrowed: { balance: "500000000000000000000000000" }, reserved: "0", margin_debt: { balance: "0" }, supply_apr: "0.0899", config: { extra_decimals: extra, can_deposit: true, can_withdraw: true, supplied_limit: null }, ...over };
}

function setup(views: Record<string, (args: any) => unknown>) {
  const { store } = memoryStore();
  const calls: string[] = [];
  const rpc = { callFunction: async (c: string, m: string, a: any) => { calls.push(`${c}.${m}`); const f = views[`${c}.${m}`]; if (!f) throw new Error(`no view ${c}.${m}`); return { result: f(a) }; } };
  const accounts: any = { account: async () => ({ userId: "u1", accountId: SELF, publicKey: PK, network: "mainnet" }), rpc, config: { network: "mainnet", previewTtlSeconds: 600 } };
  const executed: { receiverId: string; actions: any[] }[] = [];
  const operations: any = {
    estimate: async (_a: string, txs: any[]) => txs.map(tx => ({ deposit: tx.actions.reduce((t: bigint, a: any) => t + BigInt(a.deposit ?? "0"), 0n), gas: 0n, maxFee: 10n ** 21n, prepay: 10n ** 21n, creates: false, creationCharge: 0n, gasPrice: 1n, available: NEAR, warnings: [], descriptions: describeNearTransaction(tx), minGasPurchasePrice: 1n })),
    execute: async (u: string, id: string, purpose: string, kind: string, _w: string, parent?: string) => {
      const o = await store.reserve(u, id, kind as any, purpose, parent);
      if (nearFingerprint(o.network, o.accountId, o.publicKey, renormalizeNearTransaction({ receiverId: o.receiverId, actions: o.actions })) !== o.fingerprint) throw new Error("preview binding mismatch");
      executed.push({ receiverId: o.receiverId, actions: o.actions });
      views.onExecute?.(o);
      await store.update(u, id, { status: "confirmed" });
      return { operation_id: id, status: "confirmed", transaction_hash: `h${executed.length}`, failed_receipts: 0 };
    },
  };
  const plans = new NearPlans(accounts, operations, store);
  return { lend: new RheaLend(accounts, plans), plans, executed, calls };
}

const args = (a: any) => JSON.parse(Buffer.from(a.args_base64, "base64").toString());
const base = (over: Record<string, (a: any) => unknown> = {}) => ({
  [`${USDC}.ft_metadata`]: () => ({ symbol: "USDC", decimals: 6 }),
  ["wrap.near.ft_metadata"]: () => ({ symbol: "wNEAR", decimals: 24 }),
  [`${RHEA_LEND}.get_asset`]: (a: any) => asset(a.token_id === USDC ? 12 : 0),
  [`${RHEA_LEND}.storage_balance_bounds`]: () => ({ min: MIN, max: null }),
  [`${USDC}.storage_balance_bounds`]: () => ({ min: "1250000000000000000000", max: null }),
  ["wrap.near.storage_balance_bounds"]: () => ({ min: "1250000000000000000000", max: null }),
  [`${USDC}.storage_balance_of`]: () => ({ total: "1", available: "0" }),
  ["wrap.near.storage_balance_of"]: () => ({ total: "1", available: "0" }),
  [`${USDC}.ft_balance_of`]: () => "1495196",
  ["wrap.near.ft_balance_of"]: () => "0",
  [`${RHEA_LEND}.get_account`]: () => null,
  ...over,
});

test("rhea lend supply: unregistered account gets the non-refundable 0.1 NEAR registration, then ft_transfer_call msg \"\" to Burrow", async () => {
  let registered = false;
  const v: any = base({ [`${RHEA_LEND}.storage_balance_of`]: () => registered ? { total: MIN, available: "0" } : null });
  v.onExecute = (o: any) => { if (o.receiverId === RHEA_LEND) registered = true; };
  const { lend, plans, executed } = setup(v);
  const prev: any = await lend.prepareSupply("u1", { token: "usdc", amount: "0.5" });
  assert.equal(prev.steps.length, 2);
  assert.equal(prev.registration_near, "0.1");
  assert.equal(prev.lend.supply_apr_percent, 8.99);
  assert.match(prev.notes.join(" "), /stays locked/);
  const r: any = await plans.execute("u1", prev.operation_id, "supply");
  assert.equal(r.status, "confirmed");
  assert.equal(executed[0]!.receiverId, RHEA_LEND);
  assert.deepEqual(args(executed[0]!.actions[0]), { account_id: SELF, registration_only: true });
  assert.equal(executed[0]!.actions[0].deposit, MIN);
  assert.equal(executed[1]!.receiverId, USDC);
  assert.deepEqual(args(executed[1]!.actions[0]), { receiver_id: RHEA_LEND, amount: "500000", msg: "" });
});

test("rhea lend supply: registered account and NEAR wraps in the same transaction; wallet shortfall and cap are refused", async () => {
  const { lend } = setup(base({ [`${RHEA_LEND}.storage_balance_of`]: () => ({ total: MIN, available: "0" }) }));
  const prev: any = await lend.prepareSupply("u1", { token: "NEAR", amount: "0.05" });
  assert.equal(prev.steps.length, 1);
  assert.equal(prev.steps[0].receiver_id, "wrap.near");
  assert.deepEqual(prev.steps[0].actions.map((a: any) => a.method_name), ["near_deposit", "ft_transfer_call"]);
  assert.equal(prev.wrapped_from_native_near, "0.05");
  await assert.rejects(lend.prepareSupply("u1", { token: "USDC", amount: "2" }), /not enough USDC/);
  const capped = setup(base({ [`${RHEA_LEND}.storage_balance_of`]: () => ({ total: MIN, available: "0" }), [`${RHEA_LEND}.get_asset`]: () => asset(12, { config: { extra_decimals: 12, can_deposit: true, can_withdraw: true, supplied_limit: "1000000000000000000000000000" } }) }));
  await assert.rejects(capped.lend.prepareSupply("u1", { token: "USDC", amount: "0.5" }), /supply cap/);
});

test("rhea lend withdraw: all uses Withdraw without amount, partial uses max_amount in inner decimals; over-withdraw refused; low liquidity warned", async () => {
  const acct = { supplied: [{ token_id: USDC, balance: "500123000000000000", shares: "1", apr: "0.0899" }], collateral: [], borrowed: [] };
  const { lend } = setup(base({ [`${RHEA_LEND}.get_account`]: () => acct }));
  const all: any = await lend.prepareWithdraw("u1", { token: "USDC" });
  assert.equal(all.steps.length, 1);
  const a0 = all.steps[0].actions[0];
  assert.equal(a0.method_name, "execute"); assert.equal(a0.deposit_yocto, "1");
  assert.deepEqual(a0.args, { actions: [{ Withdraw: { token_id: USDC } }] });
  assert.equal(all.lend.supplied, "0.500123");
  const part: any = await lend.prepareWithdraw("u1", { token: "USDC", amount: "0.2" });
  assert.deepEqual(part.steps[0].actions[0].args, { actions: [{ Withdraw: { token_id: USDC, max_amount: "200000000000000000" } }] });
  await assert.rejects(lend.prepareWithdraw("u1", { token: "USDC", amount: "0.6" }), /only 0.500123 USDC supplied/);
  const tight = setup(base({ [`${RHEA_LEND}.get_account`]: () => acct, [`${RHEA_LEND}.get_asset`]: () => asset(12, { supplied: { balance: "1000000000000000000" }, borrowed: { balance: "900000000000000000" } }) }));
  const w: any = await tight.lend.prepareWithdraw("u1", { token: "USDC" });
  assert.match(w.warnings[0], /free liquidity/);
  const none = setup(base());
  await assert.rejects(none.lend.prepareWithdraw("u1", { token: "USDC" }), /nothing supplied/);
});

test("rhea lend withdraw NEAR: second step unwraps exactly the withdrawn wNEAR after checking the wallet balance", async () => {
  const acct = { supplied: [{ token_id: "wrap.near", balance: "50000000000000000000000", shares: "1", apr: "0.003" }], collateral: [], borrowed: [] };
  const { lend } = setup(base({ [`${RHEA_LEND}.get_account`]: () => acct }));
  const prev: any = await lend.prepareWithdraw("u1", { token: "NEAR" });
  assert.equal(prev.steps.length, 2);
  assert.equal(prev.steps[1].receiver_id, "wrap.near");
  assert.deepEqual(prev.steps[1].actions[0].args, { amount: "50000000000000000000000" });
  assert.deepEqual(prev.steps[1].checks_before_signing, ["wallet wNEAR >= 0.05"]);
  const keep: any = await lend.prepareWithdraw("u1", { token: "NEAR", unwrap_near: false });
  assert.equal(keep.steps.length, 1);
});

test("rhea lend positions: inner decimals scaled back, sides kept, zero dust dropped", async () => {
  const acct = { supplied: [{ token_id: USDC, balance: "500123000000000000", shares: "1", apr: "0.0899" }, { token_id: USDC, balance: "5", shares: "1" }], collateral: [{ token_id: "wrap.near", balance: "2000000000000000000000000", shares: "1", apr: "0.003" }], borrowed: [] };
  const { lend } = setup(base({ [`${RHEA_LEND}.get_account`]: () => acct }));
  const rows = await lend.positions(SELF);
  assert.deepEqual(rows.map(r => [r.side, r.symbol, r.formatted, r.apr_percent]), [["supplied", "USDC", "0.500123", 8.99], ["collateral", "wNEAR", "2", 0.3]]);
});
