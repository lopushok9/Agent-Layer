import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, encodeAbiParameters, encodeFunctionData, erc20Abi, parseAbi, type Address } from "viem";
import { EnsoCatalog } from "../src/enso-catalog.js";
import { ENSO_ROUTER, ENSO_SHORTCUTS, EnsoApi, EnsoRoutes } from "../src/enso-routes.js";

const account = "0x1111111111111111111111111111111111111111" as Address;
const usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913" as Address;
const vault = "0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61" as Address;
const routerAbi = parseAbi([
  "function safeRouteSingle((uint8 tokenType, bytes data) tokenIn, (uint8 tokenType, bytes data) tokenOut, address receiver, bytes data) payable returns (bytes)",
  "function routeSingle((uint8 tokenType, bytes data) tokenIn, bytes data) payable returns (bytes)",
]);
const erc20 = (token: Address, amount: bigint) => ({ tokenType: 1, data: encodeAbiParameters([{ type: "address" }, { type: "uint256" }], [token, amount]) });
const chain = (...ids: number[]) => ids.map(id => ({ id, name: String(id) }));
const standards = [
  { protocol: { slug: "erc4626", url: "https://eips.ethereum.org/EIPS/eip-4626" }, forks: [{ slug: "morpho-blue-vaults", url: "https://morpho.org" }], actions: [{ action: "deposit", supportedChains: chain(1, 8453) }, { action: "redeem", supportedChains: chain(1, 8453) }] },
  { protocol: { slug: "aave-v3" }, actions: [{ action: "deposit", supportedChains: chain(8453) }, { action: "borrow", supportedChains: chain(8453) }, { action: "harvest", supportedChains: chain(8453) }] },
  { protocol: { slug: "eth-only" }, actions: [{ action: "deposit", supportedChains: chain(1) }] },
];
const actions = [
  { action: "deposit", inputs: { tokenIn: { type: "AddressArg" }, amountIn: { type: "NumberArg" }, primaryAddress: { type: "AddressArg" }, receiver: { type: "AccountArg", optional: true }, onBehalfOf: { type: "AddressArg", optional: true } } },
  { action: "swap", inputs: { tokenIn: { type: "AddressArg" }, maxAmountOut: { type: "NumberArg", optional: true }, poolFee: { type: "Static<NumberArg>", optional: true } } },
  { action: "borrow", inputs: { tokenOut: { type: "AddressArg" } } },
];

function api(handler: (url: URL, init: any) => unknown, intervalMs = 0) {
  const calls: { url: URL; init: any; at: number }[] = [];
  const fetcher = async (url: string, init: any) => { const u = new URL(url); calls.push({ url: u, init, at: Date.now() }); const body = handler(u, init); return { ok: true, status: 200, json: async () => body }; };
  return { calls, api: new EnsoApi("key", fetcher as any, intervalMs) };
}
const catalogApi = () => api(u => u.pathname.endsWith("/standards") ? standards : u.pathname.endsWith("/actions") ? actions : []);

test("requests share one queue spaced by the plan's rate limit", async () => {
  const h = api(() => ({}), 120);
  await Promise.all([h.api.get("a", {}), h.api.get("b", {}), h.api.get("c", {})]);
  assert.deepEqual(h.calls.map(c => c.url.pathname.split("/").pop()), ["a", "b", "c"]);
  for (let i = 1; i < 3; i++) assert.ok(h.calls[i]!.at - h.calls[i - 1]!.at >= 110, "at least the interval apart");
  const limited = new EnsoApi("key", (async () => ({ ok: false, status: 429, json: async () => ({}) })) as any, 0);
  await assert.rejects(limited.get("tokens", {}), /rate limit/, "a second 429 in a row is reported");
});

test("the catalog offers only router-safe actions on the requested chain, forks included, without inputs the wallet fixes", async () => {
  const h = catalogApi();
  const c = new EnsoCatalog(h.api);
  const r = await c.catalog({ network: "base" });
  assert.deepEqual(r.protocols.map(p => [p.protocol, p.actions]), [["erc4626", ["deposit", "redeem"]], ["morpho-blue-vaults", ["deposit", "redeem"]], ["aave-v3", ["deposit"]]]);
  assert.deepEqual(Object.keys(r.inputs).sort(), ["deposit", "swap"], "borrow inputs are not offered");
  assert.deepEqual(Object.keys(r.inputs.deposit!), ["tokenIn", "amountIn", "primaryAddress"]);
  assert.deepEqual(Object.keys(r.inputs.swap!), ["tokenIn", "poolFee"], "maxAmountOut is never offered");
  assert.equal((await c.catalog({ network: "base", protocol: "morpho" })).protocols.length, 1);
  assert.equal(await c.supported("base", "morpho-blue-vaults", "deposit"), true);
  assert.equal(await c.supported("base", "aave-v3", "borrow"), true, "supported() only reflects Enso; action_preview's enum excludes borrow");
  assert.equal(await c.supported("base", "eth-only", "deposit"), false);
  await c.catalog({ network: "ethereum" });
  assert.equal(h.calls.length, 2, "standards and actions are cached");
});

test("positions are filtered by Enso, sorted by TVL, bounded and cached", async () => {
  const rows = [
    { address: vault, symbol: "gtUSDCp", project: "morpho", protocol: "morpho-blue-vaults", primaryAddress: vault, apy: 5.15, tvl: 405e6, decimals: 18, underlyingTokens: [{ address: usdc, symbol: "USDC", decimals: 6 }] },
    { address: "0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB", symbol: "aBasUSDC", protocol: "aave-v3", primaryAddress: "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5", apy: 5.03, tvl: 17e6, decimals: 6 },
    { address: "not-an-address", tvl: 1e12 },
  ];
  let now = 0;
  const h = api(() => ({ data: rows }));
  const c = new EnsoCatalog(h.api, () => now);
  const r = await c.positions({ network: "base", underlying_token: usdc, min_tvl_usd: 5e6, limit: 5 });
  assert.equal(h.calls[0]!.url.searchParams.get("underlyingTokens"), usdc);
  assert.equal(h.calls[0]!.url.searchParams.get("tvlFrom"), "5000000");
  assert.equal(h.calls[0]!.url.searchParams.get("chainId"), "8453");
  assert.deepEqual(r.positions.map(p => p.symbol), ["gtUSDCp", "aBasUSDC"], "invalid rows dropped, sorted by TVL");
  assert.equal(r.positions[0]!.primary_address, vault);
  assert.deepEqual(r.positions[0]!.underlying, [{ token: usdc, symbol: "USDC", decimals: 6 }]);
  await c.positions({ network: "base", underlying_token: usdc, min_tvl_usd: 5e6, limit: 5 });
  assert.equal(h.calls.length, 1);
  now = 6 * 60_000;
  await c.positions({ network: "base", underlying_token: usdc, min_tvl_usd: 5e6 });
  assert.equal(h.calls.length, 2, "refreshed after five minutes");
});

test("positions collect pages before sorting and paginate the cached sample with missing APY last", async () => {
  const first = Array.from({ length: 1000 }, (_, i) => ({ address: `0x${(i + 1).toString(16).padStart(40, "0")}`, tvl: i, apy: i === 0 ? null : i }));
  const h = api(u => u.searchParams.get("page") === "1" ? { data: first, meta: { next: 2 } } : { data: [{ address: vault, tvl: 1, apy: 2000 }], meta: { next: null } });
  const c = new EnsoCatalog(h.api, () => 1_000);
  const r = await c.positions({ network: "base", sort_by: "apy", limit: 1 });
  assert.equal(r.source_complete, true); assert.equal(r.total, 1001);
  assert.equal(r.positions[0]!.token, vault); assert.equal(r.next_offset, 1);
  assert.equal(r.truncated, true); assert.equal(r.fetched_at, new Date(1_000).toISOString());
  const last = await c.positions({ network: "base", sort_by: "apy", offset: 1000, limit: 1 });
  assert.equal(last.positions[0]!.apy, null); assert.equal(last.next_offset, null);
  assert.equal(h.calls.length, 2, "sort and offset reuse the sample");
});

test("positions report bounded source scans and reject malformed provider responses", async () => {
  const rows = Array.from({ length: 1000 }, (_, i) => ({ address: `0x${(i + 1).toString(16).padStart(40, "0")}` }));
  const h = api(u => ({ data: rows, meta: { next: Number(u.searchParams.get("page")) + 1 } }));
  const r = await new EnsoCatalog(h.api).positions({ network: "base", offset: 4999, limit: 1 });
  assert.equal(r.source_complete, false); assert.equal(r.source_pages_fetched, 5); assert.equal(r.truncated, true);
  const bad = api(() => ({ error: "unexpected" }));
  const c = new EnsoCatalog(bad.api);
  await assert.rejects(c.positions({ network: "base" }), /invalid positions response/);
  await assert.rejects(c.positions({ network: "base" }), /invalid positions response/);
  assert.equal(bad.calls.length, 2, "malformed responses are not cached");
});

function actionHarness(bundle: unknown = { tx: { to: ENSO_ROUTER, from: account, value: "0", data: encodeFunctionData({ abi: routerAbi, functionName: "routeSingle", args: [erc20(usdc, 100_000n), "0xabcd"] }) }, amountsOut: { [vault.toLowerCase()]: "1000" }, priceImpact: 1 }) {
  const prepared: any[] = []; const bodies: { url: URL; body: any }[] = [];
  const rpc = { getChainId: async () => 8453, readContract: async (p: { functionName: string }) => p.functionName === "shortcuts" ? ENSO_SHORTCUTS : 0n };
  const wallets = { account: async () => ({ address: account }), rpc: () => rpc };
  const transactions = { prepare: async (_u: string, input: any, terms: any) => { prepared.push({ input, terms }); return { operation_id: "op" }; } };
  const fetcher = async (url: string, init: any) => { bodies.push({ url: new URL(url), body: init.body ? JSON.parse(init.body) : undefined }); return { ok: true, status: 200, json: async () => bundle }; };
  return { prepared, bodies, routes: new EnsoRoutes(wallets as any, transactions as any, "key", fetcher as any, 0) };
}
const deposit = { network: "base" as const, protocol: "morpho-blue-vaults", action: "deposit" as const, token_in: usdc, amount_in: "100000", token_out: vault, primary_address: vault };

test("an action preview asks the Bundle API for the router strategy to this account and is sent as safeRouteSingle with the user's minimum", async () => {
  const h = actionHarness();
  const r = await h.routes.actionPreview("alice", deposit, async () => true);
  const q = h.bodies[0]!.url.searchParams;
  assert.equal(h.bodies[0]!.url.pathname, "/api/v1/shortcuts/bundle");
  assert.deepEqual([q.get("routingStrategy"), q.get("fromAddress"), q.get("receiver"), q.get("spender"), q.get("refundReceiver"), q.get("chainId")], ["router", account, account, account, account, "8453"]);
  assert.deepEqual(h.bodies[0]!.body, [
    { protocol: "morpho-blue-vaults", action: "deposit", args: { tokenIn: usdc, tokenOut: vault, amountIn: "100000", primaryAddress: vault } },
    { protocol: "erc20", action: "transfer", args: { token: vault, receiver: account, amount: { useOutputOfCallAt: 0 } } },
  ], "the action's whole output is transferred to this account");
  const calls = h.prepared[0].input.calls;
  assert.deepEqual(decodeFunctionData({ abi: erc20Abi, data: calls[0].data }).args, [ENSO_ROUTER, 100_000n]);
  const d = decodeFunctionData({ abi: routerAbi, data: calls[1].data });
  assert.equal(d.functionName, "safeRouteSingle");
  assert.deepEqual(d.args.slice(1, 4), [erc20(vault, 995n), account, "0xabcd"]);
  assert.deepEqual(h.prepared[0].terms.floors, { [vault.toLowerCase()]: "995" });
  assert.equal((r.route as Record<string, unknown>).protocol, "morpho-blue-vaults"); assert.equal(r.route.minimum_output, "995");
});

test("action previews refuse unsupported actions, foreign pool arguments and answers without the requested output", async () => {
  await assert.rejects(actionHarness().routes.actionPreview("alice", deposit, async () => false), /not available on this network/);
  await assert.rejects(actionHarness().routes.actionPreview("alice", { ...deposit, action: "borrow" } as any, async () => true), /Invalid/);
  await assert.rejects(actionHarness().routes.actionPreview("alice", { ...deposit, pool: { pool_fee: "500" } }, async () => true), /only to swap/);
  await assert.rejects(actionHarness().routes.actionPreview("alice", { ...deposit, pool: { max_amount_out: "1" } } as any, async () => true), /Unrecognized/);
  const noOutput = actionHarness({ tx: { to: ENSO_ROUTER, value: "0", data: encodeFunctionData({ abi: routerAbi, functionName: "routeSingle", args: [erc20(usdc, 100_000n), "0x"] }) }, amountsOut: { [usdc.toLowerCase()]: "5" } });
  await assert.rejects(noOutput.routes.actionPreview("alice", deposit, async () => true), /does not match the request/);
  const swap = actionHarness();
  await swap.routes.actionPreview("alice", { ...deposit, protocol: "uniswap-v3", action: "swap", primary_address: "0x2626664c2603336E57B271c5C0b26F421741e481", pool: { pool_fee: "500" } }, async () => true);
  assert.deepEqual(swap.bodies[0]!.body[0].args, { tokenIn: usdc, tokenOut: vault, amountIn: "100000", primaryAddress: "0x2626664c2603336E57B271c5C0b26F421741e481", slippage: "50", poolFee: "500" });
  const native = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE" as Address;
  const toEth = actionHarness({ tx: { to: ENSO_ROUTER, value: "0", data: encodeFunctionData({ abi: routerAbi, functionName: "routeSingle", args: [erc20(usdc, 100_000n), "0x"] }) }, amountsOut: { [native.toLowerCase()]: "1000" } });
  await toEth.routes.actionPreview("alice", { ...deposit, action: "redeem", token_out: native }, async () => true);
  assert.deepEqual(toEth.bodies[0]!.body, [{ protocol: "morpho-blue-vaults", action: "redeem", args: { tokenIn: usdc, tokenOut: native, amountIn: "100000", primaryAddress: vault, receiver: account } }], "native output is paid to receiver, no erc20 transfer");
});

test("native ETH from a pool that only holds WETH is swapped to WETH and unwrapped in the same route", async () => {
  const native = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE" as Address, weth = "0x4200000000000000000000000000000000000006" as Address, pool = "0xF2EcC3A2dEFB4ECC1Ac510CBbc405a539A990BE4" as Address;
  const bodies: any[] = []; let prepared: any;
  const ok = { tx: { to: ENSO_ROUTER, value: "0", data: encodeFunctionData({ abi: routerAbi, functionName: "routeSingle", args: [erc20(usdc, 100_000n), "0xbeef"] }) }, amountsOut: { [native.toLowerCase()]: "1000" } };
  const fetcher = async (_url: string, init: any) => { const body = JSON.parse(init.body); bodies.push(body); return body.length === 1 ? { ok: false, status: 422, json: async () => ({ message: "Underlying swaps are not supported" }) } : { ok: true, status: 200, json: async () => ok }; };
  const rpc = { getChainId: async () => 8453, readContract: async (p: { functionName: string }) => p.functionName === "shortcuts" ? ENSO_SHORTCUTS : 0n };
  const routes = new EnsoRoutes({ account: async () => ({ address: account }), rpc: () => rpc } as any, { prepare: async (_u: string, input: any, terms: any) => { prepared = { input, terms }; return {}; } } as any, "key", fetcher as any, 0);
  const r: any = await routes.actionPreview("alice", { network: "base", protocol: "curve-twocrypto-ng", action: "swap", token_in: usdc, amount_in: "100000", token_out: native, primary_address: pool }, async () => true);
  assert.equal(bodies.length, 2);
  assert.deepEqual(bodies[0][0].args.receiver, account, "native output is first asked for directly");
  assert.deepEqual(bodies[1], [
    { protocol: "curve-twocrypto-ng", action: "swap", args: { tokenIn: usdc, tokenOut: weth, amountIn: "100000", primaryAddress: pool, slippage: "50" } },
    { protocol: "wrapped-native", action: "redeem", args: { tokenIn: weth, tokenOut: native, amountIn: { useOutputOfCallAt: 0 }, primaryAddress: weth, receiver: account } },
  ]);
  const d = decodeFunctionData({ abi: routerAbi, data: prepared.input.calls.at(-1).data });
  assert.equal(d.functionName, "safeRouteSingle");
  assert.deepEqual(d.args[1], { tokenType: 0, data: encodeAbiParameters([{ type: "uint256" }], [995n]) }, "the on-chain minimum is in native ETH");
  assert.deepEqual(r.route.hops, [{ action: "swap", protocol: "curve-twocrypto-ng" }, { action: "redeem", protocol: "wrapped-native" }]);
});

test("a 429 is retried once after the interval and only then reported", async () => {
  let n = 0;
  const flaky = new EnsoApi("key", (async () => (++n === 1 ? { ok: false, status: 429, json: async () => ({}) } : { ok: true, status: 200, json: async () => ({ fine: true }) })) as any, 0);
  assert.deepEqual(await flaky.get("tokens", {}), { fine: true });
  assert.equal(n, 2);
  const declined = new EnsoApi("key", (async () => ({ ok: false, status: 422, json: async () => ({}) })) as any, 0);
  await assert.rejects(declined.post("shortcuts/bundle", {}, []), /could not build this protocol action/);
});
