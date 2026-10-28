import assert from "node:assert/strict";
import test from "node:test";
import { ManagedSwapService, validateSwapQuote, type SwapQuote } from "../src/managed-swaps.js";
import { NATIVE_TOKEN, PERMIT2, normalizeSwap, swapFingerprint, type SwapPlan } from "../src/swap-plan.js";
import { jsonValue, normalizeTransaction } from "../src/transaction-builder.js";
import { SmartWalletService } from "../src/smart-wallet.js";

const account = "0x1111111111111111111111111111111111111111";
const owner = "0x2222222222222222222222222222222222222222";
const sell = "0x3333333333333333333333333333333333333333";
const buy = "0x4444444444444444444444444444444444444444";
const router = "0x5555555555555555555555555555555555555555";
const hash = `0x${"a".repeat(64)}` as const;
const plan: SwapPlan = { network: "base", account, fromToken: sell, toToken: buy, fromAmount: "100", slippageBps: 100, minimumOutput: "990" };
function quote(): SwapQuote {
  return { liquidityAvailable: true, network: "base", fromToken: sell, toToken: buy, fromAmount: 100n, toAmount: 1000n, minToAmount: 990n, blockNumber: 1n, fees: {}, issues: { simulationIncomplete: false }, transaction: { to: router, data: "0x12345678", value: 0n, gas: 123n, gasPrice: 2n }, permit2: { eip712: { domain: { name: "Permit2", chainId: 8453, verifyingContract: PERMIT2 }, types: { PermitTransferFrom: [{ name: "permitted", type: "TokenPermissions" }, { name: "spender", type: "address" }, { name: "nonce", type: "uint256" }, { name: "deadline", type: "uint256" }], TokenPermissions: [{ name: "token", type: "address" }, { name: "amount", type: "uint256" }] }, primaryType: "PermitTransferFrom", message: { permitted: { token: sell, amount: "100" }, spender: router, nonce: "0", deadline: String(Math.floor(Date.now() / 1000) + 600) } } }, execute: async () => { throw new Error("quote.execute must not be used"); } };
}

test("swap intent binds tokens, chain, input, slippage and a fixed output floor", () => {
  assert.equal(normalizeSwap({ network: "base", from_token: sell, to_token: buy, from_amount_atomic: "100" }, account).slippageBps, 100);
  for (const change of [{ minimumOutput: "991" }, { fromAmount: "101" }, { toToken: sell as `0x${string}` }, { network: "ethereum" as const }, { slippageBps: 200 }]) assert.notEqual(swapFingerprint(plan), swapFingerprint({ ...plan, ...change }));
  for (const change of [{ from_amount_atomic: "0" }, { from_amount_atomic: "1.2" }, { to_token: sell }, { slippage_bps: 501 }, { recipient: owner }]) assert.throws(() => normalizeSwap({ network: "base", from_token: sell, to_token: buy, from_amount_atomic: "100", ...change } as any, account));
});

test("fresh quotes cannot lower the floor, change assets, require extra ETH or widen Permit2", () => {
  assert.doesNotThrow(() => validateSwapQuote(plan, quote(), owner));
  for (const mutate of [
    (q: SwapQuote) => { q.minToAmount = 989n; },
    (q: SwapQuote) => { q.fromAmount = 101n; },
    (q: SwapQuote) => { q.network = "ethereum"; },
    (q: SwapQuote) => { q.transaction!.value = 1n; },
    (q: SwapQuote) => { q.issues.allowance = { currentAllowance: 0n, spender: PERMIT2 }; },
    (q: SwapQuote) => { q.issues.simulationIncomplete = true; },
    (q: SwapQuote) => { q.permit2!.eip712.domain.chainId = 1; },
    (q: SwapQuote) => { q.permit2!.eip712.domain.verifyingContract = router; },
    (q: SwapQuote) => { (q.permit2!.eip712.message.permitted as any).amount = "101"; },
    (q: SwapQuote) => { q.permit2!.eip712.message.deadline = "1"; },
  ]) { const q = quote(); mutate(q); assert.throws(() => validateSwapQuote(plan, q, owner)); }
  const native = quote(); native.fromToken = NATIVE_TOKEN; native.transaction!.value = 100n; delete native.permit2;
  assert.doesNotThrow(() => validateSwapQuote({ ...plan, fromToken: NATIVE_TOKEN }, native, owner));
});

test("CDP quote uses controlled Permit2 signing and the transparent executor, never SDK swap()", async () => {
  const order: string[] = [];
  let q = quote();
  let priceOut = 1000n; const requestedSlippage: number[] = [];
  const smart = { address: account, owners: [{ address: owner }], quoteSwap: async ({ slippageBps }: any) => { order.push("quote"); requestedSlippage.push(slippageBps); return q; }, swap: async () => { throw new Error("opaque SDK swap must never execute"); } };
  const wallets = new SmartWalletService({ WALLET_OPERATION_ENCRYPTION_KEY: Buffer.alloc(32, 1).toString("base64") } as any, { wallet: async () => null, saveWallet: async () => {} }, { evm: { getOrCreateAccount: async () => smart.owners[0], getOrCreateSmartAccount: async () => smart, getSwapPrice: async () => ({ liquidityAvailable: true, toAmount: priceOut }) } } as any);
  wallets.rpc = (() => ({ getChainId: async () => 8453 })) as any;
  wallets.signSwapPermit = async () => { order.push("permit-sign"); return "0x1234"; };
  wallets.send = async (_user, _network, calls, _id, before) => {
    assert.equal(calls.length, 1); assert.equal(calls[0]!.to, router);
    assert.equal(calls[0]!.value, "0"); assert.ok(calls[0]!.data.endsWith("1234"));
    await before(hash); order.push("submit"); return { userOpHash: hash };
  };
  await wallets.swap("user", plan, "id", async () => { order.push("persist-permit"); }, async () => { order.push("persist-userop"); });
  assert.deepEqual(order, ["quote", "persist-permit", "permit-sign", "persist-userop", "submit"]);
  assert.deepEqual(requestedSlippage, [100]);
  // The market moved 0.5% against the user: the 990 floor is still reachable,
  // so CDP is asked for 50 bps and its minimum lands on the floor.
  order.length = 0; priceOut = 995n; q = quote(); q.toAmount = 995n; q.minToAmount = 990n;
  await wallets.swap("user", plan, "id", async () => {}, async () => {});
  assert.equal(requestedSlippage.at(-1), 50);
  order.length = 0; priceOut = 989n;
  await assert.rejects(wallets.swap("user", plan, "id", async () => {}, async () => {}), /below the confirmed minimum/);
  assert.deepEqual(order, [], "an unreachable floor stops before a firm quote");
  order.length = 0; priceOut = 1000n; q = quote(); q.toAmount = 999n; q.minToAmount = 989n;
  await assert.rejects(wallets.swap("user", plan, "id", async () => {}, async () => {}), /below the confirmed minimum/);
  assert.deepEqual(order, ["quote"], "a firm quote below the floor is still refused");
  q = quote(); order.length = 0;
  await assert.rejects(wallets.swap("user", plan, "id", async () => { throw new Error("database unavailable"); }, async () => {}), /database unavailable/);
  assert.deepEqual(order, ["quote"]);
});

test("swap preview never signs, allowance is explicit, and timeouts after Permit2 remain unknown", async () => {
  let op: any;
  let signatures = 0;
  const q = quote(); q.issues.allowance = { spender: PERMIT2, currentAllowance: 0n };
  const store = {
    createOperation: async (p: any) => { op = { ...p, id: "id", status: "prepared", expiresAt: new Date(Date.now() + 60000), userOpHash: null, transactionHash: null, error: null }; return op; },
    reserve: async (user: string, _id: string, _purpose: string, kind: string) => { if (user !== "alice" || kind !== op.kind) throw new Error("not found"); if (op.status !== "prepared") throw new Error("consumed"); op.status = "reserved"; return op; },
    beforeSwapSigning: async () => { op.status = "signing"; },
    beforeSigning: async () => { throw new Error("must not reach UserOp signing"); },
    finish: async (_id: string, status: string) => { op.status = status; },
    operation: async (user: string) => user === "alice" ? op : null,
    interruptedOperations: async () => [],
    failInterrupted: async () => { throw new Error("must not resolve a live operation"); },
  };
  const backend = { account: async () => ({ address: account }), swapPrice: async () => q, swap: async (_user: string, _plan: any, _id: string, beforePermit: any) => { await beforePermit({}); signatures++; throw new Error("response lost after Permit2 signing"); } };
  const swaps = new ManagedSwapService(backend as any, store as any, { withPaymentLock: async (_u, action) => action() }, 600);
  const preview = await swaps.preview("alice", { network: "base", from_token: sell, to_token: buy, from_amount_atomic: "100" });
  assert.equal(signatures, 0); assert.equal((preview.simulation as any).approval_required, true);
  assert.equal((preview.simulation as any).approval_details.amount_atomic, "100");
  assert.doesNotThrow(() => normalizeTransaction({ network: "base", calls: [(preview.simulation as any).approval_call] }, account, owner), "approval_call must be accepted unchanged by the generic builder");
  await assert.rejects(swaps.execute("bob", "id", "foreign"), /not found/);
  assert.equal((await swaps.execute("alice", "id", "test")).status, "unknown");
  assert.equal(op.userOpHash, null, "Permit2 can have been signed before a UserOperation hash exists");
  await assert.rejects(swaps.execute("alice", "id", "retry"), /consumed/);
  assert.equal(signatures, 1);
});

test("execution slippage lands the on-chain minimum on the confirmed floor and never exceeds approval", async () => {
  const { executionSlippageBps } = await import("../src/swap-plan.js");
  assert.equal(executionSlippageBps(1000n, 990n, 100), 100);
  assert.equal(executionSlippageBps(2000n, 990n, 100), 100, "a better market never widens the approved tolerance");
  assert.equal(executionSlippageBps(995n, 990n, 100), 50);
  assert.equal(executionSlippageBps(990n, 990n, 100), 0);
  for (const out of [995n, 1003n, 123456789n]) { const s = executionSlippageBps(out, 990n, 500); assert.ok(out * BigInt(10_000 - s) / 10_000n >= 990n); }
  assert.throws(() => executionSlippageBps(989n, 990n, 100), /below the confirmed minimum/);
});
