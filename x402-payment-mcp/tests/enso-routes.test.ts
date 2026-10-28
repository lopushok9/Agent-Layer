import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, encodeAbiParameters, encodeFunctionData, erc20Abi, parseAbi, type Address } from "viem";
import { ENSO_ROUTER, ENSO_SHORTCUTS, EnsoRoutes, verifyRoute } from "../src/enso-routes.js";
import { assetChangesWithinPreview } from "../src/asset-changes.js";

const account = "0x1111111111111111111111111111111111111111" as Address;
const usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913" as Address;
const vault = "0x0FaBfEAcedf47e890c50C8120177fff69C6a1d9B" as Address;
const native = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE" as Address;
const routerAbi = parseAbi([
  "function safeRouteSingle((uint8 tokenType, bytes data) tokenIn, (uint8 tokenType, bytes data) tokenOut, address receiver, bytes data) payable returns (bytes)",
  "function routeSingle((uint8 tokenType, bytes data) tokenIn, bytes data) payable returns (bytes)",
]);
const erc20 = (token: Address, amount: bigint) => ({ tokenType: 1, data: encodeAbiParameters([{ type: "address" }, { type: "uint256" }], [token, amount]) });
const nativeToken = (amount: bigint) => ({ tokenType: 0, data: encodeAbiParameters([{ type: "uint256" }], [amount]) });
function response(o: { tokenIn?: any; tokenOut?: any; receiver?: Address; to?: string; value?: string; amountOut?: string; fn?: "routeSingle" } = {}) {
  const data = o.fn === "routeSingle"
    ? encodeFunctionData({ abi: routerAbi, functionName: "routeSingle", args: [o.tokenIn ?? erc20(usdc, 1_000_000n), "0x1234"] })
    : encodeFunctionData({ abi: routerAbi, functionName: "safeRouteSingle", args: [o.tokenIn ?? erc20(usdc, 1_000_000n), o.tokenOut ?? erc20(vault, 995n), o.receiver ?? account, "0x1234"] });
  return { tx: { to: o.to ?? ENSO_ROUTER, from: account, data, value: o.value ?? "0" }, amountOut: o.amountOut ?? "1000", priceImpact: 3, route: [{ action: "deposit", protocol: "morpho-blue", tokenIn: [usdc], tokenOut: [vault] }] };
}
const want = { account, tokenIn: usdc, tokenOut: vault, amountIn: 1_000_000n, slippageBps: 50 };

test("only a safeRouteSingle on EnsoRouter with the requested input, this receiver and an on-chain minimum within slippage is accepted", () => {
  assert.equal(verifyRoute(response(), want).minimum, 995n);
  const cases: [Parameters<typeof response>[0], RegExp][] = [
    [{ to: "0x3333333333333333333333333333333333333333" }, /does not call the EnsoRouter/],
    [{ fn: "routeSingle" }, /not a safeRouteSingle/],
    [{ receiver: "0x3333333333333333333333333333333333333333" }, /another address/],
    [{ tokenIn: erc20(usdc, 2_000_000n) }, /does not match the request/],
    [{ tokenIn: erc20(vault, 1_000_000n) }, /does not match the request/],
    [{ tokenOut: erc20(usdc, 995n) }, /does not match the request/],
    [{ tokenOut: erc20(vault, 994n) }, /below the requested slippage/],
    [{ tokenOut: erc20(vault, 1001n) }, /does not match the request/],
    [{ tokenOut: erc20(vault, 0n) }, /does not match the request/],
    [{ value: "1" }, /does not match the request/],
    [{ tokenOut: { tokenType: 2, data: "0x" } }, /does not match the request/],
  ];
  for (const [o, re] of cases) assert.throws(() => verifyRoute(response(o), want), re, JSON.stringify(o));
  assert.throws(() => verifyRoute({ tx: { from: "0x3333333333333333333333333333333333333333", to: ENSO_ROUTER, data: response().tx.data } } as any, want), /does not match/);
});

test("native input must equal msg.value and native output decodes its minimum", () => {
  const n = { ...want, tokenIn: native, tokenOut: usdc };
  assert.equal(verifyRoute(response({ tokenIn: nativeToken(0n), tokenOut: erc20(usdc, 995n), value: "1000000" }), n).value, 1_000_000n);
  assert.throws(() => verifyRoute(response({ tokenIn: nativeToken(0n), tokenOut: erc20(usdc, 995n), value: "999999" }), n), /does not match/);
  const out = { ...want, tokenOut: native };
  assert.equal(verifyRoute(response({ tokenOut: nativeToken(995n) }), out).minimum, 995n);
});

function harness(allowance: bigint, shortcuts: string = ENSO_SHORTCUTS) {
  const prepared: any[] = []; const bodies: any[] = [];
  const rpc = { getChainId: async () => 8453, readContract: async (p: { functionName: string; args?: unknown[] }) => p.functionName === "shortcuts" ? shortcuts : allowance };
  const wallets = { account: async () => ({ address: account }), rpc: () => rpc };
  const transactions = { prepare: async (_u: string, input: any, terms: any) => { prepared.push({ input, terms }); return { operation_id: "op" }; } };
  const fetcher = async (_url: string, init: { body: string; headers: Record<string, string> }) => { bodies.push({ body: JSON.parse(init.body), auth: init.headers.authorization }); return { ok: true, status: 200, json: async () => response() }; };
  return { prepared, bodies, routes: new EnsoRoutes(wallets as any, transactions as any, "key", fetcher as any) };
}

test("the preview asks Enso for router strategy to this account and adds only the exact approval it needs", async () => {
  const h = harness(0n);
  const r = await h.routes.preview("alice", { network: "base", token_in: usdc, amount_in: "1000000", token_out: vault });
  assert.deepEqual(h.bodies[0].body, { chainId: 8453, fromAddress: account, receiver: account, spender: account, refundReceiver: account, routingStrategy: "router", tokenIn: [usdc], tokenOut: [vault], amountIn: ["1000000"], slippage: "50" });
  assert.equal(h.bodies[0].auth, "Bearer key");
  const calls = h.prepared[0].input.calls;
  assert.equal(calls.length, 2);
  assert.deepEqual(decodeFunctionData({ abi: erc20Abi, data: calls[0].data }).args, [ENSO_ROUTER, 1_000_000n]);
  assert.equal(calls[1].to, ENSO_ROUTER);
  assert.deepEqual(h.prepared[0].terms.floors, { [vault.toLowerCase()]: "995" });
  assert.equal(r.route.minimum_output, "995"); assert.equal(r.route.expected_output, "1000");
  const partial = harness(5n); await partial.routes.preview("alice", { network: "base", token_in: usdc, amount_in: "1000000", token_out: vault });
  assert.deepEqual(partial.prepared[0].input.calls.slice(0, 2).map((c: any) => decodeFunctionData({ abi: erc20Abi, data: c.data }).args[1]), [0n, 1_000_000n], "nonzero allowance is reset first");
  const enough = harness(10n ** 18n); await enough.routes.preview("alice", { network: "base", token_in: usdc, amount_in: "1000000", token_out: vault });
  assert.equal(enough.prepared[0].input.calls.length, 1);
  await assert.rejects(harness(0n, "0x3333333333333333333333333333333333333333").routes.preview("alice", { network: "base", token_in: usdc, amount_in: "1000000", token_out: vault }), /expected deployment/);
});

test("execution compares a route's output with its on-chain minimum, every other token strictly", () => {
  const preview = [{ token: { address: vault.toLowerCase() }, value: { diff: "1000" } }, { token: { address: usdc.toLowerCase() }, value: { diff: "-1000000" } }];
  const fresh = (out: string, spent = "-1000000") => [{ token: { address: vault.toLowerCase() }, value: { diff: out } }, { token: { address: usdc.toLowerCase() }, value: { diff: spent } }];
  const floors = { [vault.toLowerCase()]: 995n };
  assert.equal(assetChangesWithinPreview(preview, fresh("996")), false, "without a floor a lower output fails");
  assert.equal(assetChangesWithinPreview(preview, fresh("996"), floors), true);
  assert.equal(assetChangesWithinPreview(preview, fresh("994"), floors), false);
  assert.equal(assetChangesWithinPreview(preview, fresh("1000", "-1000001"), floors), false, "input stays strict");
  assert.equal(assetChangesWithinPreview(preview, fresh("996"), { [vault.toLowerCase()]: 2000n }), false, "a floor above the preview is ignored");
});
