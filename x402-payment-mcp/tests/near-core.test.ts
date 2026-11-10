import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, randomBytes, sign as edSign } from "node:crypto";
import test from "node:test";
import { decodeSignedTransaction } from "@near-js/transactions";
import { baseEncode } from "@near-js/utils";
import { CdpSolanaSigner, cdpNearAccountName, generateSealedKey, implicitAccountId, nearPublicKey, SealedKeySigner, verifyEd25519, type CdpSolanaApi } from "../src/near/keys.js";
import { NearRpc, summarizeOutcome } from "../src/near/rpc.js";
import { buildNearTransaction, describeNearTransaction, nearFingerprint, nearTransactionInput, normalizeNearTransaction, signNearTransaction, transactionDigest } from "../src/near/transaction.js";
import { formatNear, isValidAccountId, parseGas, parseYocto } from "../src/near/units.js";

const KEY = randomBytes(32).toString("base64");
const BLOCK = baseEncode(new Uint8Array(32).fill(7));

test("units: yocto and gas parsing are strict integers within protocol bounds", () => {
  assert.equal(parseYocto("1000000000000000000000000"), 10n ** 24n);
  assert.throws(() => parseYocto("1.5"));
  assert.throws(() => parseYocto("-1"));
  assert.throws(() => parseYocto((1n << 128n).toString()));
  assert.throws(() => parseGas("0"));
  assert.throws(() => parseGas("300000000000001"));
  assert.equal(formatNear(1500000000000000000000000n), "1.5");
  assert.equal(formatNear(1n), "0.000000000000000000000001");
  for (const id of ["alice.near", "v1.signer", "a1b2", "0x" + "a".repeat(40), "f".repeat(64)]) assert.ok(isValidAccountId(id), id);
  for (const id of ["A.near", "a", "a..near", "-a.near", "a".repeat(65), "alice.near "]) assert.ok(!isValidAccountId(id), id);
});

test("sealed key: round-trips, binds to the user by AAD and to the registered public key", async () => {
  const { publicKey, sealed } = generateSealedKey(KEY, "user-1");
  assert.equal(implicitAccountId(publicKey).length, 64);
  const signer = SealedKeySigner.open(sealed, KEY, "user-1", publicKey);
  const msg = randomBytes(32);
  assert.ok(verifyEd25519(publicKey, msg, await signer.sign(msg)));
  assert.throws(() => SealedKeySigner.open(sealed, KEY, "user-2", publicKey), "AAD binds the sealed key to its user");
  assert.throws(() => SealedKeySigner.open(sealed, randomBytes(32).toString("base64"), "user-1", publicKey));
  const other = generateSealedKey(KEY, "user-1");
  assert.throws(() => SealedKeySigner.open(sealed, KEY, "user-1", other.publicKey), /does not match/);
  assert.throws(() => generateSealedKey(undefined, "user-1"), /NEAR_KEY_ENCRYPTION_KEY/);
});

function fakeCdp(mode: "raw" | "text"): CdpSolanaApi & { calls: string[] } {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const address = baseEncode(Buffer.from(publicKey.export({ format: "jwk" }).x!, "base64url"));
  const calls: string[] = [];
  return {
    calls,
    async getOrCreateAccount() { return { address }; },
    async signMessage({ message }) {
      calls.push(message);
      const bytes = mode === "raw" ? Buffer.from(message, "base64") : Buffer.from(message, "utf8");
      return { signature: baseEncode(edSign(null, bytes, privateKey)) };
    },
  };
}

test("CDP Solana signer: accepted only when its signature verifies over the exact digest", async () => {
  const msg = randomBytes(32);
  const good = await CdpSolanaSigner.forName(fakeCdp("raw"), "near-v1-x", "base64");
  assert.ok(verifyEd25519(good.publicKey, msg, await good.sign(msg)));
  // A provider that signs the UTF-8 text of the encoded string instead of the bytes fails closed.
  const text = await CdpSolanaSigner.forName(fakeCdp("text"), "near-v1-x", "base64");
  await assert.rejects(text.sign(msg), /does not verify/);
  await assert.rejects(CdpSolanaSigner.forName(fakeCdp("raw"), "near-v1-x", "base64", new Uint8Array(32)), /does not match/);
  assert.match(cdpNearAccountName("user"), /^near-v1-[0-9a-f]{24}$/);
});

test("builder: normalizes, rejects unsafe input and binds the exact argument bytes", () => {
  const input = nearTransactionInput.parse({ receiver_id: "usdt.tether-token.near", actions: [{ type: "function_call", method_name: "ft_transfer", args: { receiver_id: "bob.near", amount: "1000000" }, deposit_yocto: "1" }] });
  const tx = normalizeNearTransaction(input);
  assert.deepEqual(JSON.parse(Buffer.from((tx.actions[0] as { args_base64: string }).args_base64, "base64").toString()), { receiver_id: "bob.near", amount: "1000000" });
  assert.equal((tx.actions[0] as { gas: string }).gas, "30000000000000");
  const d = describeNearTransaction(tx)[0] as { note?: string; deposit_near: string };
  assert.match(d.note!, /NEP-141/);
  assert.equal(d.deposit_near, "0.000000000000000000000001");
  assert.throws(() => normalizeNearTransaction(nearTransactionInput.parse({ receiver_id: "Bad.near", actions: [{ type: "transfer", amount_yocto: "1" }] })));
  assert.throws(() => normalizeNearTransaction(nearTransactionInput.parse({ receiver_id: "a.near", actions: [{ type: "transfer", amount_yocto: "0" }] })));
  assert.throws(() => normalizeNearTransaction(nearTransactionInput.parse({ receiver_id: "a.near", actions: Array(2).fill({ type: "function_call", method_name: "m", gas: "200000000000000" }) })), /300 TGas/);
  assert.throws(() => nearTransactionInput.parse({ receiver_id: "a.near", actions: [{ type: "add_key" }] }));
  assert.throws(() => nearTransactionInput.parse({ receiver_id: "a.near", actions: [{ type: "transfer", amount_yocto: "1", extra: 1 }] }));
  const pk = nearPublicKey(new Uint8Array(32).fill(1));
  const other = normalizeNearTransaction(nearTransactionInput.parse({ receiver_id: "usdt.tether-token.near", actions: [{ type: "function_call", method_name: "ft_transfer", args: { receiver_id: "eve.near", amount: "1000000" }, deposit_yocto: "1" }] }));
  assert.notEqual(nearFingerprint("mainnet", "a", pk, tx), nearFingerprint("mainnet", "a", pk, other));
  assert.notEqual(nearFingerprint("mainnet", "a", pk, tx), nearFingerprint("testnet", "a", pk, tx));
});

test("builder: signs sha256(borsh(tx)) and the signed transaction decodes and verifies", async () => {
  const { publicKey, sealed } = generateSealedKey(KEY, "u");
  const signer = SealedKeySigner.open(sealed, KEY, "u", publicKey);
  const tx = normalizeNearTransaction(nearTransactionInput.parse({ receiver_id: "bob.near", actions: [{ type: "transfer", amount_yocto: "1000" }, { type: "function_call", method_name: "ping", args: {}, deposit_yocto: "0" }] }));
  const built = buildNearTransaction(implicitAccountId(publicKey), publicKey, 42n, BLOCK, tx);
  const { hash, signedBase64 } = await signNearTransaction(built, signer);
  const decoded = decodeSignedTransaction(Buffer.from(signedBase64, "base64"));
  assert.equal(decoded.transaction.signerId, implicitAccountId(publicKey));
  assert.equal(decoded.transaction.receiverId, "bob.near");
  assert.equal(decoded.transaction.nonce, 42n);
  assert.equal(decoded.transaction.actions.length, 2);
  const digest = transactionDigest(decoded.transaction);
  assert.equal(baseEncode(digest), hash);
  assert.equal(hash, baseEncode(createHash("sha256").update(built.encode()).digest()));
  const sig = decoded.signature as unknown as { ed25519Signature: { data: Uint8Array } };
  assert.ok(verifyEd25519(publicKey, digest, Uint8Array.from(sig.ed25519Signature.data)));
  const stranger = generateSealedKey(KEY, "u");
  await assert.rejects(signNearTransaction(built, SealedKeySigner.open(stranger.sealed, KEY, "u", stranger.publicKey)), /does not match/);
});

function rpcWith(handler: (method: string, params: any) => unknown) {
  const fetcher = (async (_url: string, init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    const out = handler(body.method, body.params);
    return new Response(JSON.stringify(out instanceof Error ? { error: { name: "HANDLER_ERROR", cause: { name: out.message } } } : { result: out }), { status: 200 });
  }) as typeof fetch;
  return new NearRpc("https://rpc.example", "mainnet", fetcher);
}

test("rpc: unknown account maps to null, wrong network is refused, view results are decoded", async () => {
  const rpc = rpcWith((method, params) => {
    if (method === "status") return { chain_id: "testnet" };
    if (params.request_type === "view_account") return new Error("UNKNOWN_ACCOUNT");
    if (params.request_type === "call_function") return { result: [...Buffer.from(JSON.stringify({ ok: params.method_name }))], logs: ["l"], block_height: 5 };
    return null;
  });
  assert.equal(await rpc.viewAccount("f".repeat(64)), null);
  await assert.rejects(rpc.assertNetwork(), /chain_id mismatch/);
  const r = await rpc.callFunction("v1.signer", "public_key", {});
  assert.deepEqual(r.result, { ok: "public_key" });
  await assert.rejects(rpc.viewAccount("Bad"), /valid NEAR account/);
});

test("outcome summary never hides a failed receipt behind a successful transaction", () => {
  const s = summarizeOutcome({ final_execution_status: "FINAL", status: { SuccessValue: Buffer.from('"ok"').toString("base64") }, transaction_outcome: { id: "t", outcome: { logs: [], receipt_ids: ["r1"], gas_burnt: 1, tokens_burnt: "10", executor_id: "a", status: { SuccessReceiptId: "r1" } } }, receipts_outcome: [{ id: "r1", outcome: { logs: [], receipt_ids: [], gas_burnt: 1, tokens_burnt: "5", executor_id: "c.near", status: { Failure: { ActionError: {} } } } }] });
  assert.equal(s.result, "success");
  assert.equal(s.return_value, "ok");
  assert.equal(s.failed_receipts, 1);
  assert.equal(s.tokens_burnt_yocto, "15");
});
