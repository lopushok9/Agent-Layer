import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import test from "node:test";
import { decodeSignedTransaction } from "@near-js/transactions";
import { baseEncode } from "@near-js/utils";
import { encodeErrorResult, erc20Abi, keccak256, parseTransaction, recoverTransactionAddress, serializeTransaction, type Hex, type PublicClient } from "viem";
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
const USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const usdcChange = (diff: bigint) => [{ token: { address: USDC.toLowerCase(), symbol: "USDC", decimals: 6 }, value: { pre: 200000n, post: 200000n + diff, diff } }];
const verifiedErc20 = { contract: async () => ({ abi: erc20Abi, source: "verified_sourcify" as const }), describeCall: async () => null, describeTypedData: async () => null };

function world(opts: { mpcKey?: Hex; wrongSigner?: boolean; ethBalance?: bigint; revert?: boolean; contracts?: typeof verifiedErc20 } = {}) {
  const mpcKey = opts.mpcKey ?? generatePrivateKey();
  const mpc = privateKeyToAccount(mpcKey);
  const impostor = generatePrivateKey();
  const near = { nonce: 1, signs: [] as { path: string; payload: string; predecessor: string }[] };
  const evm = { sent: [] as Hex[], nonce: 5, latest: 5, nonceTooLow: false, rpcDown: false, receipts: new Set<Hex>(), assetChanges: [] as unknown[], simulated: 0 };
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
    async getTransactionCount({ blockTag }: { blockTag?: string }) { return blockTag === "latest" ? evm.latest : evm.nonce; },
    async estimateFeesPerGas() { return { maxFeePerGas: 1_000_000n, maxPriorityFeePerGas: 1000n }; },
    async getBalance() { return opts.ethBalance ?? ETH; },
    async estimateGas() { if (opts.revert) throw new Error("execution reverted"); return 21_000n; },
    async getBlockNumber() { return 100n; },
    async getCode() { return "0x6080"; },
    async simulateCalls({ account }: { account: Hex }) {
      assert.equal(account.toLowerCase(), mpc.address.toLowerCase(), "simulated from the derived address");
      evm.simulated++;
      if (opts.revert) return { results: [{ status: "failure", data: encodeErrorResult({ abi: [{ type: "error", name: "Error", inputs: [{ type: "string" }] }], errorName: "Error", args: ["ERC20: transfer amount exceeds balance"] }), gasUsed: 0n, logs: [] }], assetChanges: [] };
      return { results: [{ status: "success", data: "0x", gasUsed: 30000n, logs: [] }], assetChanges: evm.assetChanges };
    },
    async sendRawTransaction({ serializedTransaction }: { serializedTransaction: Hex }) {
      assert.equal((await recoverTransactionAddress({ serializedTransaction: serializedTransaction as any })).toLowerCase(), mpc.address.toLowerCase());
      if (evm.nonceTooLow) throw new Error("nonce too low: next nonce 6, tx nonce 5");
      evm.sent.push(serializedTransaction); evm.nonce++; return keccak256(serializedTransaction);
    },
    async getTransactionReceipt({ hash }: { hash: Hex }) { if (evm.rpcDown) throw new Error("fetch failed"); if (!evm.receipts.has(hash)) throw Object.assign(new Error("not found"), { name: "TransactionReceiptNotFoundError" }); return { status: "success", blockNumber: 9n, gasUsed: 21000n }; },
  } as unknown as PublicClient;
  const accounts = new NearAccountService(config, store, rpc);
  const operations = new NearOperations(accounts, store);
  const chainSigs = new ChainSignatures(accounts, operations, store, () => client, opts.contracts ?? null);
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

test("a preview whose nonce was used since is refused before the MPC sign() is paid", async () => {
  const w = world();
  const a = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "1" }) as any;
  const b = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "2" }) as any;
  assert.equal(a.evm_transaction.nonce, 5);
  assert.equal(b.evm_transaction.nonce, 5);
  assert.equal((await w.chainSigs.execute("u", a.operation_id, "first") as any).stage, "evm_submitted");
  await assert.rejects(w.chainSigs.execute("u", b.operation_id, "second"), /nonce on base is now 6.*Nothing was signed/);
  assert.equal(w.near.signs.length, 1, "no second MPC request");
  const c = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "2" }) as any;
  assert.equal(c.evm_transaction.nonce, 6);
});

test("'nonce too low' for a transaction that was never mined is reported as dropped, not submitted", async () => {
  const w = world();
  const p = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "1" }) as any;
  // Another wallet with the same key raced us between the nonce check and the broadcast.
  w.evm.nonceTooLow = true; w.evm.latest = 6;
  const r = await w.chainSigs.execute("u", p.operation_id, "x") as any;
  assert.equal(r.stage, "evm_dropped");
  assert.equal(w.evm.sent.length, 0);
  const s = await w.chainSigs.operationStatus("u", p.operation_id) as any;
  assert.equal(s.stage, "evm_dropped");
  // The account is not blocked: a new preview can be prepared and executed.
  w.evm.nonceTooLow = false; w.evm.nonce = 6;
  const next = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "1" }) as any;
  assert.equal((await w.chainSigs.execute("u", next.operation_id, "y") as any).stage, "evm_submitted");
});

test("a submitted transaction whose nonce was taken by another one becomes dropped on status", async () => {
  const w = world();
  const p = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "1" }) as any;
  await w.chainSigs.execute("u", p.operation_id, "x");
  assert.equal((await w.chainSigs.operationStatus("u", p.operation_id) as any).stage, "evm_pending");
  w.evm.latest = 6; // nonce 5 mined, but not by our hash
  w.evm.rpcDown = true;
  assert.equal((await w.chainSigs.operationStatus("u", p.operation_id) as any).stage, "evm_pending", "an RPC failure is never read as dropped");
  w.evm.rpcDown = false;
  assert.equal((await w.chainSigs.operationStatus("u", p.operation_id) as any).stage, "evm_dropped");
});

test("function_name alone is encoded with the verified ABI and the preview shows the decoded call and simulated asset changes", async () => {
  const w = world({ contracts: verifiedErc20 });
  w.evm.assetChanges = usdcChange(-10000n);
  const p = await w.chainSigs.prepare("u", { network: "base", to: USDC, function_name: "transfer", args: ["0x000000000000000000000000000000000000dEaD", "10000"] }) as any;
  assert.equal(p.evm_call.function, "transfer");
  assert.equal(p.evm_call.abi_source, "verified_sourcify");
  assert.deepEqual(p.evm_call.arguments, ["0x000000000000000000000000000000000000dEaD", "10000"]);
  assert.equal(p.simulation.asset_changes[0].value.diff, "-10000");
  assert.ok(p.evm_transaction.data.startsWith("0xa9059cbb"));
  // A function the verified ABI does not have is refused, never guessed.
  await assert.rejects(w.chainSigs.prepare("u", { network: "base", to: USDC, function_name: "mint", args: ["1"] }), /no function mint in its verified ABI.*nothing was signed/);
  // Without a verified ABI and without abi, function_name cannot be encoded.
  await assert.rejects(world().chainSigs.prepare("u", { network: "base", to: USDC, function_name: "transfer", args: ["0x000000000000000000000000000000000000dEaD", "1"] }), /no verified ABI/);
  // Self-calls from the derived address are refused like wallet self-calls.
  await assert.rejects(w.chainSigs.prepare("u", { network: "base", to: w.mpc.address, value_wei: "1" }), /self-calls/);
});

test("approve is flagged; a worse re-simulation before signing refuses without paying for MPC", async () => {
  const w = world({ contracts: verifiedErc20 });
  w.evm.assetChanges = usdcChange(-10000n);
  const approve = await w.chainSigs.prepare("u", { network: "base", to: USDC, function_name: "approve", args: ["0x000000000000000000000000000000000000dEaD", "115792089237316195423570985008687907853269984665640564039457584007913129639935"] }) as any;
  assert.match(approve.evm_call.warnings.join(" "), /allowance/);
  const p = await w.chainSigs.prepare("u", { network: "base", to: USDC, function_name: "transfer", args: ["0x000000000000000000000000000000000000dEaD", "10000"] }) as any;
  w.evm.assetChanges = usdcChange(-20000n);
  await assert.rejects(w.chainSigs.execute("u", p.operation_id, "x"), /asset changes differ from preview.*Nothing was signed/);
  assert.equal(w.near.signs.length, 0);
  assert.equal(w.evm.sent.length, 0);
  // Same outcome as previewed: re-simulated, then signed and sent.
  w.evm.assetChanges = usdcChange(-10000n);
  const again = await w.chainSigs.prepare("u", { network: "base", to: USDC, function_name: "transfer", args: ["0x000000000000000000000000000000000000dEaD", "10000"] }) as any;
  const before = w.evm.simulated;
  assert.equal((await w.chainSigs.execute("u", again.operation_id, "y") as any).stage, "evm_submitted");
  assert.equal(w.evm.simulated, before + 1);
});

test("a max withdrawal may grow with accrued interest only if what is received grows in proportion", async () => {
  const MAX = ((1n << 256n) - 1n).toString();
  const A_USDC = "0x4e65fe4dba92790696d040ac24aa414708f5c0ab";
  const changes = (aOut: bigint, usdcIn: bigint) => [
    { token: { address: A_USDC, symbol: "aBasUSDC", decimals: 6 }, value: { pre: aOut, post: 0n, diff: -aOut } },
    { token: { address: USDC.toLowerCase(), symbol: "USDC", decimals: 6 }, value: { pre: 0n, post: usdcIn, diff: usdcIn } },
  ];
  const pool = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5";
  const withdrawAbi = [{ type: "function", name: "withdraw", stateMutability: "nonpayable", inputs: [{ name: "asset", type: "address" }, { name: "amount", type: "uint256" }, { name: "to", type: "address" }], outputs: [{ type: "uint256" }] }];
  const run = async (aNow: bigint, usdcNow: bigint, amount = MAX) => {
    const w = world();
    w.evm.assetChanges = changes(1_000_000n, 1_000_000n);
    const p = await w.chainSigs.prepare("u", { network: "base", to: pool, abi: withdrawAbi, function_name: "withdraw", args: [USDC, amount, w.mpc.address] }) as any;
    w.evm.assetChanges = changes(aNow, usdcNow);
    return { p, exec: w.chainSigs.execute("u", p.operation_id, "withdraw"), w };
  };
  const ok = await run(1_000_500n, 1_000_500n); // interest accrued: 5 bps more burned and received
  assert.equal(ok.p.simulation.max_amount_growth_bps, 100);
  assert.equal((await ok.exec as any).stage, "evm_submitted");
  // More burned but received below the scaled floor (floor 995000 x 1.0005 = 995497).
  await assert.rejects((await run(1_000_500n, 990_000n)).exec, /after scaling the max amount.*Nothing was signed/);
  await assert.rejects((await run(1_200_000n, 1_200_000n)).exec, /grew more than 100 bps/); // beyond the bound
  const exact = await run(1_000_500n, 1_000_500n, "1000000"); // not a max amount: outflows stay strict
  assert.equal(exact.p.simulation.max_amount_growth_bps, undefined);
  await assert.rejects(exact.exec, /asset changes differ/);
});

test("a signature that does not recover to the derived address is never broadcast", async () => {
  const w = world({ wrongSigner: true });
  const preview = await w.chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "1" }) as any;
  await assert.rejects(w.chainSigs.execute("u", preview.operation_id, "x"), /does not recover/);
  assert.equal(w.evm.sent.length, 0);
});

test("prepare refuses reverting calls and unfunded derived addresses before anything is signed", async () => {
  await assert.rejects(world({ revert: true }).chainSigs.prepare("u", { network: "base", to: "0x000000000000000000000000000000000000dEaD", value_wei: "0", data: "0x12345678" }), /simulation reverted at call 0 .*exceeds balance.*nothing was signed/);
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
