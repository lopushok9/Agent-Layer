import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import test from "node:test";
import { decodeSignedTransaction } from "@near-js/transactions";
import { baseEncode } from "@near-js/utils";
import { keccak256, parseTransaction, recoverTransactionAddress, serializeTransaction, type Hex, type PublicClient } from "viem";
import { generatePrivateKey, privateKeyToAccount, sign } from "viem/accounts";
import { NearAccountService } from "../src/near/account.js";
import { ChainSignatures, parseMpcSignature, secp256k1KeyToAddress } from "../src/near/chain-signatures.js";
import { loadNearConfig } from "../src/near/config.js";
import { NearOperations } from "../src/near/operations.js";
import { NearRpc } from "../src/near/rpc.js";
import { transactionDigest } from "../src/near/transaction.js";
import { memoryStore } from "./near-fakes.js";

const config = loadNearConfig({ NEAR_RPC_URL: "https://rpc.example", NEAR_KEY_ENCRYPTION_KEY: randomBytes(32).toString("base64") })!;
const NEAR = 10n ** 24n;
const ETH = 10n ** 18n;

// A fake MPC network: one secp256k1 key stands for the key derived for (account, path).
function world(opts: { mpcKey?: Hex; wrongSigner?: boolean; ethBalance?: bigint; revert?: boolean } = {}) {
  const mpcKey = opts.mpcKey ?? generatePrivateKey();
  const mpc = privateKeyToAccount(mpcKey);
  const impostor = generatePrivateKey();
  const near = { nonce: 1, signs: [] as { path: string; payload: string; predecessor: string }[] };
  const evm = { sent: [] as Hex[], nonce: 5, receipts: new Set<Hex>() };
  const { store } = memoryStore();
  const rpc = new NearRpc("https://rpc.example", "mainnet", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body));
    const ok = (result: unknown) => new Response(JSON.stringify({ result }));
    if (b.method === "status") return ok({ chain_id: "mainnet" });
    if (b.method === "gas_price") return ok({ gas_price: "100000000" });
    if (b.method === "block") return ok({ header: { hash: baseEncode(new Uint8Array(32).fill(1)), height: 1 } });
    if (b.params?.request_type === "view_account") return ok({ amount: (5n * NEAR).toString(), locked: "0", storage_usage: 100, code_hash: "1", block_height: 1, block_hash: "x" });
    if (b.params?.request_type === "view_access_key") return ok({ nonce: near.nonce, permission: "FullAccess", block_hash: "x", block_height: 1 });
    if (b.params?.request_type === "call_function" && b.params.method_name === "derived_public_key") {
      assert.equal(b.params.account_id, "v1.signer");
      return ok({ result: [...Buffer.from(JSON.stringify(`secp256k1:${baseEncode(Buffer.from(mpc.publicKey.slice(4), "hex"))}`))], logs: [], block_height: 1 });
    }
    if (b.method === "send_tx") {
      const signed = decodeSignedTransaction(Buffer.from(b.params.signed_tx_base64, "base64"));
      const t = signed.transaction;
      assert.equal(t.receiverId, "v1.signer");
      const call = (t.actions[0] as any).functionCall;
      assert.equal(call.methodName, "sign");
      assert.equal(BigInt(call.deposit), 1n);
      const args = JSON.parse(Buffer.from(call.args).toString());
      near.signs.push({ path: args.request.path, payload: args.request.payload_v2.Ecdsa, predecessor: t.signerId });
      near.nonce++;
      const sig = await sign({ hash: `0x${args.request.payload_v2.Ecdsa}`, privateKey: opts.wrongSigner ? impostor : mpcKey });
      const rPoint = `0${2 + sig.yParity!}${sig.r.slice(2)}`;
      const response = { scheme: "Secp256k1", big_r: { affine_point: rPoint }, s: { scalar: sig.s.slice(2) }, recovery_id: sig.yParity };
      const hash = baseEncode(transactionDigest(t));
      return ok({ final_execution_status: "FINAL", status: { SuccessValue: Buffer.from(JSON.stringify(response)).toString("base64") }, transaction: { hash }, transaction_outcome: { id: hash, outcome: { logs: [], receipt_ids: [], gas_burnt: 1, tokens_burnt: "1", executor_id: "a", status: {} } }, receipts_outcome: [] });
    }
    throw new Error(`unexpected ${b.method}`);
  }) as typeof fetch);
  const client = {
    async getChainId() { return 8453; },
    async getTransactionCount() { return evm.nonce; },
    async estimateFeesPerGas() { return { maxFeePerGas: 1_000_000n, maxPriorityFeePerGas: 1000n }; },
    async getBalance() { return opts.ethBalance ?? ETH; },
    async estimateGas() { if (opts.revert) throw new Error("execution reverted"); return 21_000n; },
    async sendRawTransaction({ serializedTransaction }: { serializedTransaction: Hex }) {
      assert.equal((await recoverTransactionAddress({ serializedTransaction: serializedTransaction as any })).toLowerCase(), mpc.address.toLowerCase());
      evm.sent.push(serializedTransaction); return keccak256(serializedTransaction);
    },
    async getTransactionReceipt({ hash }: { hash: Hex }) { if (!evm.receipts.has(hash)) throw new Error("not found"); return { status: "success", blockNumber: 9n, gasUsed: 21000n }; },
  } as unknown as PublicClient;
  const accounts = new NearAccountService(config, store, rpc);
  const operations = new NearOperations(accounts, store);
  const chainSigs = new ChainSignatures(accounts, operations, store, () => client);
  return { chainSigs, accounts, near, evm, mpc };
}

test("derived address comes from the MPC contract view for this user's NEAR account", async () => {
  const w = world();
  const status = await w.chainSigs.status("u");
  assert.equal(status.evm_address, w.mpc.address);
  assert.equal(status.derivation_path, "agentlayer-evm-1");
  assert.throws(() => secp256k1KeyToAddress("ed25519:abc"));
});

test("chain signature: MPC signs exactly the previewed EIP-1559 hash; broadcast only after recovery matches", async () => {
  const w = world();
  const to = "0x000000000000000000000000000000000000dEaD";
  const preview = await w.chainSigs.prepare("u", { network: "base", to, value_wei: "1000", data: "0x" }) as any;
  assert.equal(preview.kind, "chain_signature");
  assert.equal(preview.receiver_id, "v1.signer");
  assert.equal(preview.actions[0].args.request.payload_v2.Ecdsa, preview.evm_transaction.signing_payload.slice(2));
  assert.equal(preview.evm_transaction.from, w.mpc.address);
  const r = await w.chainSigs.execute("u", preview.operation_id, "send dead") as any;
  assert.equal(r.stage, "evm_submitted");
  assert.equal(w.evm.sent.length, 1);
  const tx = parseTransaction(w.evm.sent[0]!);
  assert.equal(tx.chainId, 8453);
  assert.equal(tx.nonce, 5);
  assert.equal(tx.to!.toLowerCase(), to.toLowerCase());
  assert.equal(tx.value, 1000n);
  assert.equal(keccak256(serializeTransaction({ ...tx, r: undefined, s: undefined, v: undefined, yParity: undefined } as any)), preview.evm_transaction.signing_payload);
  assert.equal(w.near.signs[0]!.predecessor, (await w.accounts.account("u")).accountId);
  // Receipt reconciliation.
  w.evm.receipts.add(r.evm_tx_hash);
  const s = await w.chainSigs.operationStatus("u", preview.operation_id) as any;
  assert.equal(s.stage, "evm_final");
  assert.equal(s.evm.status, "success");
});

test("a signature that does not recover to the derived address is never broadcast", async () => {
  const w = world({ wrongSigner: true });
  const preview = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "1" }) as any;
  await assert.rejects(w.chainSigs.execute("u", preview.operation_id, "x"), /does not recover/);
  assert.equal(w.evm.sent.length, 0);
});

test("prepare refuses reverting calls and unfunded derived addresses before anything is signed", async () => {
  await assert.rejects(world({ revert: true }).chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "0", data: "0x12345678" }), /reverts/);
  await assert.rejects(world({ ethBalance: 0n }).chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "1" }), /insufficient ETH/);
});

test("MPC response parser accepts the mainnet wire format and rejects malformed values", () => {
  const sig = parseMpcSignature({ scheme: "Secp256k1", big_r: { affine_point: "02418a2608cb6819709bfdd267460e8eebf7d9375414cc9cd753c7bbf00f8688fa" }, s: { scalar: "620ea83728c75ca54ba37234a563f8037793cf5705cfacc1dc6d40e262803cf6" }, recovery_id: 1 });
  assert.equal(sig.r, "0x418a2608cb6819709bfdd267460e8eebf7d9375414cc9cd753c7bbf00f8688fa");
  assert.equal(sig.yParity, 1);
  assert.throws(() => parseMpcSignature({ scheme: "Ed25519", signature: [] }));
  assert.throws(() => parseMpcSignature({ big_r: { affine_point: "04" + "a".repeat(64) }, s: { scalar: "1".repeat(64) }, recovery_id: 0 }));
  assert.throws(() => parseMpcSignature(null));
});
