import { encodeFunctionData, erc20Abi, isAddress, zeroAddress, type Address, type Hex } from "viem";
import type { EvmSmartAccount } from "@coinbase/cdp-sdk";
import type { SmartWalletService } from "./smart-wallet.js";
import type { WalletStore } from "./wallet-store.js";
import { chainIds, jsonValue } from "./transaction-builder.js";
import { NATIVE_TOKEN, PERMIT2, normalizeSwap, swapFingerprint, type SwapInput, type SwapPlan } from "./swap-plan.js";
import { publicOperation } from "./transactions.js";
import { walletErrorDiagnostic } from "./wallet-errors.js";

export type SwapQuote = Extract<Awaited<ReturnType<EvmSmartAccount["quoteSwap"]>>, { liquidityAvailable: true }>;
type SwapPrice = Extract<Awaited<ReturnType<SmartWalletService["swapPrice"]>>, { liquidityAvailable: true }>;
type Repository = Pick<WalletStore, "createOperation" | "reserve" | "beforeSigning" | "beforeSwapSigning" | "finish">;
type Backend = Pick<SmartWalletService, "account" | "swapPrice" | "swap">;
type Lock = { withPaymentLock<T>(userId: string, action: () => Promise<T>): Promise<T> };

export function validateSwapTerms(p: Omit<SwapPlan, "minimumOutput">, q: SwapPrice | SwapQuote) {
  if (q.fromToken.toLowerCase() !== p.fromToken.toLowerCase() || q.toToken.toLowerCase() !== p.toToken.toLowerCase() || q.fromAmount !== BigInt(p.fromAmount)) throw new Error("CDP swap terms do not match the requested tokens and amount");
  if (q.toAmount <= 0n || q.minToAmount <= 0n || q.minToAmount > q.toAmount) throw new Error("CDP returned invalid swap output amounts");
  // A provider must not silently widen the requested slippage window.
  if (q.minToAmount < q.toAmount * BigInt(10_000 - p.slippageBps) / 10_000n) throw new Error("CDP quote exceeds the approved slippage tolerance");
  if (q.issues.balance) throw new Error("insufficient balance for this swap");
  if (q.issues.allowance && q.issues.allowance.spender.toLowerCase() !== PERMIT2.toLowerCase()) throw new Error("unexpected swap allowance spender");
}

export function validateSwapQuote(p: SwapPlan, q: SwapQuote, owner: Address) {
  validateSwapTerms(p, q);
  if (q.issues.simulationIncomplete) throw new Error("CDP swap simulation is incomplete; no signing is allowed");
  if (q.network !== p.network) throw new Error("CDP quote network mismatch");
  if (q.minToAmount < BigInt(p.minimumOutput)) throw new Error("fresh swap quote is below the confirmed minimum; preview and approve again");
  if (q.issues.allowance && q.issues.allowance.currentAllowance < BigInt(p.fromAmount)) throw new Error("Permit2 approval is required before this swap; use transaction_prepare for the exact approval");
  const tx = q.transaction;
  if (!tx || !isAddress(tx.to, { strict: false }) || [zeroAddress, p.account, owner].some(a => a.toLowerCase() === tx.to.toLowerCase()) || !/^0x(?:[a-f0-9]{2})+$/i.test(tx.data) || tx.data.length > 131074) throw new Error("CDP returned an invalid swap transaction");
  const native = p.fromToken.toLowerCase() === NATIVE_TOKEN.toLowerCase();
  if (tx.value !== (native ? BigInt(p.fromAmount) : 0n)) throw new Error("swap transaction native value does not match approved input");
  const permit = q.permit2?.eip712;
  if (native && permit) throw new Error("native ETH swaps must not request Permit2 signatures");
  if (!native && !permit) throw new Error("ERC-20 swap is missing its bounded Permit2 authorization");
  if (permit) {
    const m = permit.message as Record<string, any>;
    if (BigInt(permit.domain.chainId ?? 0) !== BigInt(chainIds[p.network]) || permit.domain.verifyingContract?.toLowerCase() !== PERMIT2.toLowerCase() || !["PermitTransferFrom", "PermitWitnessTransferFrom"].includes(permit.primaryType)) throw new Error("swap Permit2 domain or type is invalid");
    if (typeof m.permitted?.token !== "string" || m.permitted.token.toLowerCase() !== p.fromToken.toLowerCase() || BigInt(m.permitted?.amount ?? -1) !== BigInt(p.fromAmount)) throw new Error("swap Permit2 token or amount differs from approved input");
    if (typeof m.spender !== "string" || !isAddress(m.spender, { strict: false }) || [zeroAddress, p.account, owner].some(a => a.toLowerCase() === m.spender.toLowerCase()) || BigInt(m.deadline ?? 0) <= BigInt(Math.floor(Date.now() / 1000))) throw new Error("swap Permit2 spender or deadline is invalid");
  }
}

export class ManagedSwapService {
  constructor(private wallets: Backend, private store: Repository, private lock: Lock, private ttl: number) {}
  async preview(userId: string, input: SwapInput) {
    const account = await this.wallets.account(userId);
    const p = normalizeSwap(input, account.address);
    // An indicative price does not create/sign a firm executable quote.
    const price = await this.wallets.swapPrice(userId, p);
    if (!price.liquidityAvailable) throw new Error("no swap liquidity is available for these tokens and amount");
    validateSwapTerms(p, price);
    const plan = { ...p, minimumOutput: price.minToAmount.toString() };
    const allowance = price.issues.allowance;
    const approval = p.fromToken.toLowerCase() !== NATIVE_TOKEN.toLowerCase() && allowance && allowance.currentAllowance < BigInt(p.fromAmount)
      ? { to: p.fromToken, value: "0", data: encodeFunctionData({ abi: erc20Abi, functionName: "approve", args: [PERMIT2, BigInt(p.fromAmount)] }) } : null;
    const simulation = { status: "cdp_price_estimate", simulation_incomplete: Boolean(price.issues.simulationIncomplete), expected_output_atomic: price.toAmount.toString(), minimum_output_atomic: plan.minimumOutput, slippage_bps: p.slippageBps, fees_estimated: jsonValue(price.fees), approval_required: Boolean(approval), approval_call: approval, approval_details: approval ? { spender: PERMIT2, amount_atomic: p.fromAmount } : null, block_number: price.blockNumber.toString(), limitations: ["Indicative price only. Execution obtains a fresh quote without lowering this minimum output.", "CDP route and its calldata are trusted for enforcing net output; this adapter does not independently decode the aggregator route.", "Network fees can change. Token approval is a separate confirmed operation; it is never silently submitted."] };
    const saved = await this.store.createOperation({ userId, network: p.network, address: p.account, kind: "swap", swapPlan: plan, calls: [], descriptions: [], fingerprint: swapFingerprint(plan), simulation }, Math.min(this.ttl, 300));
    return { ...publicOperation(saved), next_step: approval ? "Show the exact Permit2 approval. Use transaction_prepare/transaction_execute for that approval after confirmation; wait for confirmation, then preview the swap again." : "Show tokens, exact input, expected output, minimum output, slippage and fees. After confirmation call swap_execute once with operation_id and purpose." };
  }
  async execute(userId: string, id: string, purpose: string) {
    return this.lock.withPaymentLock(userId, async () => {
      const op = await this.store.reserve(userId, id, purpose, "swap");
      let signing = false;
      let userOpHash: Hex | null = null;
      try {
        const plan = op.swapPlan;
        const account = await this.wallets.account(userId);
        if (!plan || plan.network !== op.network || plan.account.toLowerCase() !== op.address.toLowerCase() || account.address.toLowerCase() !== op.address.toLowerCase() || swapFingerprint(plan) !== op.fingerprint) throw new Error("swap preview no longer matches this wallet and terms");
        const result = await this.wallets.swap(userId, plan, id, async context => {
          await this.store.beforeSwapSigning(id, context);
          signing = true;
        }, async (hash, prepared) => {
          await this.store.beforeSigning(id, hash, prepared);
          userOpHash = hash;
        });
        if (!signing || !userOpHash || userOpHash !== result.userOpHash) {
          await this.store.finish(id, "unknown", null, "Swap signing boundary/hash mismatch; reconcile before retrying.");
          return { operation_id: id, status: "unknown" };
        }
        await this.store.finish(id, "submitted");
        return { operation_id: id, network: plan.network, status: "submitted", user_op_hash: result.userOpHash, minimum_output_atomic: plan.minimumOutput, next_step: "Poll transaction_status; never repeat a submitted or unknown swap." };
      } catch (error) {
        const diagnostic = walletErrorDiagnostic(error);
        console.error(JSON.stringify({ event: "wallet_execution_failed", operation_id: id, kind: "swap", stage: userOpHash ? "user_operation_signing_or_submission" : signing ? "permit2_or_preparation" : "before_signing", ...diagnostic }));
        await this.store.finish(id, signing ? "unknown" : "failed", null, `${signing ? "Permit2 or UserOperation signing was attempted; reconcile before retrying." : "Swap stopped before signing."} Diagnostic: ${JSON.stringify(diagnostic)}`);
        if (signing) return { operation_id: id, status: "unknown", next_step: "Poll transaction_status. If no UserOperation hash exists, operator reconciliation is required; do not retry automatically." };
        throw error;
      }
    });
  }
}
