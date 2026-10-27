import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, erc20Abi, keccak256, type TransactionSerializable } from "viem";
import { BaseService, normalizeRecipient, parseUsdcAmount, type BaseChain } from "../src/base.js";
import { BASE_USDC, type Config } from "../src/config.js";
import type { Store } from "../src/store.js";

const BASE_CHAIN_ID = 8453;
const SELF = "0x1111111111111111111111111111111111111111";
const TO = "0x2222222222222222222222222222222222222222";
const config = { BASE_MAX_TRANSFER_USDC_ATOMIC: "50000000", BASE_MAX_DAILY_TRANSFER_USDC_ATOMIC: "200000000", PREVIEW_TTL_SECONDS: 120 } as Config;

function harness(opts: { balance?: bigint; usedToday?: bigint; sign?: (tx: TransactionSerializable) => Promise<`0x${string}`>; send?: () => Promise<`0x${string}`>; receipt?: () => Promise<{ status: "success" | "reverted" }>; reserve?: boolean; eth?: bigint; chainId?: number; changedWallet?: boolean; feeIncrease?: boolean; auditFailure?: boolean } = {}) {
  const finished: { status: string; hash: string | null; error: string | null }[] = [];
  const signed: TransactionSerializable[] = [];
  let preview: { to: string; amount: bigint; fee: bigint; from: string } | null = null;
  const store = {
    baseTransferredToday: async () => opts.usedToday ?? 0n,
    createBasePreview: async (p: { to: string; amount: bigint; fee: bigint; from: string }) => { preview = p; return { id: "11111111-1111-4111-8111-111111111111", expiresAt: new Date() }; },
    reserveBaseTransfer: async () => (opts.reserve === false ? null : { transferId: "t1", to: preview?.to ?? TO, amount: preview?.amount ?? 5_000_000n, from: opts.changedWallet ? TO : SELF, fee: preview?.fee ?? 2_000_000_000_000_000n }),
    finishBaseTransfer: async (_id: string, status: string, hash: string | null, error: string | null) => { if (opts.auditFailure) throw new Error("database unavailable"); finished.push({ status, hash, error }); },
    withPaymentLock: async <T>(_u: string, action: () => Promise<T>) => action(),
  } as unknown as Store;
  let sent = 0;
  let feeReads = 0;
  const chain = {
    getChainId: async () => opts.chainId ?? 8453,
    getBalance: async () => opts.eth ?? 10n ** 18n,
    estimateL1Fee: async () => 1000n,
    estimateOperatorFee: async () => 2000n,
    readContract: async () => opts.balance ?? 100_000_000n,
    estimateGas: async () => 60_000n,
    estimateFeesPerGas: async () => ({ maxFeePerGas: opts.feeIncrease && feeReads++ > 0 ? 40_000_000_000n : 20_000_000_000n, maxPriorityFeePerGas: 1_000_000_000n }),
    getTransactionCount: async () => 7,
    sendRawTransaction: async () => { sent++; return opts.send ? opts.send() : ("0xabc" as `0x${string}`); },
    waitForTransactionReceipt: async () => (opts.receipt ? opts.receipt() : { status: "success" }),
  } as unknown as BaseChain;
  const signer = { address: SELF, signTransaction: async (tx: TransactionSerializable) => { signed.push(tx); return opts.sign ? opts.sign(tx) : ("0x02f8deadbeef" as `0x${string}`); } };
  const base = new BaseService(config, store, async () => signer, chain);
  return { base, finished, signed, sentCount: () => sent, preview: () => preview };
}

test("amounts and recipients are validated strictly", () => {
  assert.equal(parseUsdcAmount("1.5"), 1_500_000n);
  assert.equal(parseUsdcAmount("0.000001"), 1n);
  for (const bad of ["0", "-1", "1.1234567", "abc", "1e3", ""]) assert.throws(() => parseUsdcAmount(bad), bad);
  assert.equal(normalizeRecipient(TO.toUpperCase().replace("0X", "0x"), SELF), "0x2222222222222222222222222222222222222222");
  assert.throws(() => normalizeRecipient("0x0000000000000000000000000000000000000000", SELF), /zero address/);
  assert.throws(() => normalizeRecipient(SELF, SELF), /own address/);
  assert.throws(() => normalizeRecipient(BASE_USDC, SELF), /token contract/);
  assert.throws(() => normalizeRecipient("0x123", SELF), /20-byte/);
});

test("preview enforces per-transfer, daily, and balance-plus-fee limits", async () => {
  await assert.rejects(harness().base.preview("u", TO, "50.000001"), /per-transfer limit/);
  await assert.rejects(harness({ usedToday: 180_000_000n }).base.preview("u", TO, "25"), /remaining daily limit of 20 USDC/);
  await assert.rejects(harness({ balance: 4_000_000n }).base.preview("u", TO, "5"), /insufficient balance/);
  await assert.rejects(harness({ eth: 0n }).base.preview("u", TO, "5"), /insufficient ETH for Base gas/);
  await assert.rejects(harness({ eth: 1_440_000_000_000_000n }).base.preview("u", TO, "5"), /insufficient ETH/, "L1 and operator fees count too");
  const h = harness({ balance: 5_000_000n });
  const result = await h.base.preview("u", TO, "5");
  assert.equal(result.amount_usdc, "5"); assert.equal(result.estimated_network_fee_eth, "0.001440000000003"); assert.match(result.next_step, /Nothing has been signed/);
  assert.deepEqual(h.preview(), { userId: "u", to: TO, amount: 5_000_000n, fee: 1_440_000_000_003_000n, from: SELF });
  assert.equal(h.signed.length, 0, "preview never signs");
});

test("transfer signs exactly one Base USDC transfer and records its outcome", async () => {
  const h = harness();
  await h.base.preview("u", TO, "5");
  const result = await h.base.transfer("u", "11111111-1111-4111-8111-111111111111", "pay the designer");
  assert.equal(result.status, "confirmed");
  assert.equal(h.signed.length, 1);
  const tx = h.signed[0]!;
  assert.equal(tx.chainId, BASE_CHAIN_ID); assert.equal(tx.to, BASE_USDC); assert.equal(tx.value, 0n); assert.equal(tx.type, "eip1559"); assert.equal(tx.nonce, 7); assert.equal(tx.gas, 72_000n);
  const call = decodeFunctionData({ abi: erc20Abi, data: tx.data! });
  assert.equal(call.functionName, "transfer"); assert.deepEqual(call.args, [TO, 5_000_000n]);
  const hash = keccak256("0x02f8deadbeef");
  assert.equal(result.tx_hash, hash);
  assert.deepEqual(h.finished.map((f) => f.status), ["unknown", "submitted", "confirmed"]);
});

test("a signing failure is recorded as failed and nothing is broadcast", async () => {
  const h = harness({ sign: async () => { throw new Error("CDP rejected"); } });
  await assert.rejects(h.base.transfer("u", "p", "purpose"), /CDP rejected/);
  assert.equal(h.sentCount(), 0); assert.deepEqual(h.finished, [{ status: "failed", hash: null, error: "CDP rejected" }]);
});

test("a broadcast failure after signing is unknown, never failed, and keeps the hash", async () => {
  const h = harness({ send: async () => { throw new Error("rpc timeout"); } });
  const result = await h.base.transfer("u", "p", "purpose");
  assert.equal(result.status, "unknown"); assert.match(String(result.note), /Do not resend/);
  assert.equal(h.finished[0]!.status, "unknown"); assert.equal(h.finished[0]!.hash, keccak256("0x02f8deadbeef"));
});

test("an unconfirmed broadcast is reported as submitted and a reverted one as failed", async () => {
  const pending = await harness({ receipt: async () => { throw new Error("timeout"); } }).base.transfer("u", "p", "purpose");
  assert.equal(pending.status, "submitted"); assert.match(String(pending.note), /Do not resend/);
  const reverted = harness({ receipt: async () => ({ status: "reverted" }) });
  assert.equal((await reverted.base.transfer("u", "p", "purpose")).status, "failed");
  assert.deepEqual(reverted.finished.map((f) => f.status), ["unknown", "submitted", "failed"]);
});

test("an expired or reused preview cannot send", async () => {
  const h = harness({ reserve: false });
  await assert.rejects(h.base.transfer("u", "p", "purpose"), /expired, already used/);
  assert.equal(h.signed.length, 0);
});

test("Base rejects a wrong RPC chain, changed sender, low ETH and increased fees before signing", async () => {
  await assert.rejects(harness({ chainId: 5042 }).base.preview("u", TO, "1"), /not Base mainnet/);
  for (const [opts, reason] of [
    [{ chainId: 5042 }, /not Base mainnet/],
    [{ changedWallet: true }, /wallet changed/],
    [{ eth: 0n }, /insufficient ETH/],
    [{ balance: 0n }, /insufficient USDC/],
  ] as const) {
    const h = harness(opts);
    await assert.rejects(h.base.transfer("u", "p", "purpose"), reason);
    assert.equal(h.signed.length, 0);
  }
  const h = harness({ feeIncrease: true });
  await h.base.preview("u", TO, "1");
  await assert.rejects(h.base.transfer("u", "p", "purpose"), /gas fee increased/);
  assert.equal(h.signed.length, 0);
});

test("an audit outage after signing returns unknown with the hash and never broadcasts without persistence", async () => {
  const h = harness({ auditFailure: true });
  const original = console.error; console.error = () => {};
  try {
    const result = await h.base.transfer("u", "p", "purpose");
    assert.equal(result.status, "unknown");
    assert.equal(result.tx_hash, keccak256("0x02f8deadbeef"));
    assert.equal(h.sentCount(), 0);
  } finally { console.error = original; }
});
