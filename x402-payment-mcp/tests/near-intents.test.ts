import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import test from "node:test";
import { decodeSignedTransaction } from "@near-js/transactions";
import { baseEncode } from "@near-js/utils";
import { NearAccountService } from "../src/near/account.js";
import { loadNearConfig } from "../src/near/config.js";
import { NearIntents, OneClickClient } from "../src/near/intents.js";
import { NearOperations } from "../src/near/operations.js";
import { NearRpc } from "../src/near/rpc.js";
import { transactionDigest } from "../src/near/transaction.js";
import { memoryStore } from "./near-fakes.js";

const config = loadNearConfig({ NEAR_RPC_URL: "https://rpc.example", NEAR_KEY_ENCRYPTION_KEY: randomBytes(32).toString("base64") })!;
const NEAR = 10n ** 24n;
const EVM = "0xF9B83E2b759D9C92461a0fb569C1CC2deEDC15b9";
const DEPOSIT = "ae".repeat(32);
const AMOUNT = (2n * 10n ** 22n).toString();
const TOKENS = [
  { assetId: "nep141:wrap.near", decimals: 24, blockchain: "near", symbol: "wNEAR", price: 3.6, contractAddress: "wrap.near" },
  { assetId: "nep141:usdc.near", decimals: 6, blockchain: "near", symbol: "USDC", contractAddress: "usdc.near" },
  { assetId: "nep141:base.omft.near", decimals: 18, blockchain: "base", symbol: "ETH" },
  { assetId: "nep141:sol.omft.near", decimals: 9, blockchain: "sol", symbol: "SOL" },
];

type World = { mt: Record<string, string>; ft: Record<string, string>; registered: Set<string>; sent: { method: string; args: any; deposit: string }[][]; quotes: any[]; submits: any[]; nonce: number; tamper?: (q: any) => void; swapStatus?: any };

function setup(w: World, now = () => Date.now()) {
  const { store, ops } = memoryStore();
  let pk: string | undefined;
  const rpc = new NearRpc("https://rpc.example", "mainnet", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body));
    const ok = (result: unknown) => new Response(JSON.stringify({ result }));
    const err = (name: string) => new Response(JSON.stringify({ error: { name: "HANDLER_ERROR", cause: { name } } }));
    if (b.method === "status") return ok({ chain_id: "mainnet" });
    if (b.method === "gas_price") return ok({ gas_price: "100000000" });
    if (b.method === "block") return ok({ header: { hash: baseEncode(new Uint8Array(32).fill(3)), height: 10 } });
    if (b.method === "EXPERIMENTAL_protocol_config") return err("UNKNOWN");
    if (b.method === "query" && b.params.request_type === "view_account") return ok({ amount: (NEAR / 5n).toString(), locked: "0", storage_usage: 100, code_hash: "1", block_height: 1, block_hash: "x" });
    if (b.method === "query" && b.params.request_type === "view_access_key") return b.params.public_key === pk ? ok({ nonce: w.nonce, permission: "FullAccess", block_hash: "x", block_height: 1 }) : err("UNKNOWN_ACCESS_KEY");
    if (b.method === "query" && b.params.request_type === "call_function") {
      const args = JSON.parse(Buffer.from(b.params.args_base64, "base64").toString());
      const mts = Object.entries(w.mt).filter(([k]) => k.startsWith(`${args.account_id}|`));
      const r = b.params.account_id === "intents.near" ? ({
        is_auth_by_predecessor_id_enabled: true,
        mt_balance_of: w.mt[`${args.account_id}|${args.token_id}`] ?? "0",
        mt_tokens_for_owner: mts.map(([k]) => ({ token_id: k.split("|")[1] })),
        mt_batch_balance_of: (args.token_ids ?? []).map((t: string) => w.mt[`${args.account_id}|${t}`] ?? "0"),
      } as Record<string, unknown>)[b.params.method_name]
        : b.params.method_name === "ft_balance_of" ? (w.ft[`${b.params.account_id}:${args.account_id}`] ?? "0")
        : b.params.method_name === "storage_balance_of" ? (w.registered.has(`${b.params.account_id}:${args.account_id}`) ? { total: "1250000000000000000000", available: "0" } : null)
        : b.params.method_name === "storage_balance_bounds" ? { min: "1250000000000000000000", max: "1250000000000000000000" } : null;
      return ok({ result: [...Buffer.from(JSON.stringify(r))], logs: [], block_height: 1 });
    }
    if (b.method === "send_tx") {
      const signed = decodeSignedTransaction(Buffer.from(b.params.signed_tx_base64, "base64"));
      w.nonce++;
      w.sent.push(signed.transaction.actions.map((a: any) => ({ method: a.functionCall.methodName, args: JSON.parse(Buffer.from(a.functionCall.args).toString()), deposit: a.functionCall.deposit.toString() })));
      const hash = baseEncode(transactionDigest(signed.transaction));
      return ok({ final_execution_status: "FINAL", status: { SuccessValue: "" }, transaction: { hash }, transaction_outcome: { id: hash, outcome: { logs: [], receipt_ids: [], gas_burnt: 1, tokens_burnt: "100", executor_id: "a", status: { SuccessValue: "" } } }, receipts_outcome: [] });
    }
    throw new Error(`unexpected ${b.method}`);
  }) as typeof fetch);
  const oneclick = new OneClickClient("https://1click.example", (async (url: string, init: RequestInit) => {
    const path = new URL(url).pathname;
    if (path === "/v0/tokens") return new Response(JSON.stringify(TOKENS));
    if (path === "/v0/quote") {
      const req = JSON.parse(String(init.body));
      w.quotes.push(req);
      const q = { quote: { amountIn: req.amount, amountOut: "34756132164931", minAmountOut: "34408570843281", depositAddress: DEPOSIT, timeEstimate: 24, deadline: req.deadline }, quoteRequest: { ...req, appFees: [{ fee: 20 }] }, correlationId: "c-1" };
      w.tamper?.(q);
      return new Response(JSON.stringify(q));
    }
    if (path === "/v0/deposit/submit") { w.submits.push(JSON.parse(String(init.body))); return new Response("{}"); }
    if (path === "/v0/status") return new Response(JSON.stringify(w.swapStatus ?? { status: "PENDING_DEPOSIT", swapDetails: {} }));
    return new Response("{}", { status: 404 });
  }) as typeof fetch);
  const accounts = new NearAccountService(config, store, rpc);
  const operations = new NearOperations(accounts, store);
  const cs = { fromAddress: async () => EVM } as any;
  const intents = new NearIntents(accounts, operations, store, cs, oneclick, now);
  return { intents, operations, ops, init: async (u: string) => { pk = (await accounts.account(u)).publicKey; return (await accounts.account(u)).accountId; } };
}
const world = (): World => ({ mt: {}, ft: {}, registered: new Set(), sent: [], quotes: [], submits: [], nonce: 5 });

test("intents prepare: NEAR -> ETH@base wraps, registers storage and transfers to the deposit address; recipient is the derived EVM address", async () => {
  const w = world();
  const { intents, ops, init } = setup(w);
  const self = await init("u1");
  const p: any = await intents.prepare("u1", { origin_asset: "NEAR", destination_asset: "ETH@base", amount: AMOUNT });
  const q = w.quotes[0];
  assert.equal(q.recipient, EVM); assert.equal(q.refundTo, self); assert.equal(q.originAsset, "nep141:wrap.near"); assert.equal(q.destinationAsset, "nep141:base.omft.near");
  assert.equal(q.dry, false); assert.equal(q.slippageTolerance, 100); assert.equal(q.depositType, "ORIGIN_CHAIN"); assert.equal(q.refundType, "ORIGIN_CHAIN"); assert.equal(q.recipientType, "DESTINATION_CHAIN");
  assert.equal(p.kind, "intents_swap"); assert.equal(p.receiver_id, "wrap.near");
  assert.equal(p.intents.recipient, EVM); assert.equal(p.intents.deposit_address, DEPOSIT); assert.equal(p.intents.destination.minimum_formatted, "0.000034408570843281"); assert.equal(p.intents.origin.wraps_near, "0.02");
  const op = [...ops.values()][0]!;
  const actions = op.actions.map((a: any) => [a.method, JSON.parse(Buffer.from(a.args_base64, "base64").toString()), a.deposit]);
  assert.deepEqual(actions, [
    ["storage_deposit", { account_id: self, registration_only: true }, "1250000000000000000000"],
    ["near_deposit", {}, AMOUNT],
    ["storage_deposit", { account_id: DEPOSIT, registration_only: true }, "1250000000000000000000"],
    ["ft_transfer", { receiver_id: DEPOSIT, amount: AMOUNT }, "1"],
  ]);
});

test("intents prepare: skips wrapping and registration that already exist", async () => {
  const w = world();
  const { intents, ops, init } = setup(w);
  const self = await init("u1");
  w.ft[`wrap.near:${self}`] = AMOUNT; w.registered.add(`wrap.near:${self}`); w.registered.add(`wrap.near:${DEPOSIT}`);
  await intents.prepare("u1", { origin_asset: "nep141:wrap.near", destination_asset: "nep141:base.omft.near", amount: AMOUNT });
  assert.deepEqual([...ops.values()][0]!.actions.map((a: any) => a.method), ["ft_transfer"]);
});

test("intents prepare: refuses a quote that does not echo the request, or a foreign deposit address", async () => {
  for (const tamper of [(q: any) => { q.quoteRequest.recipient = "0x000000000000000000000000000000000000dEaD"; }, (q: any) => { q.quote.depositAddress = "evil.near"; }, (q: any) => { q.quote.amountIn = "1"; }, (q: any) => { q.quote.minAmountOut = "99999999999999999"; }]) {
    const w = world(); w.tamper = tamper;
    const { intents, ops, init } = setup(w);
    await init("u1");
    await assert.rejects(intents.prepare("u1", { origin_asset: "NEAR", destination_asset: "ETH@base", amount: AMOUNT }), /intents: 1Click/);
    assert.equal(ops.size, 0);
  }
});

test("intents prepare: only NEAR-chain origins; non-wNEAR tokens need the balance; other chains need a recipient", async () => {
  const w = world();
  const { intents, init } = setup(w);
  await init("u1");
  await assert.rejects(intents.prepare("u1", { origin_asset: "ETH@base", destination_asset: "USDC@near", amount: "1000" }), /origin_asset must be a NEAR-chain/);
  await assert.rejects(intents.prepare("u1", { origin_asset: "USDC@near", destination_asset: "ETH@base", amount: "1000" }), /holds 0 of USDC/);
  await assert.rejects(intents.prepare("u1", { origin_asset: "NEAR", destination_asset: "SOL@sol", amount: AMOUNT }), /pass recipient for delivery on sol/);
  assert.equal(w.quotes.length, 0);
});

test("intents execute: signs once, submits the deposit, and only the intents tool can execute it", async () => {
  const w = world();
  const { intents, operations, init } = setup(w);
  await init("u1");
  const p: any = await intents.prepare("u1", { origin_asset: "NEAR", destination_asset: "ETH@base", amount: AMOUNT });
  await assert.rejects(operations.execute("u1", p.operation_id, "wrong tool"), /operation type does not match/);
  const r: any = await intents.execute("u1", p.operation_id, "swap NEAR to ETH on Base");
  assert.equal(r.status, "confirmed"); assert.equal(w.sent.length, 1);
  assert.deepEqual(w.sent[0]!.map(a => a.method), ["storage_deposit", "near_deposit", "storage_deposit", "ft_transfer"]);
  assert.deepEqual(w.submits, [{ txHash: r.transaction_hash, depositAddress: DEPOSIT, nearSenderAccount: (await (intents as any).accounts.account("u1")).accountId }]);
  await assert.rejects(intents.execute("u1", p.operation_id, "again"), /consumed/);
  w.swapStatus = { status: "SUCCESS", swapDetails: { amountOut: "34756132164931", destinationChainTxHashes: [{ hash: "0xabc", explorerUrl: "https://basescan.org/tx/0xabc" }] } };
  const s: any = await intents.status("u1", p.operation_id);
  assert.equal(s.swap_status, "SUCCESS"); assert.equal(s.amount_out, "34756132164931"); assert.equal(s.destination_tx[0].hash, "0xabc");
});

test("intents execute: refuses before signing when the deposit deadline is near", async () => {
  const w = world();
  let t = Date.now();
  const { intents, init } = setup(w, () => t);
  await init("u1");
  const p: any = await intents.prepare("u1", { origin_asset: "NEAR", destination_asset: "ETH@base", amount: AMOUNT });
  t += 29 * 60_000;
  await assert.rejects(intents.execute("u1", p.operation_id, "late"), /deadline is too close/);
  assert.equal(w.sent.length, 0);
});

const decode = (op: any) => op.actions.map((a: any) => [a.method, JSON.parse(Buffer.from(a.args_base64, "base64").toString()), a.deposit]);

test("intents prepare: deliver_to intents credits this account's intents balance (NEAR -> SOL without a Solana address)", async () => {
  const w = world();
  const { intents, ops, init } = setup(w);
  const self = await init("u1");
  const p: any = await intents.prepare("u1", { origin_asset: "NEAR", destination_asset: "SOL@sol", amount: AMOUNT, deliver_to: "intents" });
  assert.equal(w.quotes[0].recipientType, "INTENTS"); assert.equal(w.quotes[0].recipient, self); assert.equal(w.quotes[0].depositType, "ORIGIN_CHAIN");
  assert.equal(p.intents.deliver_to, "intents"); assert.equal(p.intents.recipient, self);
  assert.deepEqual(decode([...ops.values()][0]).at(-1), ["ft_transfer", { receiver_id: DEPOSIT, amount: AMOUNT }, "1"]);
  await assert.rejects(intents.prepare("u1", { origin_asset: "NEAR", destination_asset: "SOL@sol", amount: AMOUNT, deliver_to: "intents", recipient: "SoLAddress1111111" }), /do not pass recipient/);
});

test("intents prepare: pay_from intents spends the intents balance with one mt_transfer on intents.near; refunds stay in intents", async () => {
  const w = world();
  const { intents, ops, init } = setup(w);
  const self = await init("u1");
  await assert.rejects(intents.prepare("u1", { origin_asset: "SOL@sol", destination_asset: "USDC@near", amount: "1000000", pay_from: "intents" }), /intents balance holds 0 of SOL/);
  assert.equal(w.quotes.length, 0);
  w.mt[`${self}|nep141:sol.omft.near`] = "5000000";
  const p: any = await intents.prepare("u1", { origin_asset: "SOL@sol", destination_asset: "USDC@near", amount: "1000000", pay_from: "intents" });
  const q = w.quotes[0];
  assert.equal(q.depositType, "INTENTS"); assert.equal(q.refundType, "INTENTS"); assert.equal(q.refundTo, self); assert.equal(q.recipient, self); assert.equal(q.recipientType, "DESTINATION_CHAIN");
  assert.equal(p.receiver_id, "intents.near");
  assert.deepEqual(decode([...ops.values()][0]), [["mt_transfer", { receiver_id: DEPOSIT, token_id: "nep141:sol.omft.near", amount: "1000000" }, "1"]]);
});

test("intents balances, deposit and withdraw", async () => {
  const w = world();
  const { intents, ops, init } = setup(w);
  const self = await init("u1");
  w.mt[`${self}|nep141:sol.omft.near`] = "865000"; w.mt[`${self}|nep141:wrap.near`] = "0";
  const b: any = await intents.balances("u1");
  assert.deepEqual(b.balances.map((x: any) => [x.symbol, x.formatted]), [["SOL", "0.000865"]]);

  const d: any = await intents.prepareDeposit("u1", { asset: "NEAR", amount: AMOUNT });
  assert.equal(d.receiver_id, "wrap.near"); assert.equal(d.kind, "near_tx");
  assert.deepEqual(decode([...ops.values()].at(-1)).map((a: any) => a[0]), ["storage_deposit", "near_deposit", "ft_transfer_call"]);
  assert.deepEqual(decode([...ops.values()].at(-1)).at(-1), ["ft_transfer_call", { receiver_id: "intents.near", amount: AMOUNT, msg: "" }, "1"]);

  await assert.rejects(intents.prepareWithdraw("u1", { asset: "NEAR", amount: AMOUNT }), /intents balance holds 0/);
  w.mt[`${self}|nep141:wrap.near`] = AMOUNT;
  await assert.rejects(intents.prepareWithdraw("u1", { asset: "NEAR", amount: AMOUNT }), /not registered on wrap.near/);
  w.registered.add(`wrap.near:${self}`);
  const r: any = await intents.prepareWithdraw("u1", { asset: "NEAR", amount: AMOUNT });
  assert.equal(r.receiver_id, "intents.near");
  assert.deepEqual(decode([...ops.values()].at(-1)), [["ft_withdraw", { token: "wrap.near", receiver_id: self, amount: AMOUNT }, "1"]]);
  await assert.rejects(intents.prepareWithdraw("u1", { asset: "SOL@sol", amount: "1" }), /NEAR-chain NEP-141/);
});

test("intents quoteFromEvm: ORIGIN_CHAIN quote refunds to the EVM address and needs an EVM deposit address; tampering is refused", async () => {
  const EVM_DEP = "0x3333333333333333333333333333333333333333";
  const w = world();
  w.tamper = q => { q.quote.depositAddress = EVM_DEP; };
  const { intents, init } = setup(w);
  const self = await init("u1");
  const eth = await intents.asset("ETH@base", "o"), wnear = await intents.asset("NEAR", "d");
  const r: any = await intents.quoteFromEvm("u1", { origin: eth, dest: wnear, amount: "100000000000000", deliver_to: "chain", slippage_bps: 100 });
  const req = w.quotes.at(-1);
  assert.equal(req.depositType, "ORIGIN_CHAIN"); assert.equal(req.refundType, "ORIGIN_CHAIN");
  assert.equal(req.refundTo, EVM); assert.equal(req.recipient, self); assert.equal(req.recipientType, "DESTINATION_CHAIN");
  assert.equal(r.plan.deposit_address, EVM_DEP); assert.equal(r.plan.pay_from, "evm");
  assert.match(r.description.protection, /refunds the deposit to 0xF9B8/);
  // NEAR-style deposit address or the account's own EVM address are refused
  const bad = world(); const s2 = setup(bad); await s2.init("u1");
  await assert.rejects(s2.intents.quoteFromEvm("u1", { origin: eth, dest: wnear, amount: "1", deliver_to: "chain", slippage_bps: 100 }), /unexpected EVM deposit address/);
  const own = world(); own.tamper = q => { q.quote.depositAddress = EVM; }; const s3 = setup(own); await s3.init("u1");
  await assert.rejects(s3.intents.quoteFromEvm("u1", { origin: eth, dest: wnear, amount: "1", deliver_to: "chain", slippage_bps: 100 }), /unexpected EVM deposit address/);
  const swapped = world(); swapped.tamper = q => { q.quote.depositAddress = EVM_DEP; q.quoteRequest.refundTo = "0x4444444444444444444444444444444444444444"; }; const s4 = setup(swapped); await s4.init("u1");
  await assert.rejects(s4.intents.quoteFromEvm("u1", { origin: eth, dest: wnear, amount: "1", deliver_to: "chain", slippage_bps: 100 }), /does not match the request \(refundTo\)/);
});
