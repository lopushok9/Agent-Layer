import { decodeAbiParameters, decodeFunctionData, encodeAbiParameters, encodeFunctionData, erc20Abi, getAddress, isAddressEqual, parseAbi, type Address, type Hex } from "viem";
import { z } from "zod";
import type { SmartWalletService } from "./smart-wallet.js";
import { addressInput, chainIds, walletNetwork } from "./transaction-builder.js";
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

type Backend = Pick<SmartWalletService, "account" | "rpc">;
type Transactions = Pick<TransactionService, "prepare">;
type Fetch = (url: string, init: { method: string; headers: Record<string, string>; body: string; signal: AbortSignal }) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;
type RouteResponse = { tx?: { to?: string; data?: string; value?: string | number; from?: string }; amountOut?: unknown; minAmountOut?: unknown; priceImpact?: number | null; route?: { action?: unknown; protocol?: unknown; tokenIn?: unknown; tokenOut?: unknown }[] };

// Enso's Route API turns "token X into position Y" into one transaction across
// hundreds of protocols. Its response is untrusted: the only thing the user is
// asked to rely on is what EnsoRouter.safeRouteSingle enforces on-chain (input
// pulled, minimum output to the receiver checked after the route), so the input
// is decoded from the calldata and compared with the request, and the call sent
// is always a safeRouteSingle with this account and the user's minimum.
export class EnsoRoutes {
  constructor(private wallets: Backend, private transactions: Transactions, private apiKey: string, private fetcher: Fetch = fetch as unknown as Fetch) {}

  async preview(userId: string, input: RouteInput) {
    const p = routeInput.parse(input);
    const account = (await this.wallets.account(userId)).address;
    const rpc = this.wallets.rpc(p.network);
    if (await rpc.getChainId() !== chainIds[p.network]) throw new Error("RPC chain ID mismatch");
    const tokenIn = getAddress(p.token_in), tokenOut = getAddress(p.token_out), amountIn = BigInt(p.amount_in);
    if (isAddressEqual(tokenIn, tokenOut)) throw new Error("route tokens must differ");
    if (await rpc.readContract({ address: ENSO_ROUTER, abi: routerAbi, functionName: "shortcuts" }) !== ENSO_SHORTCUTS) throw new Error("Enso router on this network is not the expected deployment");
    const route = await this.route({ chainId: chainIds[p.network], fromAddress: account, receiver: account, spender: account, refundReceiver: account, routingStrategy: "router", tokenIn: [tokenIn], tokenOut: [tokenOut], amountIn: [amountIn.toString()], slippage: String(p.slippage_bps) });
    const terms = verifyRoute(route, { account, tokenIn, tokenOut, amountIn, slippageBps: p.slippage_bps });
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
    const summary = { provider: "enso", router: ENSO_ROUTER, token_in: tokenIn, amount_in: amountIn.toString(), token_out: tokenOut, expected_output: terms.expected.toString(), minimum_output: terms.minimum.toString(), minimum_enforced_by: "EnsoRouter.safeRouteSingle reverts unless the receiver gains at least minimum_output", slippage_bps: p.slippage_bps, receiver: account, price_impact_bps: typeof route.priceImpact === "number" ? route.priceImpact : null, hops: hops(route), approvals_included: calls.length - 1 };
    const preview = await this.transactions.prepare(userId, { network: p.network, calls }, { route: summary, floors: { [tokenOut.toLowerCase()]: terms.minimum.toString() } });
    return { ...preview, route: summary, next_step: "Show the route: input, expected and minimum output, hops, price impact, the exact approval and the simulated asset changes. After the user confirms this exact preview, call transaction_execute once with operation_id. Execution keeps the minimum output fixed; the route itself reverts below it." };
  }

  private async route(body: Record<string, unknown>): Promise<RouteResponse> {
    const res = await this.fetcher("https://api.enso.build/api/v1/shortcuts/route", { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${this.apiKey}` }, body: JSON.stringify(body), signal: AbortSignal.timeout(20_000) });
    if (!res.ok) throw new Error(res.status === 400 || res.status === 404 ? "Enso found no route for these tokens and amount" : "Enso route service is unavailable");
    return await res.json() as RouteResponse;
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
