import { createHash } from "node:crypto";
import { getAddress, maxUint256, zeroAddress, type Address } from "viem";
import { z } from "zod";
import { addressInput, chainIds, walletNetwork, type WalletNetwork } from "./transaction-builder.js";

export const NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE" as const;
export const PERMIT2 = "0x000000000022D473030F116dDEE9F6B43aC78BA3" as const;
export const swapInput = z.strictObject({
  network: walletNetwork,
  from_token: addressInput,
  to_token: addressInput,
  from_amount_atomic: z.string().regex(/^[1-9][0-9]{0,77}$/).refine(v => BigInt(v) <= maxUint256, "amount exceeds uint256"),
  slippage_bps: z.number().int().min(0).max(500).default(100),
});
export type SwapInput = z.input<typeof swapInput>;
export type SwapPlan = {
  network: WalletNetwork; account: Address; fromToken: Address; toToken: Address;
  fromAmount: string; slippageBps: number; minimumOutput: string;
};
export function normalizeSwap(input: SwapInput, account: Address) {
  const p = swapInput.parse(input);
  const fromToken = getAddress(p.from_token), toToken = getAddress(p.to_token);
  if (fromToken === toToken || [fromToken, toToken].some(t => t === zeroAddress || t.toLowerCase() === account.toLowerCase())) throw new Error("swap tokens must be distinct nonzero token addresses or the native ETH sentinel");
  return { network: p.network, account: getAddress(account), fromToken, toToken, fromAmount: p.from_amount_atomic, slippageBps: p.slippage_bps };
}
export function swapFingerprint(p: SwapPlan) {
  return createHash("sha256").update(JSON.stringify({ version: 1, kind: "cdp_swap", chainId: chainIds[p.network], account: p.account.toLowerCase(), fromToken: p.fromToken.toLowerCase(), toToken: p.toToken.toLowerCase(), fromAmount: BigInt(p.fromAmount).toString(), minimumOutput: BigInt(p.minimumOutput).toString(), slippageBps: p.slippageBps })).digest("hex");
}
