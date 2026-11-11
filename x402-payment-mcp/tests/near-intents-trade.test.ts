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
const WNEAR = "nep141:wrap.near", USDC = "nep141:usdc.near";
const TOKENS: Record<string, { assetId: string; symbol: string; decimals: number }> = { NEAR: { assetId: WNEAR, symbol: "wNEAR", decimals: 24 }, "USDC@near": { assetId: USDC, symbol: "USDC", decimals: 6 } };

type World = { balance: Record<string, string>; quotes: { amount_out: string; hash: string }[]; published: any[]; relayStatus: string; simError?: string; usedNonces: Set<string>; publishStatus?: string };

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
    throw new Error(`unexpected ${b.method} ${b.params?.method_name}`);
  }) as typeof fetch);
  const relay = new SolverRelayClient("https://relay.example", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body)), p = b.params[0];
    const reply = (result: unknown) => new Response(JSON.stringify({ jsonrpc: "2.0", id: 1, result }));
    if (b.method === "quote") return reply(w.quotes.map(q => ({ quote_hash: q.hash, defuse_asset_identifier_in: p.defuse_asset_identifier_in, defuse_asset_identifier_out: p.defuse_asset_identifier_out, amount_in: p.exact_amount_in, amount_out: q.amount_out, expiration_time: new Date(now() + 60_000).toISOString() })));
    if (b.method === "publish_intent") { w.published.push(p); return reply({ status: w.publishStatus ?? "OK", intent_hash: "x" }); }
    if (b.method === "get_status") return reply({ intent_hash: p.intent_hash, status: w.relayStatus, data: { hash: "SettleTx111" } });
    throw new Error("unexpected relay method");
  }) as typeof fetch);
  const accounts = new NearAccountService(config, store, rpc);
  const intents = { asset: async (ref: string) => TOKENS[ref]!, intentsBalanceOf: async (_a: string, t: string) => BigInt(w.balance[t] ?? "0") } as any;
  const trades = new IntentsTrades(accounts, store, intents, relay, now);
  return { trades, ops, init: async (u: string) => { const a = await accounts.account(u); pk = a.publicKey; return a; } };
}
const world = (): World => ({ balance: { [WNEAR]: (10n ** 24n).toString() }, quotes: [{ amount_out: "3700000", hash: "q1" }, { amount_out: "3727723", hash: "q2" }], published: [], relayStatus: "SETTLED", usedNonces: new Set() });
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
  const { quote_hashes, signed_data: s } = w.published[0];
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
