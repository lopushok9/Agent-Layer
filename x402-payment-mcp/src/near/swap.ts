import { z } from "zod";
import { concatHex, encodeFunctionData, erc20Abi, formatUnits, getAddress, isAddress, numberToHex, parseAbi, type Address, type Hex, type PublicClient } from "viem";
import { SIMPLE_7702_ACCOUNT, type ChainSignatures, type EvmNetwork } from "./chain-signatures.js";
import { NearPublicError } from "./operations.js";

// Uniswap V3 on the derived address: quotes every direct pool (and two-hop
// routes through WETH) with QuoterV2, then builds one SwapRouter02 multicall
// whose amountOutMinimum is enforced on chain. Native ETH is wrapped by the
// router (msg.value) or unwrapped to the account (unwrapWETH9). Addresses are
// Uniswap's canonical deployments.
export const UNISWAP_V3 = {
  base: { router: "0x2626664c2603336E57B271c5C0b26F421741e481", quoter: "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a", weth: "0x4200000000000000000000000000000000000006" },
  ethereum: { router: "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45", quoter: "0x61fFE014bA17989E743c5F6cB21bF9697530B21e", weth: "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2" },
} as const satisfies Record<EvmNetwork, { router: Address; quoter: Address; weth: Address }>;
const FEE_TIERS = [100, 500, 3000, 10000] as const;
const HOP_FEES = [500, 3000] as const;
const ADDRESS_THIS = "0x0000000000000000000000000000000000000002";
const DEADLINE_SECONDS = 30 * 60;

const tokenInput = z.string().refine(v => v.toUpperCase() === "ETH" || isAddress(v, { strict: false }), "use \"ETH\" or a token contract address");
export const evmSwapInput = z.strictObject({
  network: z.enum(["base", "ethereum"]),
  token_in: tokenInput.describe("\"ETH\" for native ETH, or the ERC-20 address to sell"),
  token_out: tokenInput.describe("\"ETH\" for native ETH, or the ERC-20 address to buy"),
  amount_in: z.string().regex(/^[1-9]\d{0,77}$/).describe("Exact amount to sell in the token's smallest unit (USDC 6 decimals: 0.1 USDC = \"100000\"; ETH in wei)"),
  slippage_bps: z.number().int().min(1).max(300).default(50).describe("On-chain minimum output below the quote, in bps (50 = 0.5%)"),
});
export type EvmSwapInput = z.input<typeof evmSwapInput>;

const quoterAbi = parseAbi([
  "function quoteExactInputSingle((address tokenIn,address tokenOut,uint256 amountIn,uint24 fee,uint160 sqrtPriceLimitX96)) returns (uint256 amountOut,uint160 sqrtPriceX96After,uint32 initializedTicksCrossed,uint256 gasEstimate)",
  "function quoteExactInput(bytes path,uint256 amountIn) returns (uint256 amountOut,uint160[] sqrtPriceX96AfterList,uint32[] initializedTicksCrossedList,uint256 gasEstimate)",
]);
const routerAbi = parseAbi([
  "function exactInputSingle((address tokenIn,address tokenOut,uint24 fee,address recipient,uint256 amountIn,uint256 amountOutMinimum,uint160 sqrtPriceLimitX96)) payable returns (uint256 amountOut)",
  "function exactInput((bytes path,address recipient,uint256 amountIn,uint256 amountOutMinimum)) payable returns (uint256 amountOut)",
  "function unwrapWETH9(uint256 amountMinimum,address recipient) payable",
  "function multicall(uint256 deadline,bytes[] data) payable returns (bytes[])",
]);

export type SwapRoute = { fees: number[]; tokens: Address[]; amountOut: bigint };

export function encodePath(tokens: Address[], fees: number[]): Hex {
  const parts: Hex[] = [tokens[0]!];
  fees.forEach((fee, i) => parts.push(numberToHex(fee, { size: 3 }), tokens[i + 1]!));
  return concatHex(parts);
}

// Best exact-input route among direct pools and WETH two-hops; failing quotes
// (no pool, no liquidity) are skipped.
export async function bestRoute(rpc: PublicClient, quoter: Address, weth: Address, tokenIn: Address, tokenOut: Address, amountIn: bigint): Promise<SwapRoute | null> {
  const candidates: { fees: number[]; tokens: Address[] }[] = FEE_TIERS.map(fee => ({ fees: [fee], tokens: [tokenIn, tokenOut] }));
  if (tokenIn.toLowerCase() !== weth.toLowerCase() && tokenOut.toLowerCase() !== weth.toLowerCase())
    for (const a of HOP_FEES) for (const b of HOP_FEES) candidates.push({ fees: [a, b], tokens: [tokenIn, weth, tokenOut] });
  const quotes = await Promise.all(candidates.map(async c => {
    try {
      const { result } = c.fees.length === 1
        ? await rpc.simulateContract({ address: quoter, abi: quoterAbi, functionName: "quoteExactInputSingle", args: [{ tokenIn, tokenOut, amountIn, fee: c.fees[0]!, sqrtPriceLimitX96: 0n }] })
        : await rpc.simulateContract({ address: quoter, abi: quoterAbi, functionName: "quoteExactInput", args: [encodePath(c.tokens, c.fees), amountIn] });
      const amountOut = (result as readonly [bigint, ...unknown[]])[0];
      return amountOut > 0n ? { ...c, amountOut } : null;
    } catch { return null; }
  }));
  return quotes.reduce<SwapRoute | null>((best, q) => q && (!best || q.amountOut > best.amountOut) ? q : best, null);
}

export function swapCall(network: EvmNetwork, from: Address, route: SwapRoute, amountIn: bigint, minOut: bigint, nativeIn: boolean, nativeOut: boolean, now: number) {
  const { router } = UNISWAP_V3[network];
  const recipient = nativeOut ? ADDRESS_THIS : from;
  const swap = route.fees.length === 1
    ? encodeFunctionData({ abi: routerAbi, functionName: "exactInputSingle", args: [{ tokenIn: route.tokens[0]!, tokenOut: route.tokens[1]!, fee: route.fees[0]!, recipient, amountIn, amountOutMinimum: minOut, sqrtPriceLimitX96: 0n }] })
    : encodeFunctionData({ abi: routerAbi, functionName: "exactInput", args: [{ path: encodePath(route.tokens, route.fees), recipient, amountIn, amountOutMinimum: minOut }] });
  const inner = nativeOut ? [swap, encodeFunctionData({ abi: routerAbi, functionName: "unwrapWETH9", args: [minOut, from] })] : [swap];
  const deadline = BigInt(Math.floor(now / 1000) + DEADLINE_SECONDS);
  return { to: getAddress(router), value: nativeIn ? amountIn.toString() : "0", data: encodeFunctionData({ abi: routerAbi, functionName: "multicall", args: [deadline, inner] }) };
}

export class EvmSwaps {
  constructor(private cs: ChainSignatures, private now: () => number = Date.now) {}

  private async token(rpc: PublicClient, address: Address | "ETH") {
    if (address === "ETH") return { address, symbol: "ETH", decimals: 18 };
    try {
      const [symbol, decimals] = await Promise.all([rpc.readContract({ address, abi: erc20Abi, functionName: "symbol" }), rpc.readContract({ address, abi: erc20Abi, functionName: "decimals" })]);
      return { address, symbol: String(symbol).replace(/[^\x20-\x7e]/g, "?").slice(0, 20), decimals: Number(decimals) };
    } catch { throw new NearPublicError(`evm token ${address} is not a readable ERC-20 on this network; nothing was signed`); }
  }

  async prepare(userId: string, input: EvmSwapInput) {
    const p = evmSwapInput.parse(input);
    const network = p.network;
    const { router, quoter, weth } = UNISWAP_V3[network];
    const rpc = this.cs.rpcFor(network);
    const from = await this.cs.fromAddress(userId);
    const inId = p.token_in.toUpperCase() === "ETH" ? "ETH" as const : getAddress(p.token_in);
    const outId = p.token_out.toUpperCase() === "ETH" ? "ETH" as const : getAddress(p.token_out);
    const tokenIn = inId === "ETH" ? getAddress(weth) : inId, tokenOut = outId === "ETH" ? getAddress(weth) : outId;
    if (tokenIn.toLowerCase() === tokenOut.toLowerCase()) throw new NearPublicError("evm swap needs two different tokens (ETH and WETH count as the same); nothing was signed");
    const amountIn = BigInt(p.amount_in);
    const [inMeta, outMeta] = await Promise.all([this.token(rpc, inId), this.token(rpc, outId)]);
    const route = await bestRoute(rpc, getAddress(quoter), getAddress(weth), tokenIn, tokenOut, amountIn);
    if (!route) throw new NearPublicError(`evm swap: no Uniswap V3 route for ${inMeta.symbol} → ${outMeta.symbol} on ${network}; nothing was signed`);
    const minOut = route.amountOut * BigInt(10_000 - p.slippage_bps) / 10_000n;
    const swap = swapCall(network, from, route, amountIn, minOut, inId === "ETH", outId === "ETH", this.now());
    const summary = {
      protocol: "uniswap_v3", router, quoter,
      token_in: { ...inMeta, amount: amountIn.toString(), formatted: formatUnits(amountIn, inMeta.decimals) },
      token_out: { ...outMeta, quoted: route.amountOut.toString(), quoted_formatted: formatUnits(route.amountOut, outMeta.decimals), minimum: minOut.toString(), minimum_formatted: formatUnits(minOut, outMeta.decimals) },
      route: { tokens: route.tokens, fee_tiers_bps: route.fees.map(f => f / 100) }, slippage_bps: p.slippage_bps,
      protection: "amountOutMinimum is enforced by the router on chain; the multicall deadline is 30 minutes.",
    };
    const calls = [swap];
    let step = "swap";
    if (inId !== "ETH") {
      const allowance = await rpc.readContract({ address: inId, abi: erc20Abi, functionName: "allowance", args: [from, getAddress(router)] });
      if (allowance < amountIn) {
        const approve = { to: inId, value: "0", data: encodeFunctionData({ abi: erc20Abi, functionName: "approve", args: [getAddress(router), amountIn] }) };
        const delegated = (await this.cs.delegation(network, from))?.toLowerCase() === SIMPLE_7702_ACCOUNT.toLowerCase();
        if (delegated) { calls.unshift(approve); step = "approve_and_swap_atomic"; }
        else return this.preview(userId, network, from, [approve], { swap: { ...summary, step: "approval_required", next: "This preview approves exactly amount_in to the router. After it is confirmed on chain, call evm_swap_prepare again for the swap itself (or delegate the address with evm_delegation_prepare to do both atomically)." } });
      }
    }
    return this.preview(userId, network, from, calls, { swap: { ...summary, step } }, p.slippage_bps);
  }

  private async preview(userId: string, network: EvmNetwork, from: Address, raw: { to: Address; value: string; data: Hex }[], extra: Record<string, unknown>, toleranceBps = 50) {
    const built = await Promise.all(raw.map(c => this.cs.build(network, from, { to: c.to, value_wei: c.value, data: c.data })));
    return this.cs.previewCalls(userId, network, from, built.map(b => b.calls[0]!), built.map((b, index) => ({ ...b.description, index })), toleranceBps, extra);
  }
}
