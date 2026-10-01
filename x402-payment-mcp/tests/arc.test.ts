import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, erc20Abi, keccak256, type TransactionSerializable } from "viem";
import { ArcService, normalizeRecipient, parseUsdcAmount, type ArcChain } from "../src/arc.js";
import { ARC_CHAIN_ID, ARC_USDC, type Config } from "../src/config.js";
import type { Store } from "../src/store.js";

const SELF = "0x1111111111111111111111111111111111111111";
const TO = "0x2222222222222222222222222222222222222222";
const config = { ARC_MAX_TRANSFER_USDC_ATOMIC: "50000000", ARC_MAX_DAILY_TRANSFER_USDC_ATOMIC: "200000000", PREVIEW_TTL_SECONDS: 120 } as Config;

function harness(opts: { balance?: bigint; usedToday?: bigint; sign?: (tx: TransactionSerializable) => Promise<`0x${string}`>; send?: () => Promise<`0x${string}`>; receipt?: () => Promise<{ status: "success" | "reverted" }>; reserve?: boolean } = {}) {
  const finished: { status: string; hash: string | null; error: string | null }[] = [];
  const signed: TransactionSerializable[] = [];
  let preview: { to: string; amount: bigint; fee: bigint } | null = null;
  const store = {
    arcTransferredToday: async () => opts.usedToday ?? 0n,
    createArcPreview: async (p: { to: string; amount: bigint; fee: bigint }) => { preview = p; return { id: "11111111-1111-4111-8111-111111111111", expiresAt: new Date() }; },
    reserveArcTransfer: async () => (opts.reserve === false ? null : { transferId: "t1", to: preview?.to ?? TO, amount: preview?.amount ?? 5_000_000n }),
    finishArcTransfer: async (_id: string, status: string, hash: string | null, error: string | null) => { finished.push({ status, hash, error }); },
    withPaymentLock: async <T>(_u: string, action: () => Promise<T>) => action(),
  } as unknown as Store;
  let sent = 0;
  const chain = {
    readContract: async () => opts.balance ?? 100_000_000n,
    estimateGas: async () => 60_000n,
    estimateFeesPerGas: async () => ({ maxFeePerGas: 20_000_000_000n, maxPriorityFeePerGas: 1_000_000_000n }),
    getTransactionCount: async () => 7,
    sendRawTransaction: async () => { sent++; return opts.send ? opts.send() : ("0xabc" as `0x${string}`); },
    waitForTransactionReceipt: async () => (opts.receipt ? opts.receipt() : { status: "success" }),
  } as unknown as ArcChain;
  const signer = { address: SELF, signTransaction: async (tx: TransactionSerializable) => { signed.push(tx); return opts.sign ? opts.sign(tx) : ("0x02f8deadbeef" as `0x${string}`); } };
  const arc = new ArcService(config, store, async () => signer, chain);
  return { arc, finished, signed, sentCount: () => sent, preview: () => preview };
}

test("amounts and recipients are validated strictly", () => {
  assert.equal(parseUsdcAmount("1.5"), 1_500_000n);
  assert.equal(parseUsdcAmount("0.000001"), 1n);
  for (const bad of ["0", "-1", "1.1234567", "abc", "1e3", ""]) assert.throws(() => parseUsdcAmount(bad), bad);
  assert.equal(normalizeRecipient(TO.toUpperCase().replace("0X", "0x"), SELF), "0x2222222222222222222222222222222222222222");
  assert.throws(() => normalizeRecipient("0x0000000000000000000000000000000000000000", SELF), /zero address/);
  assert.throws(() => normalizeRecipient(SELF, SELF), /own address/);
  assert.throws(() => normalizeRecipient(ARC_USDC, SELF), /token contract/);
  assert.throws(() => normalizeRecipient("0x123", SELF), /20-byte/);
});

test("preview enforces per-transfer, daily, and balance-plus-fee limits", async () => {
  await assert.rejects(harness().arc.preview("u", TO, "50.000001"), /per-transfer limit/);
  await assert.rejects(harness({ usedToday: 180_000_000n }).arc.preview("u", TO, "25"), /remaining daily limit of 20 USDC/);
  await assert.rejects(harness({ balance: 4_000_000n }).arc.preview("u", TO, "5"), /insufficient balance/);
  // fee = 60k gas * 20 gwei = 1.2e15 native wei = 0.0012 USDC
  await assert.rejects(harness({ balance: 5_000_000n }).arc.preview("u", TO, "5"), /amount plus network fee \(~0.0012 USDC\)/);
  const h = harness();
  const result = await h.arc.preview("u", TO, "5");
  assert.equal(result.amount_usdc, "5"); assert.equal(result.max_network_fee_usdc, "0.0012"); assert.match(result.next_step, /Nothing has been signed/);
  assert.deepEqual(h.preview(), { userId: "u", to: TO, amount: 5_000_000n, fee: 1200n });
  assert.equal(h.signed.length, 0, "preview never signs");
});

test("transfer signs exactly one Arc USDC transfer and records its outcome", async () => {
  const h = harness();
  await h.arc.preview("u", TO, "5");
  const result = await h.arc.transfer("u", "11111111-1111-4111-8111-111111111111", "pay the designer");
  assert.equal(result.status, "confirmed");
  assert.equal(h.signed.length, 1);
  const tx = h.signed[0]!;
  assert.equal(tx.chainId, ARC_CHAIN_ID); assert.equal(tx.to, ARC_USDC); assert.equal(tx.value, 0n); assert.equal(tx.type, "eip1559"); assert.equal(tx.nonce, 7); assert.equal(tx.gas, 72_000n);
  const call = decodeFunctionData({ abi: erc20Abi, data: tx.data! });
  assert.equal(call.functionName, "transfer"); assert.deepEqual(call.args, [TO, 5_000_000n]);
  const hash = keccak256("0x02f8deadbeef");
  assert.equal(result.tx_hash, hash);
  assert.deepEqual(h.finished.map((f) => f.status), ["submitted", "confirmed"]);
});

test("a signing failure is recorded as failed and nothing is broadcast", async () => {
  const h = harness({ sign: async () => { throw new Error("CDP rejected"); } });
  await assert.rejects(h.arc.transfer("u", "p", "purpose"), /CDP rejected/);
  assert.equal(h.sentCount(), 0); assert.deepEqual(h.finished, [{ status: "failed", hash: null, error: "CDP rejected" }]);
});

test("a broadcast failure after signing is unknown, never failed, and keeps the hash", async () => {
  const h = harness({ send: async () => { throw new Error("rpc timeout"); } });
  await assert.rejects(h.arc.transfer("u", "p", "purpose"), /rpc timeout/);
  assert.equal(h.finished[0]!.status, "unknown"); assert.equal(h.finished[0]!.hash, keccak256("0x02f8deadbeef"));
});

test("an unconfirmed broadcast is reported as submitted and a reverted one as failed", async () => {
  const pending = await harness({ receipt: async () => { throw new Error("timeout"); } }).arc.transfer("u", "p", "purpose");
  assert.equal(pending.status, "submitted"); assert.match(String(pending.note), /Do not resend/);
  const reverted = harness({ receipt: async () => ({ status: "reverted" }) });
  assert.equal((await reverted.arc.transfer("u", "p", "purpose")).status, "failed");
  assert.deepEqual(reverted.finished.map((f) => f.status), ["submitted", "failed"]);
});

test("an expired or reused preview cannot send", async () => {
  const h = harness({ reserve: false });
  await assert.rejects(h.arc.transfer("u", "p", "purpose"), /expired, already used/);
  assert.equal(h.signed.length, 0);
});
