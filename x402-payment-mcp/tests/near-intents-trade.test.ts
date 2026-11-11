import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import test from "node:test";
import { baseDecode } from "@near-js/utils";
import { NearAccountService, publicKeyBytes } from "../src/near/account.js";
import { loadNearConfig } from "../src/near/config.js";
import { verifyEd25519 } from "../src/near/keys.js";
import { NearRpc } from "../src/near/rpc.js";
import { IntentsTrades, nep413Prehash, SolverRelayClient, versionedNonce } from "../src/near/solver-relay.js";
import { memoryStore } from "./near-fakes.js";

const config = loadNearConfig({ NEAR_RPC_URL: "https://rpc.example", NEAR_KEY_ENCRYPTION_KEY: randomBytes(32).toString("base64") })!;
const WNEAR = "nep141:wrap.near", USDC = "nep141:usdc.near", SOL = "nep141:sol.omft.near";
const TOKENS: Record<string, { assetId: string; symbol: string; decimals: number; blockchain: string }> = { NEAR: { assetId: WNEAR, symbol: "wNEAR", decimals: 24, blockchain: "near" }, "USDC@near": { assetId: USDC, symbol: "USDC", decimals: 6, blockchain: "near" }, "SOL@sol": { assetId: SOL, symbol: "SOL", decimals: 9, blockchain: "sol" } };

type World = { balance: Record<string, string>; quotes: { amount_out: string; hash: string }[]; published: any[]; relayStatus: string; simError?: string; usedNonces: Set<string>; publishStatus?: string; registered?: boolean; oneclickDeadlineMs?: number; submitted?: string[]; oneclickOut?: string };

function setup(w: World, now = () => Date.now()) {
  const { store, ops } = memoryStore();
  let pk = "";
  const rpc = new NearRpc("https://rpc.example", "mainnet", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body));
    const ok = (result: unknown) => new Response(JSON.stringify({ result }));
    const view = (v: unknown) => ok({ result: [...Buffer.from(JSON.stringify(v))], logs: [], block_height: 1 });
    if (b.method === "query" && b.params.request_type === "call_function" && b.params.account_id === "intents.near") {
      const args = JSON.parse(Buffer.from(b.params.args_base64, "base64").toString());
      if (b.params.method_name === "current_salt") return view("252812b3");
      if (b.params.method_name === "mt_balance_of") return view(w.balance[args.token_id] ?? "0");
      if (b.params.method_name === "is_nonce_used") return view(w.usedNonces.has(args.nonce));
      if (b.params.method_name === "simulate_intents") {
        const s = args.signed[0];
        const hash = nep413Prehash({ message: s.payload.message, nonce: Buffer.from(s.payload.nonce, "base64"), recipient: s.payload.recipient });
        if (!verifyEd25519(publicKeyBytes(pk), hash, baseDecode(s.signature.slice(8)))) return ok({ error: "wasm execution failed with error: GuestPanic { panic_msg: \"invalid signature\" }", logs: [] });
        if (w.simError) return ok({ error: w.simError, logs: [] });
        return view({ intents_executed: [], state: {} });
      }
    }
    if (b.method === "query" && b.params.request_type === "call_function" && b.params.account_id === "usdc.near") {
      if (b.params.method_name === "storage_balance_of") return view(w.registered ? { total: "1250000000000000000000", available: "0" } : null);
      if (b.params.method_name === "storage_balance_bounds") return view({ min: "1250000000000000000000", max: "1250000000000000000000" });
    }
    throw new Error(`unexpected ${b.method} ${b.params?.method_name}`);
  }) as typeof fetch);
  const relay = new SolverRelayClient("https://relay.example", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body)), p = b.params[0];
    const reply = (result: unknown) => new Response(JSON.stringify({ jsonrpc: "2.0", id: 1, result }));
    if (b.method === "quote") return reply(w.quotes.map(q => ({ quote_hash: q.hash, defuse_asset_identifier_in: p.defuse_asset_identifier_in, defuse_asset_identifier_out: p.defuse_asset_identifier_out, amount_in: p.exact_amount_in, amount_out: q.amount_out, expiration_time: new Date(now() + 60_000).toISOString() })));
    if (b.method === "publish_intents") { w.published.push(p); return reply({ status: w.publishStatus ?? "OK", intent_hashes: ["x"] }); }
    if (b.method === "get_status") return reply({ intent_hash: p.intent_hash, status: w.relayStatus, data: { hash: "SettleTx111" } });
    throw new Error("unexpected relay method");
  }) as typeof fetch);
  const accounts = new NearAccountService(config, store, rpc);
  const intents = {
    asset: async (ref: string) => TOKENS[ref] ?? Object.values(TOKENS).find(t => t.assetId === ref)!, intentsBalanceOf: async (_a: string, t: string) => BigInt(w.balance[t] ?? "0"),
    quoteFromIntents: async (u: string, input: any) => {
      const self = (await accounts.account(u)).accountId;
      const plan = { deposit_address: "d".repeat(64), deposit_memo: null, correlation_id: "c1", deadline: new Date(now() + (w.oneclickDeadlineMs ?? 1_800_000)).toISOString(), origin_asset: (TOKENS[input.origin_asset] ?? { assetId: input.origin_asset }).assetId, destination_asset: SOL, amount_in: input.amount, min_amount_out: "123", recipient: self, pay_from: "intents", deliver_to: "intents" };
      return { self, plan, have: BigInt(w.balance[plan.origin_asset] ?? "0"), description: { protocol: "near_intents_1click" } };
    },
    dryQuoteFromIntents: async () => w.oneclickOut === undefined ? null : { amountOut: w.oneclickOut, timeEstimate: 12 },
    oneClickStatus: async () => ({ swap_status: "PROCESSING" }),
    submitDeposit: async (tx: string, dep: string, sender: string) => { w.submitted = [tx, dep, sender]; },
  } as any;
  const trades = new IntentsTrades(accounts, store, intents, relay, now);
  return { trades, ops, init: async (u: string) => { const a = await accounts.account(u); pk = a.publicKey; return a; } };
}
const world = (): World => ({ balance: { [WNEAR]: (10n ** 24n).toString() }, quotes: [{ amount_out: "3700000", hash: "q1" }, { amount_out: "3727723", hash: "q2" }], published: [], relayStatus: "SETTLED", usedNonces: new Set(), registered: true });
const ONE = (10n ** 24n).toString();

test("versioned nonce layout: magic prefix, V1, salt, deadline ns, 15 random bytes", () => {
  const n = versionedNonce("252812b3", 1_700_000_000_000, Buffer.alloc(15, 7));
  assert.equal(n.length, 32);
  assert.equal(n.subarray(0, 4).toString("hex"), "5628f6c6"); assert.equal(n[4], 0); assert.equal(n.subarray(5, 9).toString("hex"), "252812b3");
  assert.equal(n.readBigInt64LE(9), 1_700_000_000_000n * 1_000_000n); assert.deepEqual(n.subarray(17), Buffer.alloc(15, 7));
});

test("trade prepare: best solver quote, minimum from slippage, nothing signed", async () => {
  const w = world();
  const { trades, ops, init } = setup(w);
  await init("u1");
  const p: any = await trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE });
  assert.equal(p.buy.quoted, "3727723"); assert.equal(p.buy.minimum, (3727723n * 9950n / 10000n).toString()); assert.equal(p.solver_quotes, 2);
  assert.equal([...ops.values()][0]!.kind, "intents_trade"); assert.equal(w.published.length, 0);
  w.quotes = [];
  await assert.rejects(trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE }), /no solver quotes/);
  await assert.rejects(trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: "2" + ONE }), /intents balance holds/);
});

test("trade execute: signs one NEP-413 token_diff with the account key, publishes the best quote, settles", async () => {
  const w = world();
  const { trades, init } = setup(w);
  const a = await init("u1");
  const p: any = await trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE });
  const r: any = await trades.execute("u1", p.operation_id, "swap 1 NEAR to USDC inside intents");
  assert.equal(r.status, "confirmed"); assert.equal(r.settlement_tx, "SettleTx111");
  assert.equal(w.published.length, 1);
  const { quote_hashes, signed_datas: [s] } = w.published[0];
  assert.deepEqual(quote_hashes, ["q2"]);
  assert.equal(s.standard, "nep413"); assert.equal(s.payload.recipient, "intents.near"); assert.equal(s.public_key, a.publicKey);
  const msg = JSON.parse(s.payload.message);
  assert.equal(msg.signer_id, a.accountId);
  assert.deepEqual(msg.intents, [{ intent: "token_diff", diff: { [WNEAR]: `-${ONE}`, [USDC]: "3727723" } }]);
  assert.ok(Date.parse(msg.deadline) - Date.now() <= 46_000);
  const hash = nep413Prehash({ message: s.payload.message, nonce: Buffer.from(s.payload.nonce, "base64"), recipient: "intents.near" });
  assert.ok(verifyEd25519(publicKeyBytes(a.publicKey), hash, baseDecode(s.signature.slice(8))));
  await assert.rejects(trades.execute("u1", p.operation_id, "again"), /consumed/);
});

test("trade execute: refuses before signing when the fresh quote is below the confirmed minimum or simulation rejects", async () => {
  const w = world();
  const { trades, ops, init } = setup(w);
  await init("u1");
  const p1: any = await trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE });
  w.quotes = [{ amount_out: "3000000", hash: "low" }];
  await assert.rejects(trades.execute("u1", p1.operation_id, "x"), /below the confirmed minimum/);
  assert.equal(ops.get(p1.operation_id)!.status, "failed"); assert.equal(ops.get(p1.operation_id)!.txHash, null);
  w.quotes = [{ amount_out: "3727723", hash: "q2" }];
  const p2: any = await trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE });
  w.simError = "wasm execution failed with error: GuestPanic { panic_msg: \"insufficient balance or overflow\" }";
  await assert.rejects(trades.execute("u1", p2.operation_id, "x"), /rejected the signed intent in simulation \(.*insufficient balance/);
  assert.equal(w.published.length, 0);
});

test("trade status: an unsettled intent past its deadline with an unused nonce is failed; nothing moved", async () => {
  const w = world(); w.relayStatus = "PENDING";
  let t = Date.now();
  const { trades, init } = setup(w, () => t);
  await init("u1");
  const p: any = await trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE });
  const r: any = await trades.execute("u1", p.operation_id, "x");
  assert.equal(r.status, "submitted");
  t += 120_000;
  const s: any = await trades.status("u1", p.operation_id);
  assert.equal(s.status, "failed");
});

const signedOf = (w: World, i = 0) => { const s = w.published[i].signed_datas[0]; return { s, msg: JSON.parse(s.payload.message) }; };

test("trade deliver_to wallet: token_diff and ft_withdraw of exactly the bought amount in ONE signed message", async () => {
  const w = world();
  const { trades, init } = setup(w);
  const a = await init("u1");
  const p: any = await trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE, deliver_to: "wallet" });
  assert.equal(p.deliver_to.wallet, a.accountId); assert.equal(p.storage_deposit, undefined);
  const r: any = await trades.execute("u1", p.operation_id, "swap to wallet");
  assert.equal(r.status, "confirmed"); assert.equal(r.deliver_to, "wallet");
  const { msg } = signedOf(w);
  assert.equal(w.published[0].quote_hashes[0], "q2");
  assert.deepEqual(msg.intents, [
    { intent: "token_diff", diff: { [WNEAR]: `-${ONE}`, [USDC]: "3727723" } },
    { intent: "ft_withdraw", token: "usdc.near", receiver_id: a.accountId, amount: "3727723", min_gas: "17050000000000" },
  ]);
});

test("trade deliver_to wallet: NEAR out arrives natively; non-NEAR-chain assets are refused; storage is paid from intents wNEAR or refused", async () => {
  const w = world(); w.balance[USDC] = "5000000";
  const { trades, init } = setup(w);
  const a = await init("u1");
  const p: any = await trades.prepare("u1", { token_in: "USDC@near", token_out: "NEAR", amount_in: "5000000", deliver_to: "wallet" });
  assert.equal(p.buy.symbol, "NEAR (native)");
  await trades.execute("u1", p.operation_id, "x");
  assert.deepEqual(signedOf(w).msg.intents[1], { intent: "native_withdraw", receiver_id: a.accountId, amount: "3727723" });
  await assert.rejects(trades.prepare("u1", { token_in: "NEAR", token_out: "SOL@sol", amount_in: ONE, deliver_to: "wallet" }), /not a NEAR-chain token/);
  w.registered = false;
  await assert.rejects(trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE, deliver_to: "wallet" }), /not registered on USDC.*holds too little/);
  w.balance[WNEAR] = (2n * 10n ** 24n).toString();
  const p2: any = await trades.prepare("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE, deliver_to: "wallet" });
  assert.equal(p2.storage_deposit.near, "0.00125");
  await trades.execute("u1", p2.operation_id, "x");
  assert.equal(signedOf(w, 1).msg.intents[1].storage_deposit, "1250000000000000000000");
});

test("withdraw: NEAR leaves intents as native NEAR via ONE relayed native_withdraw intent with no quote; nothing needs wallet gas", async () => {
  const w = world();
  const { trades, ops, init } = setup(w);
  const a = await init("u1");
  const half = (5n * 10n ** 23n).toString();
  const p: any = await trades.prepareWithdraw("u1", { asset: "NEAR", amount: half });
  assert.equal(p.kind, "intents_withdraw"); assert.equal(p.withdraw.symbol, "NEAR (native)");
  await assert.rejects(trades.execute("u1", p.operation_id, "x", "trade"), /not an intents_trade/);
  const r: any = await trades.execute("u1", p.operation_id, "refill gas", "withdraw");
  assert.equal(r.status, "confirmed"); assert.equal(r.kind, "intents_withdraw"); assert.equal(r.withdrawn, half);
  const { s, msg } = signedOf(w);
  assert.deepEqual(w.published[0].quote_hashes, []);
  assert.deepEqual(msg.intents, [{ intent: "native_withdraw", receiver_id: a.accountId, amount: half }]);
  const hash = nep413Prehash({ message: s.payload.message, nonce: Buffer.from(s.payload.nonce, "base64"), recipient: "intents.near" });
  assert.ok(verifyEd25519(publicKeyBytes(a.publicKey), hash, baseDecode(s.signature.slice(8))));
  assert.equal(ops.get(p.operation_id)!.actions.length, 0);
  await assert.rejects(trades.prepareWithdraw("u1", { asset: "NEAR", amount: "2" + ONE }), /intents balance holds/);
});

test("withdraw: a withdrawal must simulate cleanly (no invariant allowance) and ft_withdraw pays storage from intents wNEAR when needed", async () => {
  const w = world(); w.balance[USDC] = "5000000"; w.registered = false;
  const { trades, init } = setup(w);
  const a = await init("u1");
  const p: any = await trades.prepareWithdraw("u1", { asset: "USDC@near", amount: "5000000" });
  assert.equal(p.storage_deposit.near, "0.00125");
  w.simError = "wasm execution failed with error: GuestPanic { panic_msg: \"invariant violated\" }";
  await assert.rejects(trades.execute("u1", p.operation_id, "x", "withdraw"), /rejected the signed intent in simulation/);
  assert.equal(w.published.length, 0);
  delete w.simError;
  const p2: any = await trades.prepareWithdraw("u1", { asset: "USDC@near", amount: "5000000" });
  await trades.execute("u1", p2.operation_id, "x", "withdraw");
  assert.deepEqual(signedOf(w).msg.intents, [{ intent: "ft_withdraw", token: "usdc.near", receiver_id: a.accountId, amount: "5000000", storage_deposit: "1250000000000000000000", min_gas: "17050000000000" }]);
  await assert.rejects(trades.prepareWithdraw("u1", { asset: "SOL@sol", amount: "1" }), /not a NEAR-chain token/);
});

test("1Click from the intents balance: ONE signed transfer intent to the deposit address, no quote, 1Click notified with the settlement hash", async () => {
  const w = world();
  const { trades, init } = setup(w);
  const a = await init("u1");
  const p: any = await trades.prepareOneClick("u1", { origin_asset: "NEAR", destination_asset: "SOL@sol", amount: ONE, deliver_to: "intents" });
  assert.equal(p.kind, "intents_swap");
  assert.deepEqual(p.signed_intent, { intent: "transfer", receiver_id: "d".repeat(64), tokens: { [WNEAR]: ONE } });
  await assert.rejects(trades.execute("u1", p.operation_id, "x", "withdraw"), /not an intents_withdraw/);
  const r: any = await trades.execute("u1", p.operation_id, "swap via 1Click", "oneclick");
  assert.equal(r.status, "confirmed"); assert.equal(r.kind, "intents_swap"); assert.equal(r.oneclick.swap_status, "PROCESSING");
  assert.deepEqual(w.published[0].quote_hashes, []);
  assert.deepEqual(signedOf(w).msg.intents, [p.signed_intent]);
  assert.deepEqual(w.submitted, ["SettleTx111", "d".repeat(64), a.accountId]);
  w.oneclickDeadlineMs = 60_000;
  const p2: any = await trades.prepareOneClick("u1", { origin_asset: "NEAR", destination_asset: "SOL@sol", amount: ONE, deliver_to: "intents" });
  await assert.rejects(trades.execute("u1", p2.operation_id, "x", "oneclick"), /deadline is too close/);
  assert.equal(w.published.length, 1);
});

test("binding survives Postgres jsonb key reordering of the stored plan", async () => {
  const w = world();
  const { trades, ops, init } = setup(w);
  await init("u1");
  const p: any = await trades.prepareWithdraw("u1", { asset: "NEAR", amount: "1000" });
  const op = ops.get(p.operation_id)!;
  const reorder = (x: any): any => Array.isArray(x) ? x.map(reorder) : x && typeof x === "object" ? Object.fromEntries(Object.entries(x).reverse().map(([k, v]) => [k, reorder(v)])) : x;
  (op as any).plan = reorder(op.plan);
  const r: any = await trades.execute("u1", p.operation_id, "x", "withdraw");
  assert.equal(r.status, "confirmed");
});

test("auto route: relay when it is within 0.5% of 1Click, 1Click when it pays clearly more or the relay has no quote", async () => {
  const w = world();
  const { trades, init } = setup(w);
  await init("u1");
  const args = { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE };
  w.oneclickOut = "3740000"; // relay best 3727723 is 0.33% lower: relay wins on speed
  const a: any = await trades.prepareAuto("u1", args);
  assert.equal(a.route.chosen, "solver_relay"); assert.equal(a.kind, "intents_trade"); assert.deepEqual(a.route.quotes, { solver_relay_out: "3727723", oneclick_out: "3740000" });
  const r: any = await trades.execute("u1", a.operation_id, "x");
  assert.equal(r.status, "confirmed"); assert.deepEqual(w.published[0].quote_hashes, ["q2"]);
  w.oneclickOut = "3760000"; // 0.86% better: 1Click
  const b: any = await trades.prepareAuto("u1", args);
  assert.equal(b.route.chosen, "1click"); assert.equal(b.kind, "intents_swap"); assert.equal(b.signed_intent.intent, "transfer");
  w.quotes = []; w.oneclickOut = "3700000";
  const c: any = await trades.prepareAuto("u1", args);
  assert.equal(c.route.chosen, "1click"); assert.match(c.route.why, /no quote/);
  delete w.oneclickOut;
  await assert.rejects(trades.prepareAuto("u1", args), /neither the Solver Relay nor 1Click/);
  w.quotes = [{ amount_out: "3727723", hash: "q2" }];
  const d: any = await trades.prepareAuto("u1", args);
  assert.equal(d.route.chosen, "solver_relay"); assert.match(d.route.why, /1Click gave no quote/);
});

test("auto route: wallet delivery through 1Click is refused when the wallet is not registered on the token", async () => {
  const w = world(); w.quotes = []; w.oneclickOut = "3700000"; w.registered = false;
  const { trades, init } = setup(w);
  await init("u1");
  await assert.rejects(trades.prepareAuto("u1", { token_in: "NEAR", token_out: "USDC@near", amount_in: ONE, deliver_to: "wallet" }), /only 1Click quotes this pair.*deliver_to intents/);
});
