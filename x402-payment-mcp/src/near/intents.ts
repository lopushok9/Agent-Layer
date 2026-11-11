import { z } from "zod";
import { getAddress, isAddress } from "viem";
import type { NearAccountService } from "./account.js";
import type { ChainSignatures } from "./chain-signatures.js";
import { NearPublicError, type NearOperations } from "./operations.js";
import type { NearStore } from "./store.js";
import type { NormalizedNearAction } from "./transaction.js";
import { assertAccountId, GAS_PER_TGAS } from "./units.js";

// NEAR Intents through the 1Click API: the NEAR account funds a one-time
// deposit address with a NEP-141 token and solvers deliver the destination
// asset on any supported chain. Refunds go back to the same NEAR account, and
// EVM deliveries default to the Chain Signatures address of that account, so
// one NEAR key controls both ends of the swap.
export const ONECLICK_URL = "https://1click.chaindefuser.com";
export const WRAP_NEAR = "wrap.near";
const IMPLICIT = /^[0-9a-f]{64}$/;
// Chains where the derived Chain Signatures address is a valid recipient.
const EVM_CHAINS = new Set(["eth", "base", "arb", "op", "pol", "bsc", "avax", "gnosis", "bera", "scroll", "monad", "xlayer", "abs", "plasma", "hood"]);
const SPENDABLE_EVM = new Set(["eth", "base"]);
const QUOTE_DEADLINE_MS = 30 * 60_000;
const DEADLINE_MARGIN_MS = 2 * 60_000;
const STORAGE_GAS = 10n * GAS_PER_TGAS, WRAP_GAS = 10n * GAS_PER_TGAS, TRANSFER_GAS = 20n * GAS_PER_TGAS;
const UINT = /^\d{1,78}$/;

export type OneClickToken = { assetId: string; decimals: number; blockchain: string; symbol: string; price?: number; contractAddress?: string };
export type OneClickQuote = {
  quote: { amountIn: string; amountOut: string; minAmountOut: string; depositAddress?: string; depositMemo?: string; deadline?: string; timeWhenInactive?: string; timeEstimate?: number; amountInUsd?: string; amountOutUsd?: string; amountOutFormatted?: string; withdrawFee?: string };
  quoteRequest: Record<string, unknown>; signature?: string; correlationId?: string; timestamp?: string;
};

export class OneClickClient {
  private cache: { at: number; tokens: OneClickToken[] } | null = null;
  constructor(private base = ONECLICK_URL, private fetcher: typeof fetch = globalThis.fetch, private jwt?: string) {}

  private async request<T>(path: string, init?: { method: "POST"; body: unknown }): Promise<T> {
    const headers: Record<string, string> = { accept: "application/json" };
    if (init) headers["content-type"] = "application/json";
    if (this.jwt) headers.authorization = `Bearer ${this.jwt}`;
    let res: Response;
    try { res = await this.fetcher(`${this.base}${path}`, { method: init?.method ?? "GET", headers, body: init ? JSON.stringify(init.body) : null, signal: AbortSignal.timeout(15_000) }); }
    catch { throw new NearPublicError("intents: the 1Click API is unreachable; nothing was signed"); }
    const text = await res.text();
    let body: any = null;
    try { body = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
    if (!res.ok) {
      const m = typeof body?.message === "string" ? body.message.replace(/[^\x20-\x7e]/g, "").slice(0, 200) : `HTTP ${res.status}`;
      throw new NearPublicError(`intents: 1Click refused the request (${m}); nothing was signed`);
    }
    return body as T;
  }

  async tokens(): Promise<OneClickToken[]> {
    if (this.cache && Date.now() - this.cache.at < 300_000) return this.cache.tokens;
    const raw = await this.request<unknown[]>("/v0/tokens");
    if (!Array.isArray(raw)) throw new NearPublicError("intents: unexpected 1Click token list; nothing was signed");
    const tokens = raw.flatMap(t => {
      const x = t as Record<string, unknown>;
      if (typeof x.assetId !== "string" || typeof x.blockchain !== "string" || typeof x.symbol !== "string" || !Number.isInteger(x.decimals)) return [];
      return [{ assetId: x.assetId, decimals: x.decimals as number, blockchain: x.blockchain, symbol: x.symbol.replace(/[^\x20-\x7e]/g, "?").slice(0, 20), ...(typeof x.price === "number" ? { price: x.price } : {}), ...(typeof x.contractAddress === "string" ? { contractAddress: x.contractAddress } : {}) }];
    });
    this.cache = { at: Date.now(), tokens };
    return tokens;
  }

  quote(body: Record<string, unknown>) { return this.request<OneClickQuote>("/v0/quote", { method: "POST", body }); }
  submit(txHash: string, depositAddress: string, nearSenderAccount: string) { return this.request<unknown>("/v0/deposit/submit", { method: "POST", body: { txHash, depositAddress, nearSenderAccount } }); }
  status(depositAddress: string) { return this.request<Record<string, any>>(`/v0/status?depositAddress=${encodeURIComponent(depositAddress)}`); }
}

const assetRef = z.string().min(2).max(200);
export const intentsTokensInput = z.strictObject({
  blockchain: z.string().max(20).optional().describe("Filter by chain, e.g. near, base, eth, arb, sol, btc"),
  symbol: z.string().max(20).optional().describe("Filter by symbol, e.g. USDC, ETH"),
});
export const intentsSwapInput = z.strictObject({
  origin_asset: assetRef.describe("What the NEAR account sells: \"NEAR\" (wrapped automatically), a NEAR-chain 1Click assetId like nep141:wrap.near, or SYMBOL@near"),
  destination_asset: assetRef.describe("What to receive: a 1Click assetId from intents_tokens, or SYMBOL@chain such as ETH@base, USDC@base, USDC@near"),
  amount: z.string().regex(/^[1-9]\d{0,77}$/).describe("Exact amount to sell in the origin token's smallest unit (NEAR/wNEAR 24 decimals: 0.02 NEAR = \"20000000000000000000000\")"),
  recipient: z.string().min(2).max(100).optional().describe("Destination address. Defaults to this NEAR account for NEAR assets and to its Chain Signatures EVM address for EVM chains; required elsewhere"),
  slippage_bps: z.number().int().min(1).max(500).default(100).describe("Accepted slippage below the quote in bps (100 = 1%); below the minimum the deposit is refunded"),
});
export type IntentsSwapInput = z.input<typeof intentsSwapInput>;

export type IntentsPlan = { deposit_address: string; deposit_memo: string | null; correlation_id: string | null; deadline: string; origin_asset: string; destination_asset: string; amount_in: string; min_amount_out: string; recipient: string };

export class NearIntents {
  constructor(private accounts: NearAccountService, private operations: NearOperations, private store: NearStore, private cs: ChainSignatures | null, private client = new OneClickClient(), private now: () => number = Date.now) {}
  private get rpc() { return this.accounts.rpc; }

  async tokens(input: z.infer<typeof intentsTokensInput>) {
    const b = input.blockchain?.toLowerCase(), s = input.symbol?.toUpperCase();
    const all = (await this.client.tokens()).filter(t => (!b || t.blockchain === b) && (!s || t.symbol.toUpperCase() === s));
    return { count: all.length, tokens: all.slice(0, 100).map(t => ({ asset_id: t.assetId, symbol: t.symbol, blockchain: t.blockchain, decimals: t.decimals, ...(t.price !== undefined ? { price_usd: t.price } : {}), ...(t.contractAddress ? { contract: t.contractAddress } : {}) })), ...(all.length > 100 ? { note: "Showing the first 100; filter by blockchain or symbol." } : {}), origin_note: "intents_swap_prepare sells assets with blockchain \"near\" from the NEAR account." };
  }

  private async resolve(ref: string, role: string): Promise<OneClickToken> {
    const tokens = await this.client.tokens();
    if (ref.toUpperCase() === "NEAR") ref = `nep141:${WRAP_NEAR}`;
    const at = ref.indexOf("@");
    const matches = at > 0 && !ref.includes(":")
      ? tokens.filter(t => t.symbol.toUpperCase() === ref.slice(0, at).toUpperCase() && t.blockchain === ref.slice(at + 1).toLowerCase())
      : tokens.filter(t => t.assetId === ref);
    if (matches.length !== 1) throw new NearPublicError(`intents: ${role} ${ref.slice(0, 80)} ${matches.length ? "is ambiguous; use its asset_id" : "is not a 1Click asset; see intents_tokens"}. Nothing was signed`);
    return matches[0]!;
  }

  private async ftView(contract: string, method: string, args: unknown) { return (await this.rpc.callFunction(contract, method, args)).result; }

  async prepare(userId: string, input: IntentsSwapInput) {
    const p = intentsSwapInput.parse(input);
    const account = await this.accounts.account(userId);
    const self = account.accountId;
    const [origin, dest] = await Promise.all([this.resolve(p.origin_asset, "origin_asset"), this.resolve(p.destination_asset, "destination_asset")]);
    if (origin.blockchain !== "near" || !origin.assetId.startsWith("nep141:")) throw new NearPublicError("intents: origin_asset must be a NEAR-chain NEP-141 token (blockchain near); the NEAR account is the only sender. Nothing was signed");
    if (origin.assetId === dest.assetId) throw new NearPublicError("intents: origin and destination are the same asset; nothing was signed");
    const contract = assertAccountId(origin.assetId.slice("nep141:".length), "origin contract");
    const amount = BigInt(p.amount);
    const recipient = await this.recipient(userId, self, dest.blockchain, p.recipient);

    // Balances and storage before asking for a deposit address.
    const [balance, registered, bounds] = await Promise.all([this.ftView(contract, "ft_balance_of", { account_id: self }), this.ftView(contract, "storage_balance_of", { account_id: self }), this.ftView(contract, "storage_balance_bounds", {})]);
    const have = typeof balance === "string" && UINT.test(balance) ? BigInt(balance) : 0n;
    const storageMin = BigInt(String((bounds as { min?: unknown } | null)?.min ?? "0").replace(/\D/g, "") || "0");
    const wrap = contract === WRAP_NEAR && have < amount ? amount - have : 0n;
    if (have < amount && !wrap) throw new NearPublicError(`intents: the NEAR account holds ${have} of ${origin.symbol} (smallest units), needs ${amount}; nothing was signed`);

    const deadline = new Date(this.now() + QUOTE_DEADLINE_MS).toISOString();
    const request = { dry: false, swapType: "EXACT_INPUT", slippageTolerance: p.slippage_bps, originAsset: origin.assetId, depositType: "ORIGIN_CHAIN", destinationAsset: dest.assetId, amount: p.amount, refundTo: self, refundType: "ORIGIN_CHAIN", recipient, recipientType: "DESTINATION_CHAIN", deadline, quoteWaitingTimeMs: 3000 };
    const q = await this.client.quote(request);
    const deposit = this.checkQuote(q, request, self);

    const actions: NormalizedNearAction[] = [];
    const call = (method: string, args: unknown, gas: bigint, depositYocto: bigint): NormalizedNearAction => ({ type: "function_call", method, args_base64: Buffer.from(JSON.stringify(args)).toString("base64"), gas: gas.toString(), deposit: depositYocto.toString() });
    if (registered === null) actions.push(call("storage_deposit", { account_id: self, registration_only: true }, STORAGE_GAS, storageMin));
    if (wrap) actions.push(call("near_deposit", {}, WRAP_GAS, wrap));
    const depositRegistered = await this.ftView(contract, "storage_balance_of", { account_id: deposit });
    if (depositRegistered === null) actions.push(call("storage_deposit", { account_id: deposit, registration_only: true }, STORAGE_GAS, storageMin));
    actions.push(call("ft_transfer", { receiver_id: deposit, amount: p.amount, ...(q.quote.depositMemo ? { memo: q.quote.depositMemo } : {}) }, TRANSFER_GAS, 1n));

    const fmt = (v: string, d: number) => formatUnits(BigInt(v), d);
    const plan: IntentsPlan = { deposit_address: deposit, deposit_memo: q.quote.depositMemo ?? null, correlation_id: q.correlationId ?? null, deadline, origin_asset: origin.assetId, destination_asset: dest.assetId, amount_in: p.amount, min_amount_out: q.quote.minAmountOut, recipient };
    const warnings: string[] = [];
    if (p.recipient) warnings.push(`Recipient ${recipient} was given explicitly; check it, delivery to a wrong address is irreversible.`);
    if (EVM_CHAINS.has(dest.blockchain) && !SPENDABLE_EVM.has(dest.blockchain)) warnings.push(`Delivery on ${dest.blockchain}: the same key controls the address there, but this server's EVM tools only send on Base and Ethereum.`);
    const fees = q.quoteRequest.appFees;
    return this.operations.preview(userId, { receiverId: contract, actions }, "intents_swap", { oneclick: plan }, {
      intents: {
        protocol: "near_intents_1click",
        origin: { asset_id: origin.assetId, symbol: origin.symbol, amount: p.amount, formatted: fmt(p.amount, origin.decimals), ...(wrap ? { wraps_near_yocto: wrap.toString(), wraps_near: fmt(wrap.toString(), 24) } : {}) },
        destination: { asset_id: dest.assetId, symbol: dest.symbol, blockchain: dest.blockchain, quoted: q.quote.amountOut, quoted_formatted: fmt(q.quote.amountOut, dest.decimals), minimum: q.quote.minAmountOut, minimum_formatted: fmt(q.quote.minAmountOut, dest.decimals), ...(q.quote.amountOutUsd ? { quoted_usd: q.quote.amountOutUsd } : {}) },
        ...(q.quote.amountInUsd ? { amount_in_usd: q.quote.amountInUsd } : {}),
        recipient, refund_to: self, deposit_address: deposit, ...(q.quote.depositMemo ? { deposit_memo: q.quote.depositMemo } : {}),
        deposit_deadline: deadline, ...(q.quote.timeEstimate !== undefined ? { time_estimate_seconds: q.quote.timeEstimate } : {}),
        ...(Array.isArray(fees) && fees.length ? { app_fees_bps: fees.map((f: any) => Number(f?.fee) || 0).reduce((a: number, b: number) => a + b, 0) } : {}),
        ...(q.quote.withdrawFee ? { destination_withdraw_fee: q.quote.withdrawFee } : {}),
        protection: "Solvers must deliver at least the minimum to the recipient; otherwise, or after the deposit deadline, 1Click refunds the deposit to this NEAR account.",
        ...(warnings.length ? { warnings } : {}),
      },
    });
  }

  private async recipient(userId: string, self: string, chain: string, given?: string) {
    if (chain === "near") return given ? assertAccountId(given, "recipient") : self;
    if (EVM_CHAINS.has(chain)) {
      if (!given) {
        if (!this.cs) throw new NearPublicError("intents: Chain Signatures is not configured; pass recipient. Nothing was signed");
        return this.cs.fromAddress(userId);
      }
      if (!isAddress(given, { strict: false })) throw new NearPublicError("intents: recipient is not an EVM address; nothing was signed");
      return getAddress(given);
    }
    if (!given) throw new NearPublicError(`intents: pass recipient for delivery on ${chain}; only NEAR and EVM chains have a default. Nothing was signed`);
    if (!/^[A-Za-z0-9:._-]{8,100}$/.test(given)) throw new NearPublicError("intents: recipient has unexpected characters; nothing was signed");
    return given;
  }

  // The quote must echo exactly what was asked and name a fresh implicit
  // deposit account; anything else is refused before a preview exists.
  private checkQuote(q: OneClickQuote, request: Record<string, unknown>, self: string): string {
    const r = q?.quoteRequest ?? {};
    for (const k of ["swapType", "originAsset", "destinationAsset", "amount", "recipient", "refundTo", "depositType", "refundType", "recipientType", "slippageTolerance"])
      if (String(r[k]) !== String(request[k])) throw new NearPublicError(`intents: 1Click quote does not match the request (${k}); nothing was signed`);
    const d = q?.quote?.depositAddress;
    if (typeof d !== "string" || !IMPLICIT.test(d) || d === self) throw new NearPublicError("intents: 1Click returned an unexpected deposit address; nothing was signed");
    const { amountIn, amountOut, minAmountOut } = q.quote;
    if (amountIn !== request.amount || !UINT.test(amountOut) || !UINT.test(minAmountOut) || BigInt(minAmountOut) === 0n || BigInt(minAmountOut) > BigInt(amountOut))
      throw new NearPublicError("intents: 1Click quote amounts are inconsistent; nothing was signed");
    if (q.quote.depositMemo !== undefined && (typeof q.quote.depositMemo !== "string" || q.quote.depositMemo.length > 64)) throw new NearPublicError("intents: unexpected deposit memo; nothing was signed");
    return d;
  }

  async execute(userId: string, id: string, purpose: string) {
    const op = await this.store.operation(userId, id);
    if (!op || op.kind !== "intents_swap") throw new NearPublicError("operation not found for this user, or not an intents swap");
    const plan = (op.plan as { oneclick?: IntentsPlan } | null)?.oneclick;
    if (!plan) throw new NearPublicError("operation has no intents plan");
    if (op.status === "prepared" && Date.parse(plan.deadline) - DEADLINE_MARGIN_MS < this.now()) throw new NearPublicError("preview expired: the 1Click deposit deadline is too close; prepare a new swap. Nothing was signed");
    const r = await this.operations.execute(userId, id, purpose, "intents_swap", "FINAL") as Record<string, unknown>;
    let submitted: boolean | string = false;
    if (r.status === "confirmed" && !r.failed_receipts && typeof r.transaction_hash === "string") {
      try { await this.client.submit(r.transaction_hash, plan.deposit_address, op.accountId); submitted = true; }
      catch { submitted = "not acknowledged (1Click also detects the deposit on its own)"; }
    }
    return { ...r, intents: { deposit_address: plan.deposit_address, deposit_submitted: submitted, next: "Call intents_status with this operation_id until SUCCESS or REFUNDED." } };
  }

  async status(userId: string, id: string) {
    const op = await this.store.operation(userId, id);
    if (!op || op.kind !== "intents_swap") throw new NearPublicError("operation not found for this user, or not an intents swap");
    const plan = (op.plan as { oneclick: IntentsPlan }).oneclick;
    const near = await this.operations.status(userId, id) as Record<string, unknown>;
    if (near.status !== "confirmed") return { ...near, stage: "near_deposit", deposit_address: plan.deposit_address };
    const s = await this.client.status(plan.deposit_address);
    const d = s?.swapDetails ?? {};
    const hashes = (v: unknown) => Array.isArray(v) ? v.flatMap(x => typeof x?.hash === "string" ? [{ hash: x.hash.slice(0, 120), ...(typeof x.explorerUrl === "string" && /^https:\/\//.test(x.explorerUrl) ? { explorer_url: x.explorerUrl.slice(0, 300) } : {}) }] : []) : [];
    const clean = (v: unknown) => typeof v === "string" && UINT.test(v) ? v : undefined;
    return {
      operation_id: id, stage: "intents", near_transaction_hash: op.txHash, deposit_address: plan.deposit_address,
      swap_status: typeof s?.status === "string" ? s.status.replace(/[^A-Z_]/g, "").slice(0, 40) : "UNKNOWN",
      recipient: plan.recipient, minimum_out: plan.min_amount_out,
      ...(clean(d.amountOut) ? { amount_out: d.amountOut } : {}), ...(clean(d.refundedAmount) && d.refundedAmount !== "0" ? { refunded_amount: d.refundedAmount } : {}),
      origin_tx: hashes(d.originChainTxHashes), destination_tx: hashes(d.destinationChainTxHashes),
      note: "SUCCESS: delivered. PENDING_DEPOSIT/KNOWN_DEPOSIT_TX/PROCESSING: in progress, check again. REFUNDED: returned to this NEAR account. INCOMPLETE_DEPOSIT/FAILED: report the operation_id.",
    };
  }
}

function formatUnits(v: bigint, decimals: number): string {
  const s = v.toString().padStart(decimals + 1, "0");
  const whole = s.slice(0, s.length - decimals), frac = s.slice(s.length - decimals).replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}
