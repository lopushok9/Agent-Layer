import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { decodeSignedTransaction } from "@near-js/transactions";
import { baseEncode } from "@near-js/utils";
import { encodeAbiParameters, encodeEventTopics, getAddress, hashTypedData, recoverTypedDataAddress, type Hex, type PublicClient } from "viem";
import { generatePrivateKey, privateKeyToAccount, sign } from "viem/accounts";
import { BASE_NETWORK, BASE_USDC, type Config } from "../src/config.js";
import { NearAccountService } from "../src/near/account.js";
import { ChainSignatures, SIMPLE_7702_ACCOUNT } from "../src/near/chain-signatures.js";
import { loadNearConfig } from "../src/near/config.js";
import { NearOperations } from "../src/near/operations.js";
import { NearRpc } from "../src/near/rpc.js";
import { transactionDigest } from "../src/near/transaction.js";
import { authorizationTypedData, NearX402Payments, USDC_ABI, type PaymentPlan } from "../src/near/x402.js";
import type { NearPayment, NearPaymentStore, PaymentState } from "../src/near/x402-store.js";
import { memoryStore } from "./near-fakes.js";

export function memoryPayments(now: () => number) {
  const rows = new Map<string, NearPayment>();
  const store: NearPaymentStore = {
    async create(userId, amount, plan, ttl) { const row: NearPayment = { id: randomUUID(), userId, amount, plan: structuredClone(plan), status: "prepared", purpose: null, result: null, expiresAt: new Date(now() + ttl * 1000) }; rows.set(row.id, row); return structuredClone(row); },
    async get(userId, id) { const row = rows.get(id); return row?.userId === userId ? structuredClone(row) : null; },
    async reserve(userId, id, purpose, limit) {
      const row = rows.get(id);
      if (!row || row.userId !== userId) throw new Error("payment preview not found for this user");
      if (row.status !== "prepared") throw new Error("payment preview already consumed; use x402_status");
      if (row.expiresAt.getTime() <= now()) throw new Error("preview expired");
      if ([...rows.values()].some(r => r.userId === userId && ["reserved", "signing", "signed", "sending", "unknown"].includes(r.status))) throw new Error("unresolved payment");
      const spent = [...rows.values()].filter(r => r.userId === userId && ["reserved", "signing", "signed", "sending", "unknown", "settled"].includes(r.status)).reduce((a, r) => a + BigInt(r.amount), 0n);
      if (limit !== null && spent + BigInt(row.amount) > limit) throw new Error("daily spend limit exceeded");
      row.status = "reserved"; row.purpose = purpose; return structuredClone(row);
    },
    async update(userId, id, status, plan, result) {
      const row = rows.get(id); if (!row || row.userId !== userId) throw new Error("not found");
      Object.assign(row, { status, plan: structuredClone(plan), ...(result ? { result: structuredClone(result) } : {}) }); return structuredClone(row);
    },
  };
  return { rows, store };
}

export function paymentWorld() {
  const key = generatePrivateKey(), mpc = privateKeyToAccount(key);
  let now = Date.now();
  const { store: nearStore, ops } = memoryStore();
  const payments = memoryPayments(() => now);
  const state = {
    signs: [] as any[], sends: [] as { url: string; init: RequestInit; payload: any }[], probes: [] as any[],
    pending: false, rpcDown: false, wrongSigner: false, highS: false, malformed: false,
    timeout: false, settle: true, fakeHeader: false, responseStatus: 200, missingHeader: false, simulationFails: false,
    gasPrice: "100000000", chainId: 8453, balance: 10_000_000n, nearBalance: 5n * 10n ** 24n, delegate: null as string | null,
    finalTimestamp: 0n, canceled: false, receiptAmount: null as bigint | null, receiptToken: BASE_USDC as string,
    signatureChecks: 0, simulations: 0, advanceDuringSign: 0,
  };
  const outcomes = new Map<string, any>(), receipts = new Map<string, any>();
  const nearConfig = loadNearConfig({ NEAR_RPC_URL: "https://rpc.example", NEAR_KEY_ENCRYPTION_KEY: randomBytes(32).toString("base64") })!;
  let nearNonce = 1;
  const nearRpc = new NearRpc("https://rpc.example", "mainnet", (async (_url, init) => {
    const b = JSON.parse(String(init!.body)); const ok = (result: any) => new Response(JSON.stringify({ result }));
    if (b.method === "status") return ok({ chain_id: "mainnet" });
    if (b.method === "gas_price") return ok({ gas_price: state.gasPrice });
    if (b.method === "block") return ok({ header: { hash: baseEncode(new Uint8Array(32).fill(1)), height: 1 } });
    if (b.params?.request_type === "view_account") return ok({ amount: String(state.nearBalance), locked: "0", storage_usage: 100 });
    if (b.params?.request_type === "view_access_key") return ok({ nonce: nearNonce, permission: "FullAccess" });
    if (b.params?.method_name === "derived_public_key") return ok({ result: [...Buffer.from(JSON.stringify(`secp256k1:${baseEncode(Buffer.from(mpc.publicKey.slice(4), "hex"))}`))], logs: [], block_height: 1 });
    if (b.method === "send_tx") {
      const signed = decodeSignedTransaction(Buffer.from(b.params.signed_tx_base64, "base64"));
      const t = signed.transaction, call = (t.actions[0] as any).functionCall;
      assert.equal(t.receiverId, "v1.signer"); assert.equal(call.methodName, "sign");
      const args = JSON.parse(Buffer.from(call.args).toString());
      state.signs.push({ args, predecessor: t.signerId }); nearNonce++;
      const row = [...payments.rows.values()].find(r => r.plan.digest === `0x${args.request.payload_v2.Ecdsa}`)!;
      assert.ok(row?.plan.authorization, "authorization persisted before MPC request");
      const sig = await sign({ hash: `0x${args.request.payload_v2.Ecdsa}`, privateKey: state.wrongSigner ? generatePrivateKey() : key });
      let s = BigInt(sig.s), parity = sig.yParity!;
      if (state.highS) { s = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n - s; parity ^= 1; }
      const wire = state.malformed ? {} : { scheme: "Secp256k1", big_r: { affine_point: `0${2 + parity}${sig.r.slice(2)}` }, s: { scalar: s.toString(16).padStart(64, "0") }, recovery_id: parity };
      const hash = baseEncode(transactionDigest(t));
      const outcome = { final_execution_status: "FINAL", status: { SuccessValue: Buffer.from(JSON.stringify(wire)).toString("base64") }, transaction: { hash }, receipts_outcome: [] };
      outcomes.set(hash, outcome); now += state.advanceDuringSign * 1000;
      if (state.pending) return ok({ final_execution_status: "INCLUDED", status: "Started", transaction: { hash } });
      return ok(outcome);
    }
    if (b.method === "EXPERIMENTAL_tx_status") return ok(state.pending ? { status: "Started" } : outcomes.get(b.params.tx_hash));
    throw new Error(`unexpected NEAR RPC ${b.method}`);
  }) as typeof fetch);
  const rpc = {
    async getChainId() { return state.chainId; },
    async getCode({ address }: any) { if (address.toLowerCase() === mpc.address.toLowerCase()) return state.delegate ? `0xef0100${state.delegate.slice(2)}` : "0x"; return "0x6080"; },
    async readContract({ functionName, args }: any) {
      if (functionName === "balanceOf") return state.balance;
      if (functionName === "isValidSignature") { state.signatureChecks++; const row = [...payments.rows.values()].find(r => r.plan.digest === args[0])!; assert.equal((await recoverTypedDataAddress({ ...authorizationTypedData(row.plan.authorization!), signature: args[1] })).toLowerCase(), mpc.address.toLowerCase()); return "0x1626ba7e"; }
      throw new Error(functionName);
    },
    async getBlockNumber() { return 100n; },
    async getBlock({ blockTag }: any = {}) { if (state.rpcDown) throw new Error("RPC down"); return { number: 110n, timestamp: blockTag === "finalized" ? state.finalTimestamp : BigInt(Math.floor(now / 1000)) }; },
    async simulateContract({ functionName, args }: any) {
      state.simulations++; if (state.simulationFails) throw new Error("revert"); assert.equal(functionName, "transferWithAuthorization");
      const row = [...payments.rows.values()].find(r => r.plan.authorization?.nonce === args[5])!;
      assert.equal((await recoverTypedDataAddress({ ...authorizationTypedData(row.plan.authorization!), signature: args[6] })).toLowerCase(), mpc.address.toLowerCase());
    },
    async getTransactionReceipt({ hash }: any) { if (state.rpcDown || !receipts.has(hash)) throw new Error("receipt unavailable"); return receipts.get(hash); },
    async getLogs({ event }: any) {
      if (state.rpcDown) throw new Error("RPC down");
      if (event.name === "AuthorizationCanceled") return state.canceled ? [{ transactionHash: `0x${"bb".repeat(32)}` }] : [];
      return [...receipts.keys()].map(transactionHash => ({ transactionHash }));
    },
    async sendRawTransaction() { throw new Error("payer must never send a Base transaction for x402"); },
    async getTransactionCount() { throw new Error("Base transaction nonce is unrelated to authorization nonce"); },
  } as unknown as PublicClient;
  const accounts = new NearAccountService(nearConfig, nearStore, nearRpc);
  const operations = new NearOperations(accounts, nearStore);
  const cs = new ChainSignatures(accounts, operations, nearStore, () => rpc);
  const config = { PREVIEW_TTL_SECONDS: 600, PAYMENT_TIMEOUT_MS: 45_000, SPEND_LIMITS_ENABLED: true, MAX_PAYMENT_USDC_ATOMIC: "1000000", MAX_DAILY_USDC_ATOMIC: "5000000" } as Config;
  const terms = { scheme: "exact", network: BASE_NETWORK, asset: BASE_USDC, amount: "1000", payTo: "0x1111111111111111111111111111111111111111", maxTimeoutSeconds: 120, extra: { name: "USD Coin", version: "2", assetTransferMethod: "eip3009" } };
  const challenge = { x402Version: 2, resource: { url: "https://api.example.com/data", description: "test API", mimeType: "application/json" }, accepts: [terms] };
  const locks = new Map<string, Promise<unknown>>();
  const locking = { async withPaymentLock<T>(user: string, run: () => Promise<T>): Promise<T> { const before = locks.get(user) ?? Promise.resolve(); const p = before.catch(() => {}).then(run); locks.set(user, p); return p; } };
  const send = (async (url, init) => {
    const headers = new Headers(init?.headers), raw = headers.get("payment-signature")!;
    const payload = JSON.parse(Buffer.from(raw, "base64").toString());
    state.sends.push({ url: String(url), init: init!, payload });
    const a = payload.payload.authorization;
    const hash = `0x${"ab".repeat(32)}` as Hex;
    if (state.settle) {
      const logs = [
        { address: state.receiptToken, topics: encodeEventTopics({ abi: USDC_ABI, eventName: "AuthorizationUsed", args: { authorizer: a.from, nonce: a.nonce } }), data: "0x" },
        { address: state.receiptToken, topics: encodeEventTopics({ abi: USDC_ABI, eventName: "Transfer", args: { from: a.from, to: a.to } }), data: encodeAbiParameters([{ type: "uint256" }], [state.receiptAmount ?? BigInt(a.value)]) },
      ];
      receipts.set(hash, { status: "success", logs });
    }
    if (state.timeout) throw new Error("fetch failed https://api.example.com/?key=SECRET");
    return new Response(JSON.stringify({ data: "paid API result" }), { status: state.responseStatus, headers: state.missingHeader ? { "content-type": "application/json" } : { "content-type": "application/json", "payment-response": Buffer.from(JSON.stringify({ success: true, transaction: state.fakeHeader ? `0x${"cc".repeat(32)}` : hash, network: BASE_NETWORK })).toString("base64") } });
  }) as typeof fetch;
  const makeService = () => new NearX402Payments(config, accounts, operations, nearStore, cs, payments.store, locking, {
    now: () => now, listing: async () => ({ listed: true, method: "POST" as const }),
    probe: (async (url, init) => { state.probes.push({ url, init }); return new Response(null, { status: 402, headers: { "payment-required": Buffer.from(JSON.stringify(challenge)).toString("base64") } }); }) as typeof fetch,
    send,
  });
  return { service: makeService(), makeService, state, rows: payments.rows, paymentStore: payments.store, nearStore, ops, accounts, operations, config, terms, challenge, mpc, rpc, receipts,
    advance(seconds: number) { now += seconds * 1000; }, now: () => now,
    delegate() { state.delegate = SIMPLE_7702_ACCOUNT; },
  };
}
