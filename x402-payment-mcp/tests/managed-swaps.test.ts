import assert from "node:assert/strict";
import test from "node:test";
import { ManagedSwapService, validateSwapQuote, type SwapQuote } from "../src/managed-swaps.js";
import { NATIVE_TOKEN, PERMIT2, normalizeSwap, swapFingerprint, type SwapPlan } from "../src/swap-plan.js";
import { jsonValue } from "../src/transaction-builder.js";
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

test("actual CDP SDK swap persists before Permit2 and UserOperation signing, without an uncontrolled inline quote", async () => {
  const { toEvmSmartAccount } = await import(new URL("./accounts/evm/toEvmSmartAccount.js", import.meta.resolve("@coinbase/cdp-sdk")).href);
  const order: string[] = [];
  const signer = { address: owner, sign: async () => { order.push("userop-sign"); return "0x12"; } };
  let q = quote();
  const api = {
    createEvmSwapQuote: async (body: any, key: string) => { assert.equal(body.taker, account); assert.equal(body.signerAddress, owner); assert.match(key, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/); assert.notEqual(key,"operation-id"); order.push("quote"); return jsonValue(q); },
    signEvmTypedData: async (address: string, data: any) => { assert.equal(address, owner); assert.equal(data.domain.verifyingContract, account); order.push("permit-sign"); return { signature: `0x${"ab".repeat(64)}1b` }; },
    prepareUserOperation: async (_address: string, body: any) => { assert.equal(body.calls.length, 1); assert.equal(body.calls[0].to, router); return { userOpHash: hash }; },
    sendUserOperation: async (_address: string, h: string, _body: any, key: string) => { assert.equal(h, hash); assert.equal(key, "operation-id"); order.push("submit"); return { status: "broadcast" }; },
  };
  const smart = toEvmSmartAccount(api, { smartAccount: { address: account }, owner: signer });
  const cdp = { evm: { getOrCreateAccount: async () => signer, getOrCreateSmartAccount: async () => smart } };
  const wallets = new SmartWalletService({ BASE_PAYMASTER_URL: "https://paymaster.example" } as any, { wallet: async () => null, saveWallet: async () => {} }, cdp as any);
  wallets.rpc = (() => ({ getChainId: async () => 8453 })) as any;
  await wallets.swap("user", plan, "operation-id", async () => { order.push("persist-permit"); }, async h => { assert.equal(h, hash); order.push("persist-userop"); });
  assert.deepEqual(order, ["quote", "persist-permit", "permit-sign", "persist-userop", "userop-sign", "submit"]);
  assert.equal(smart.owners[0], signer, "request-local signing wrapper is restored");
  order.length = 0; q = quote(); q.toAmount = 999n; q.minToAmount = 989n;
  await assert.rejects(wallets.swap("user", plan, "operation-id", async () => { order.push("persist-permit"); }, async () => {}), /below the confirmed minimum/);
  assert.deepEqual(order, ["quote"], "worsened quote never reaches any signing API");
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
  };
  const backend = { account: async () => ({ address: account }), swapPrice: async () => q, swap: async (_user: string, _plan: any, _id: string, beforePermit: any) => { await beforePermit({}); signatures++; throw new Error("response lost after Permit2 signing"); } };
  const swaps = new ManagedSwapService(backend as any, store as any, { withPaymentLock: async (_u, action) => action() }, 600);
  const preview = await swaps.preview("alice", { network: "base", from_token: sell, to_token: buy, from_amount_atomic: "100" });
  assert.equal(signatures, 0); assert.equal((preview.simulation as any).approval_required, true);
  assert.equal((preview.simulation as any).approval_call.amount_atomic, "100");
  await assert.rejects(swaps.execute("bob", "id", "foreign"), /not found/);
  assert.equal((await swaps.execute("alice", "id", "test")).status, "unknown");
  assert.equal(op.userOpHash, null, "Permit2 can have been signed before a UserOperation hash exists");
  await assert.rejects(swaps.execute("alice", "id", "retry"), /consumed/);
  assert.equal(signatures, 1);
});
