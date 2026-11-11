import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import test from "node:test";
import { decodeSignedTransaction } from "@near-js/transactions";
import { baseEncode } from "@near-js/utils";
import { NearAccountService, publicKeyBytes } from "../src/near/account.js";
import { loadNearConfig } from "../src/near/config.js";
import { verifyEd25519 } from "../src/near/keys.js";
import { NearOperations, publicNearError } from "../src/near/operations.js";
import { NearRpc } from "../src/near/rpc.js";
import { memoryStore } from "./near-fakes.js";
import { transactionDigest } from "../src/near/transaction.js";

const KEY = randomBytes(32).toString("base64");
const config = loadNearConfig({ NEAR_RPC_URL: "https://rpc.example", NEAR_KEY_ENCRYPTION_KEY: KEY })!;
const NEAR = 10n ** 24n;

type Chain = { balance: bigint; nonce: number; sent: string[]; known: Set<string>; failSend?: string; dropFirst?: boolean; missing?: Set<string> };
function chainRpc(chain: Chain, accountKey: () => string | undefined) {
  return new NearRpc("https://rpc.example", "mainnet", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body));
    const ok = (result: unknown) => new Response(JSON.stringify({ result }));
    const err = (name: string) => new Response(JSON.stringify({ error: { name: "HANDLER_ERROR", cause: { name } } }));
    if (b.method === "status") return ok({ chain_id: "mainnet" });
    if (b.method === "gas_price") return ok({ gas_price: "100000000" });
    if (b.method === "block") return ok({ header: { hash: baseEncode(new Uint8Array(32).fill(3)), height: 10 } });
    if (b.method === "EXPERIMENTAL_protocol_config") return ok({ runtime_config: { min_gas_purchase_price: "1000000000", account_creation_charge: "7000000000000000000000", transaction_costs: { action_creation_config: { create_account_cost: { execution: 7200000000000, send_not_sir: 500000000000 } } } } });
    if (b.method === "query" && b.params.request_type === "view_account" && chain.missing?.has(b.params.account_id)) return err("UNKNOWN_ACCOUNT");
    if (b.method === "query" && b.params.request_type === "view_account") return chain.balance ? ok({ amount: chain.balance.toString(), locked: "0", storage_usage: 100, code_hash: "1", block_height: 1, block_hash: "x" }) : err("UNKNOWN_ACCOUNT");
    if (b.method === "query" && b.params.request_type === "view_access_key") return b.params.public_key === accountKey() && chain.balance ? ok({ nonce: chain.nonce, permission: "FullAccess", block_hash: "x", block_height: 1 }) : err("UNKNOWN_ACCESS_KEY");
    if (b.method === "send_tx") {
      if (chain.failSend) return err(chain.failSend);
      const signed = decodeSignedTransaction(Buffer.from(b.params.signed_tx_base64, "base64"));
      const digest = transactionDigest(signed.transaction);
      const sig = Uint8Array.from((signed.signature as any).ed25519Signature.data);
      assert.ok(verifyEd25519(publicKeyBytes(accountKey()!), digest, sig), "chain rejects bad signatures");
      const hash = baseEncode(digest);
      chain.sent.push(hash);
      if (chain.dropFirst) { chain.dropFirst = false; return err("TIMEOUT_ERROR"); }
      if (!chain.known.has(hash)) { assert.equal(signed.transaction.nonce, BigInt(chain.nonce + 1)); chain.nonce++; chain.known.add(hash); }
      return ok(outcome(hash));
    }
    if (b.method === "EXPERIMENTAL_tx_status") return chain.known.has(b.params.tx_hash) ? ok(outcome(b.params.tx_hash)) : err("UNKNOWN_TRANSACTION");
    throw new Error(`unexpected ${b.method}`);
  }) as typeof fetch);
}
const outcome = (hash: string) => ({ final_execution_status: "FINAL", status: { SuccessValue: "" }, transaction: { hash }, transaction_outcome: { id: hash, outcome: { logs: [], receipt_ids: [], gas_burnt: 1, tokens_burnt: "100", executor_id: "a", status: { SuccessValue: "" } } }, receipts_outcome: [] });

function setup(chain: Chain) {
  const { store, ops } = memoryStore();
  let pk: string | undefined;
  const accounts = new NearAccountService(config, store, chainRpc(chain, () => pk));
  const operations = new NearOperations(accounts, store);
  return { operations, accounts, ops, init: async (u: string) => { pk = (await accounts.account(u)).publicKey; } };
}
const transfer = { receiver_id: "bob.near", actions: [{ type: "transfer" as const, amount_yocto: (NEAR / 10n).toString() }] };

test("execute: signs the previewed transfer once with the next nonce and records the confirmed outcome", async () => {
  const chain: Chain = { balance: 2n * NEAR, nonce: 7, sent: [], known: new Set() };
  const { operations, init } = setup(chain);
  await init("u");
  const preview = await operations.prepare("u", transfer);
  assert.equal(preview.total_attached_near, "0.1");
  assert.equal(preview.actions[0]!.type, "transfer");
  const r = await operations.execute("u", preview.operation_id, "pay bob");
  assert.equal(r.status, "confirmed");
  assert.equal(chain.nonce, 8);
  await assert.rejects(operations.execute("u", preview.operation_id, "again"), /already consumed/);
  assert.equal(chain.sent.length, 1);
  assert.equal((await operations.status("u", preview.operation_id)).status, "confirmed");
  await assert.rejects(operations.status("other", preview.operation_id), /not found/);
});

test("prepare: inactive account and insufficient balance are refused before any preview is stored", async () => {
  const inactive = setup({ balance: 0n, nonce: 0, sent: [], known: new Set() });
  await assert.rejects(inactive.operations.prepare("u", transfer), /not active yet/);
  const poor = setup({ balance: NEAR / 20n, nonce: 0, sent: [], known: new Set() });
  await poor.init("u");
  await assert.rejects(poor.operations.prepare("u", transfer), /insufficient NEAR/);
  assert.equal(poor.ops.size, 0);
});

test("prepare: a missing implicit receiver shows the account creation fee; a missing named receiver is refused", async () => {
  const implicit = "2de1b2769ad4ea889ebc32c7168a12ec1e437f52aa49a26cac86494cd7e8718e";
  const chain: Chain = { balance: NEAR / 20n, nonce: 0, sent: [], known: new Set(), missing: new Set([implicit, "nobody.near"]) };
  const { operations, init, ops } = setup(chain);
  await init("u");
  const p = await operations.prepare("u", { receiver_id: implicit, actions: [{ type: "transfer", amount_yocto: (NEAR / 1000n).toString() }] }) as any;
  assert.equal(p.creates_receiver_account, true);
  assert.equal(p.account_creation_fee_near, "0.007");
  // 0.007 NEAR charge + (5 + 7.7) TGas at the 1e8 gas price.
  assert.equal(p.max_network_fee_yocto, (7n * 10n ** 21n + 12_700_000_000_000n * 100_000_000n).toString());
  assert.match(p.warnings.join(" "), /does not exist yet/);
  await assert.rejects(operations.prepare("u", { receiver_id: "nobody.near", actions: [{ type: "transfer", amount_yocto: "1" }] }), /does not exist/);
  await assert.rejects(operations.prepare("u", { receiver_id: implicit, actions: [{ type: "function_call", method_name: "x", deposit_yocto: "0" }] }), /does not exist/);
  // Gas is prepaid at the 1e9 minimum purchase price: 300 TGas needs 0.3 NEAR up front even though the fee bound at 1e8 is 0.03.
  await assert.rejects(operations.prepare("u", { receiver_id: "wrap.near", actions: [{ type: "function_call", method_name: "x", deposit_yocto: "0", gas: "295000000000000" }] }), /up front/);
  assert.equal(ops.size, 1);
});

test("unknown broadcast blocks new executions; status re-sends the identical bytes, which execute at most once", async () => {
  const chain: Chain = { balance: 2n * NEAR, nonce: 1, sent: [], known: new Set(), dropFirst: true };
  const { operations, init } = setup(chain);
  await init("u");
  const a = await operations.prepare("u", transfer);
  const b = await operations.prepare("u", transfer);
  const r = await operations.execute("u", a.operation_id, "first");
  assert.equal(r.status, "unknown");
  await assert.rejects(operations.execute("u", b.operation_id, "second"), /unresolved NEAR operation/);
  const s = await operations.status("u", a.operation_id);
  assert.equal(s.status, "confirmed");
  assert.equal(chain.sent[0], chain.sent[1], "the same transaction hash was re-sent");
  assert.equal(chain.nonce, 2);
  assert.equal((await operations.execute("u", b.operation_id, "second")).status, "confirmed");
});

test("definitive RPC rejection marks the operation failed and frees the account", async () => {
  const chain: Chain = { balance: 2n * NEAR, nonce: 1, sent: [], known: new Set(), failSend: "INVALID_TRANSACTION" };
  const { operations, init, ops } = setup(chain);
  await init("u");
  const a = await operations.prepare("u", transfer);
  await assert.rejects(operations.execute("u", a.operation_id, "x"), /rejected the transaction/);
  assert.equal(ops.get(a.operation_id)!.status, "failed");
  delete chain.failSend;
  const b = await operations.prepare("u", transfer);
  assert.equal((await operations.execute("u", b.operation_id, "x")).status, "confirmed");
});

test("public errors withhold provider details", () => {
  assert.match(publicNearError(new Error("connect ECONNREFUSED https://rpc.example/key=secret")).message, /details are withheld/);
  assert.match(publicNearError(new Error("insufficient NEAR: needs 1")).message, /insufficient NEAR/);
});
