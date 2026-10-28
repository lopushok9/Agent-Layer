import { decodeAbiParameters, decodeFunctionData, encodeAbiParameters, encodeFunctionData, erc20Abi, getAddress, isAddressEqual, parseAbi, type Address, type Hex } from "viem";
import { z } from "zod";
import type { SmartWalletService } from "./smart-wallet.js";
import { addressInput, chainIds, walletNetwork, type WalletNetwork } from "./transaction-builder.js";
import type { TransactionService } from "./transactions.js";

const NATIVE = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE";
// EnsoRouter and the EnsoShortcuts it deploys in its constructor, identical on
// Ethereum and Base (EnsoBuild/shortcuts-client-contracts broadcast/
// EnsoRouterDeployer.s.sol/{1,8453}/run-latest.json; shortcuts() read on-chain).
export const ENSO_ROUTER = "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf" as const;
export const ENSO_SHORTCUTS = "0x4Fe93ebC4Ce6Ae4f81601cC7Ce7139023919E003" as const;
const routerAbi = parseAbi([
  "function safeRouteSingle((uint8 tokenType, bytes data) tokenIn, (uint8 tokenType, bytes data) tokenOut, address receiver, bytes data) payable returns (bytes)",
  "function routeSingle((uint8 tokenType, bytes data) tokenIn, bytes data) payable returns (bytes)",
  "function shortcuts() view returns (address)",
]);
const NATIVE_TYPE = 0, ERC20_TYPE = 1;
const atomic = z.string().regex(/^[1-9][0-9]{0,77}$/, "use a positive integer atomic amount");

export const routeInput = z.strictObject({
  network: walletNetwork,
  token_in: addressInput.describe(`Token to spend; native ETH is ${NATIVE}`),
  amount_in: atomic,
  token_out: addressInput.describe("Token or position to receive: a token, a vault share, an LP or lending receipt token"),
  slippage_bps: z.number().int().min(1).max(500).default(50),
});
export type RouteInput = z.input<typeof routeInput>;

// Only actions whose result is a token held by the receiver: EnsoRouter calls
// protocols as EnsoShortcuts, so a borrow, repay or harvest through the router
// would act for Enso's contract, not this account (Enso uses delegatecall for
// those, which this wallet never does), and safeRouteSingle can only check a
// token balance.
export const ROUTER_ACTIONS = ["deposit", "redeem", "swap"] as const;
const slug = z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/, "use the protocol slug from defi_catalog");
export const actionInput = z.strictObject({
  network: walletNetwork,
  protocol: slug,
  action: z.enum(ROUTER_ACTIONS),
  token_in: addressInput.describe(`Token to spend (for redeem: the position token); native ETH is ${NATIVE}`),
  amount_in: atomic,
  token_out: addressInput.describe("Token this account receives: the position token for deposit, the underlying for redeem"),
  primary_address: addressInput.describe("Contract the protocol action calls (defi_positions primary_address, or the pool for swap)"),
  slippage_bps: z.number().int().min(1).max(500).default(50),
  // Pool selectors of Enso's swap action; fee-receiver and maxAmountOut
  // arguments, which divert output above a limit to Enso's fee receiver, are
  // deliberately not accepted.
  pool: z.strictObject({ pool_fee: z.string().regex(/^\d{1,7}$/).optional(), tick_spacing: z.string().regex(/^-?\d{1,7}$/).optional(), hooks: addressInput.optional(), pool_id: z.string().regex(/^0x[0-9a-fA-F]{64}$/).optional() }).optional(),
});
export type ActionInput = z.input<typeof actionInput>;

type Backend = Pick<SmartWalletService, "account" | "rpc">;
type Transactions = Pick<TransactionService, "prepare">;
export type Fetch = (url: string, init: { method: string; headers: Record<string, string>; body?: string; signal: AbortSignal }) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;
export type RouteResponse = { tx?: { to?: string; data?: string; value?: string | number; from?: string }; amountOut?: unknown; minAmountOut?: unknown; priceImpact?: number | null; route?: { action?: unknown; protocol?: unknown; tokenIn?: unknown; tokenOut?: unknown }[] };

// Enso's Route API turns "token X into position Y" into one transaction across
// hundreds of protocols. Its response is untrusted: the only thing the user is
// asked to rely on is what EnsoRouter.safeRouteSingle enforces on-chain (input
// pulled, minimum output to the receiver checked after the route), so the input
// is decoded from the calldata and compared with the request, and the call sent
// is always a safeRouteSingle with this account and the user's minimum.
export class EnsoRoutes {
  readonly api: EnsoApi;
  constructor(private wallets: Backend, private transactions: Transactions, apiKey: string, fetcher: Fetch = fetch as unknown as Fetch, intervalMs = 1_100) {
    this.api = new EnsoApi(apiKey, fetcher, intervalMs);
  }

  async preview(userId: string, input: RouteInput) {
    const p = routeInput.parse(input);
    return this.build(userId, p.network, p.token_in, p.amount_in, p.token_out, p.slippage_bps, async account => {
      const tokenIn = getAddress(p.token_in), tokenOut = getAddress(p.token_out);
      return await this.api.post("shortcuts/route", {}, { chainId: chainIds[p.network], fromAddress: account, receiver: account, spender: account, refundReceiver: account, routingStrategy: "router", tokenIn: [tokenIn], tokenOut: [tokenOut], amountIn: [p.amount_in], slippage: String(p.slippage_bps) }) as RouteResponse;
    });
  }

  // One protocol action from Enso's catalog, built by the Bundle API with the
  // router strategy. Its answer is the same EnsoRouter routeSingle a route
  // returns, so it gets the same checks and the same on-chain minimum.
  async actionPreview(userId: string, input: ActionInput, supported: (network: WalletNetwork, protocol: string, action: string) => Promise<boolean>) {
    const p = actionInput.parse(input);
    if (!await supported(p.network, p.protocol, p.action)) throw new Error("this protocol action is not available on this network through the Enso router");
    return this.build(userId, p.network, p.token_in, p.amount_in, p.token_out, p.slippage_bps, async account => {
      const tokenIn = getAddress(p.token_in), tokenOut = getAddress(p.token_out);
      // Many protocols (Aave supply, for one) mint to the caller, which under
      // the router is EnsoShortcuts; Enso then refuses the bundle ("does not
      // transfer all funds to the requested receiver"). So the action's output
      // is moved to this account by an explicit erc20 transfer of exactly what
      // the action returned. Native ETH output is paid to receiver directly.
      const nativeOut = isAddressEqual(tokenOut, NATIVE);
      const args: Record<string, unknown> = { tokenIn, tokenOut, amountIn: p.amount_in, primaryAddress: getAddress(p.primary_address), ...(nativeOut ? { receiver: account } : {}) };
      if (p.action === "swap") {
        args.slippage = String(p.slippage_bps);
        if (p.pool?.pool_fee) args.poolFee = p.pool.pool_fee;
        if (p.pool?.tick_spacing) args.tickSpacing = p.pool.tick_spacing;
        if (p.pool?.hooks) args.hooks = getAddress(p.pool.hooks);
        if (p.pool?.pool_id) args.poolId = p.pool.pool_id;
      } else if (p.pool) throw new Error("pool parameters apply only to swap");
      const bundle = await this.api.post("shortcuts/bundle", { chainId: String(chainIds[p.network]), fromAddress: account, routingStrategy: "router", receiver: account, spender: account, refundReceiver: account }, [{ protocol: p.protocol, action: p.action, args }, ...(nativeOut ? [] : [{ protocol: "erc20", action: "transfer", args: { token: tokenOut, receiver: account, amount: { useOutputOfCallAt: 0 } } }])]) as RouteResponse & { amountsOut?: Record<string, unknown> };
      const out = bundle.amountsOut && typeof bundle.amountsOut === "object" ? Object.entries(bundle.amountsOut).find(([k]) => k.toLowerCase() === tokenOut.toLowerCase())?.[1] : undefined;
      return { tx: bundle.tx, amountOut: out, priceImpact: bundle.priceImpact, route: [{ action: p.action, protocol: p.protocol }] } as RouteResponse;
    }, { protocol: p.protocol, action: p.action, primary_address: getAddress(p.primary_address) });
  }

  private async build(userId: string, network: WalletNetwork, tokenInRaw: string, amount: string, tokenOutRaw: string, slippageBps: number, fetchRoute: (account: Address) => Promise<RouteResponse>, extra: Record<string, unknown> = {}) {
    const account = (await this.wallets.account(userId)).address;
    const rpc = this.wallets.rpc(network);
    if (await rpc.getChainId() !== chainIds[network]) throw new Error("RPC chain ID mismatch");
    const tokenIn = getAddress(tokenInRaw), tokenOut = getAddress(tokenOutRaw), amountIn = BigInt(amount);
    if (isAddressEqual(tokenIn, tokenOut)) throw new Error("route tokens must differ");
    if (await rpc.readContract({ address: ENSO_ROUTER, abi: routerAbi, functionName: "shortcuts" }) !== ENSO_SHORTCUTS) throw new Error("Enso router on this network is not the expected deployment");
    const route = await fetchRoute(account);
    const terms = verifyRoute(route, { account, tokenIn, tokenOut, amountIn, slippageBps });
    const calls: { to: Address; value: string; data?: Hex }[] = [];
    if (!isAddressEqual(tokenIn, NATIVE)) {
      // Exact allowance for this route only, never unlimited. Tokens such as
      // USDT revert on a nonzero-to-nonzero approve, so reset first.
      const allowance = await rpc.readContract({ address: tokenIn, abi: erc20Abi, functionName: "allowance", args: [account, ENSO_ROUTER] });
      if (allowance < amountIn) {
        if (allowance > 0n) calls.push({ to: tokenIn, value: "0", data: encodeFunctionData({ abi: erc20Abi, functionName: "approve", args: [ENSO_ROUTER, 0n] }) });
        calls.push({ to: tokenIn, value: "0", data: encodeFunctionData({ abi: erc20Abi, functionName: "approve", args: [ENSO_ROUTER, amountIn] }) });
      }
    }
    calls.push({ to: ENSO_ROUTER, value: terms.value.toString(), data: terms.data });
    const summary = { provider: "enso", ...extra, router: ENSO_ROUTER, token_in: tokenIn, amount_in: amountIn.toString(), token_out: tokenOut, expected_output: terms.expected.toString(), minimum_output: terms.minimum.toString(), minimum_enforced_by: "EnsoRouter.safeRouteSingle reverts unless the receiver gains at least minimum_output", slippage_bps: slippageBps, receiver: account, price_impact_bps: typeof route.priceImpact === "number" ? route.priceImpact : null, hops: hops(route), approvals_included: calls.length - 1 };
    const preview = await this.transactions.prepare(userId, { network, calls }, { route: summary, floors: { [tokenOut.toLowerCase()]: terms.minimum.toString() } });
    return { ...preview, route: summary, next_step: "Show the route: input, expected and minimum output, hops, price impact, the exact approval and the simulated asset changes. After the user confirms this exact preview, call transaction_execute once with operation_id. Execution keeps the minimum output fixed; the route itself reverts below it." };
  }
}

// The free Enso plan allows one request per second. Every call goes through
// one queue so concurrent agents wait instead of failing.
export class EnsoApi {
  private queue: Promise<unknown> = Promise.resolve();
  private nextAt = 0;
  constructor(private apiKey: string, private fetcher: Fetch, private intervalMs: number) {}
  get(path: string, query: Record<string, string | string[] | undefined>) { return this.request("GET", path, query); }
  post(path: string, query: Record<string, string | string[] | undefined>, body: unknown) { return this.request("POST", path, query, body); }
  private request(method: string, path: string, query: Record<string, string | string[] | undefined>, body?: unknown): Promise<unknown> {
    const search = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) for (const x of Array.isArray(v) ? v : v === undefined ? [] : [v]) search.append(k, x);
    const url = `https://api.enso.build/api/v1/${path}${search.size ? `?${search}` : ""}`;
    const run = this.queue.then(async () => {
      const wait = this.nextAt - Date.now();
      if (wait > 0) await new Promise(r => setTimeout(r, wait));
      this.nextAt = Date.now() + this.intervalMs;
      const res = await this.fetcher(url, { method, headers: { "content-type": "application/json", authorization: `Bearer ${this.apiKey}` }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(20_000) });
      if (res.status === 429) throw new Error("Enso rate limit reached; try again in a few seconds");
      if (!res.ok) throw new Error(res.status !== 400 && res.status !== 404 ? "Enso route service is unavailable" : path === "shortcuts/bundle" ? "Enso could not build this protocol action with these inputs" : "Enso found no route for these tokens and amount");
      return await res.json();
    });
    this.queue = run.catch(() => undefined);
    return run;
  }
}

export function verifyRoute(route: RouteResponse, want: { account: Address; tokenIn: Address; tokenOut: Address; amountIn: bigint; slippageBps: number }) {
  const tx = route.tx;
  const invalid = () => new Error("Enso returned a route that does not match the request; nothing was prepared");
  const notSingle = () => new Error("Enso route is not a single-token EnsoRouter route; nothing was prepared");
  if (!tx || typeof tx.to !== "string" || typeof tx.data !== "string" || !/^0x[0-9a-fA-F]*$/.test(tx.data)) throw invalid();
  if (!isAddressEqual(getAddress(tx.to), ENSO_ROUTER)) throw new Error("Enso route does not call the EnsoRouter; nothing was prepared");
  if (tx.from !== undefined && !isAddressEqual(getAddress(tx.from), want.account)) throw invalid();
  let decoded;
  try { decoded = decodeFunctionData({ abi: routerAbi, data: tx.data as Hex }); } catch { throw notSingle(); }
  if (decoded.functionName !== "safeRouteSingle" && decoded.functionName !== "routeSingle") throw notSingle();
  const inToken = decoded.args[0];
  const value = BigInt(tx.value ?? 0);
  const nativeIn = isAddressEqual(want.tokenIn, NATIVE), nativeOut = isAddressEqual(want.tokenOut, NATIVE);
  // EnsoRouter._transfer: Native takes msg.value; ERC20 data is (token, amount).
  if (nativeIn) { if (inToken.tokenType !== NATIVE_TYPE || value !== want.amountIn) throw invalid(); }
  else {
    if (inToken.tokenType !== ERC20_TYPE || value !== 0n) throw invalid();
    const [token, amount] = decodeAbiParameters([{ type: "address" }, { type: "uint256" }], inToken.data);
    if (!isAddressEqual(token, want.tokenIn) || amount !== want.amountIn) throw invalid();
  }
  const expected = (() => { try { return BigInt(String(Array.isArray(route.amountOut) ? route.amountOut[0] : route.amountOut)); } catch { return 0n; } })();
  if (expected <= 0n) throw invalid();
  // The on-chain floor must honour the user's tolerance against Enso's own quote.
  const floor = expected * BigInt(10_000 - want.slippageBps) / 10_000n;
  if (decoded.functionName === "routeSingle") {
    // The Route API answers with routeSingle, which checks no output. Its
    // safeRouteSingle runs the same routeSingle(tokenIn, data) and then reverts
    // with AmountTooLow unless receiver's tokenOut balance grew by the minimum
    // (EnsoRouter.sol), so the same shortcut is wrapped with this account as
    // receiver and the user's floor as minimum. A shortcut that pays anyone
    // else cannot pass that check.
    if (floor <= 0n) throw invalid();
    const tokenOut = nativeOut
      ? { tokenType: NATIVE_TYPE, data: encodeAbiParameters([{ type: "uint256" }], [floor]) }
      : { tokenType: ERC20_TYPE, data: encodeAbiParameters([{ type: "address" }, { type: "uint256" }], [want.tokenOut, floor]) };
    const data = encodeFunctionData({ abi: routerAbi, functionName: "safeRouteSingle", args: [inToken, tokenOut, want.account, decoded.args[1]] });
    return { value, data, expected, minimum: floor };
  }
  const [, outToken, receiver] = decoded.args;
  if (!isAddressEqual(receiver, want.account)) throw new Error("Enso route sends the output to another address; nothing was prepared");
  // EnsoRouter._checkMinAmountOut: Native data is (minAmountOut); ERC20 is (token, minAmountOut).
  let minimum: bigint;
  if (nativeOut) { if (outToken.tokenType !== NATIVE_TYPE) throw invalid(); [minimum] = decodeAbiParameters([{ type: "uint256" }], outToken.data); }
  else {
    if (outToken.tokenType !== ERC20_TYPE) throw invalid();
    const [token, min] = decodeAbiParameters([{ type: "address" }, { type: "uint256" }], outToken.data);
    if (!isAddressEqual(token, want.tokenOut)) throw invalid();
    minimum = min;
  }
  if (minimum <= 0n || minimum > expected) throw invalid();
  if (minimum < floor) throw new Error("Enso route minimum output is below the requested slippage; nothing was prepared");
  return { value, data: tx.data as Hex, expected, minimum };
}

function hops(route: RouteResponse) {
  return (Array.isArray(route.route) ? route.route : []).slice(0, 12).map(h => ({ action: String(h.action ?? "").slice(0, 40), protocol: String(h.protocol ?? "").slice(0, 60) }));
}
