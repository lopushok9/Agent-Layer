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
// Gas is prepaid at max(gas price, 0.001 NEAR/TGas) and refunded, so limits
// are kept close to measured usage (storage/wrap/ft_transfer burn 2-5 TGas).
const STORAGE_GAS = 8n * GAS_PER_TGAS, WRAP_GAS = 8n * GAS_PER_TGAS, TRANSFER_GAS = 10n * GAS_PER_TGAS;
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
  origin_asset: assetRef.describe("What to sell: \"NEAR\", a 1Click assetId, or SYMBOL@chain. With pay_from wallet it must be a NEAR-chain token (NEAR is wrapped automatically); with pay_from intents any asset held in the intents balance (e.g. SOL@sol)"),
  destination_asset: assetRef.describe("What to receive: a 1Click assetId from intents_tokens, or SYMBOL@chain such as ETH@base, SOL@sol, USDC@near"),
  amount: z.string().regex(/^[1-9]\d{0,77}$/).describe("Exact amount to sell in the origin token's smallest unit (NEAR/wNEAR 24 decimals: 0.02 NEAR = \"20000000000000000000000\"; SOL 9)"),
  pay_from: z.enum(["wallet", "intents"]).default("wallet").describe("wallet: the NEAR account's own tokens; intents: its NEAR Intents balance (see intents_balances)"),
  deliver_to: z.enum(["chain", "intents"]).default("chain").describe("chain: deliver on the destination chain to recipient; intents: credit the NEAR account's NEAR Intents balance (no address on that chain needed, e.g. hold SOL inside the NEAR account)"),
  recipient: z.string().min(2).max(100).optional().describe("Only for deliver_to chain. Defaults to this NEAR account for NEAR assets and to its Chain Signatures EVM address for EVM chains; required elsewhere"),
  slippage_bps: z.number().int().min(1).max(500).default(100).describe("Accepted slippage below the quote in bps (100 = 1%); below the minimum the deposit is refunded"),
});
export type IntentsSwapInput = z.input<typeof intentsSwapInput>;
export const intentsTransferInput = z.strictObject({
  asset: assetRef.describe("\"NEAR\" or a NEAR-chain NEP-141 token (assetId or SYMBOL@near)"),
  amount: z.string().regex(/^[1-9]\d{0,77}$/).describe("Amount in the token's smallest unit"),
});

export type IntentsPlan = { deposit_address: string; deposit_memo: string | null; correlation_id: string | null; deadline: string; origin_asset: string; destination_asset: string; amount_in: string; min_amount_out: string; recipient: string; pay_from?: "wallet" | "intents"; deliver_to?: "chain" | "intents" };
export const INTENTS_CONTRACT = "intents.near";
// Deposits use 30 TGas like the near-intents.org app (FT_DEPOSIT_GAS): with an
// empty msg ft_on_transfer only credits the balance. ft_withdraw schedules
// ft_transfer plus a 15 TGas resolve. mt_transfer has no callbacks.
const MT_TRANSFER_GAS = 15n * GAS_PER_TGAS, FT_CALL_GAS = 30n * GAS_PER_TGAS, WITHDRAW_GAS = 50n * GAS_PER_TGAS;

export class NearIntents {
  constructor(private accounts: NearAccountService, private operations: NearOperations, private store: NearStore, private cs: ChainSignatures | null, private client = new OneClickClient(), private now: () => number = Date.now) {}
  private get rpc() { return this.accounts.rpc; }

  async tokens(input: z.infer<typeof intentsTokensInput>) {
    const b = input.blockchain?.toLowerCase(), s = input.symbol?.toUpperCase();
    const all = (await this.client.tokens()).filter(t => (!b || t.blockchain === b) && (!s || t.symbol.toUpperCase() === s));
    return { count: all.length, tokens: all.slice(0, 100).map(t => ({ asset_id: t.assetId, symbol: t.symbol, blockchain: t.blockchain, decimals: t.decimals, ...(t.price !== undefined ? { price_usd: t.price } : {}), ...(t.contractAddress ? { contract: t.contractAddress } : {}) })), ...(all.length > 100 ? { note: "Showing the first 100; filter by blockchain or symbol." } : {}), origin_note: "intents_swap_prepare sells NEAR-chain assets from the wallet (pay_from wallet) or any asset held in the intents balance (pay_from intents)." };
  }

  asset(ref: string, role: string) { return this.resolve(ref, role); }
  intentsBalanceOf(account: string, tokenId: string) { return this.intentsBalance(account, tokenId); }

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
    if (origin.assetId === dest.assetId) throw new NearPublicError("intents: origin and destination are the same asset; nothing was signed");
    if (p.deliver_to === "intents" && p.recipient) throw new NearPublicError("intents: deliver_to intents credits this NEAR account; do not pass recipient. Nothing was signed");
    const amount = BigInt(p.amount);
    const recipient = p.deliver_to === "intents" ? self : await this.recipient(userId, self, dest.blockchain, p.recipient);
    const call = (method: string, args: unknown, gas: bigint, depositYocto: bigint): NormalizedNearAction => ({ type: "function_call", method, args_base64: Buffer.from(JSON.stringify(args)).toString("base64"), gas: gas.toString(), deposit: depositYocto.toString() });
    const actions: NormalizedNearAction[] = [];
    let receiverId: string, wrap = 0n, funding: () => Promise<void>;
    let deposit = "";

    if (p.pay_from === "intents") {
      // Spend the intents balance: mt_transfer on intents.near, authorized by
      // this account as predecessor. Refunds return to the intents balance.
      if (!/^nep(141|245):/.test(origin.assetId)) throw new NearPublicError("intents: this origin_asset cannot be held in the intents balance; nothing was signed");
      await this.assertPredecessorAuth(self);
      const have = await this.intentsBalance(self, origin.assetId);
      if (have < amount) throw new NearPublicError(`intents: the intents balance holds ${have} of ${origin.symbol} (smallest units), needs ${amount}; see intents_balances. Nothing was signed`);
      receiverId = INTENTS_CONTRACT;
      funding = async () => { actions.push(call("mt_transfer", { receiver_id: deposit, token_id: origin.assetId, amount: p.amount }, MT_TRANSFER_GAS, 1n)); };
    } else {
      if (origin.blockchain !== "near" || !origin.assetId.startsWith("nep141:")) throw new NearPublicError("intents: with pay_from wallet, origin_asset must be a NEAR-chain NEP-141 token (blockchain near); use pay_from intents for assets in the intents balance. Nothing was signed");
      const contract = assertAccountId(origin.assetId.slice("nep141:".length), "origin contract");
      // Balances and storage before asking for a deposit address.
      const [balance, registered, bounds] = await Promise.all([this.ftView(contract, "ft_balance_of", { account_id: self }), this.ftView(contract, "storage_balance_of", { account_id: self }), this.ftView(contract, "storage_balance_bounds", {})]);
      const have = typeof balance === "string" && UINT.test(balance) ? BigInt(balance) : 0n;
      const storageMin = storageMinOf(bounds);
      wrap = contract === WRAP_NEAR && have < amount ? amount - have : 0n;
      if (have < amount && !wrap) throw new NearPublicError(`intents: the NEAR account holds ${have} of ${origin.symbol} (smallest units), needs ${amount}; nothing was signed`);
      receiverId = contract;
      if (registered === null) actions.push(call("storage_deposit", { account_id: self, registration_only: true }, STORAGE_GAS, storageMin));
      if (wrap) actions.push(call("near_deposit", {}, WRAP_GAS, wrap));
      funding = async () => {
        const depositRegistered = await this.ftView(contract, "storage_balance_of", { account_id: deposit });
        if (depositRegistered === null) actions.push(call("storage_deposit", { account_id: deposit, registration_only: true }, STORAGE_GAS, storageMin));
        actions.push(call("ft_transfer", { receiver_id: deposit, amount: p.amount, ...(q.quote.depositMemo ? { memo: q.quote.depositMemo } : {}) }, TRANSFER_GAS, 1n));
      };
    }

    const deadline = new Date(this.now() + QUOTE_DEADLINE_MS).toISOString();
    const source = p.pay_from === "intents" ? "INTENTS" : "ORIGIN_CHAIN";
    const request = { dry: false, swapType: "EXACT_INPUT", slippageTolerance: p.slippage_bps, originAsset: origin.assetId, depositType: source, destinationAsset: dest.assetId, amount: p.amount, refundTo: self, refundType: source, recipient, recipientType: p.deliver_to === "intents" ? "INTENTS" : "DESTINATION_CHAIN", deadline, quoteWaitingTimeMs: 3000 };
    const q = await this.client.quote(request);
    deposit = this.checkQuote(q, request, self);
    if (p.pay_from === "intents" && q.quote.depositMemo) throw new NearPublicError("intents: unexpected deposit memo for an intents-balance deposit; nothing was signed");
    await funding();

    const plan: IntentsPlan = { deposit_address: deposit, deposit_memo: q.quote.depositMemo ?? null, correlation_id: q.correlationId ?? null, deadline, origin_asset: origin.assetId, destination_asset: dest.assetId, amount_in: p.amount, min_amount_out: q.quote.minAmountOut, recipient, pay_from: p.pay_from, deliver_to: p.deliver_to };
    return this.operations.preview(userId, { receiverId, actions }, "intents_swap", { oneclick: plan }, { intents: this.describe(p, origin, dest, q, plan, wrap) });
  }

  // Pay 1Click from the intents balance without a NEAR transaction: the binding
  // quote (INTENTS deposit and refund) for a transfer intent that the caller
  // signs and the Solver Relay submits, as the near-intents.org app does.
  async quoteFromIntents(userId: string, input: IntentsSwapInput) {
    const p = intentsSwapInput.parse({ ...input, pay_from: "intents" });
    const self = (await this.accounts.account(userId)).accountId;
    const [origin, dest] = await Promise.all([this.resolve(p.origin_asset, "origin_asset"), this.resolve(p.destination_asset, "destination_asset")]);
    if (origin.assetId === dest.assetId) throw new NearPublicError("intents: origin and destination are the same asset; nothing was signed");
    if (!/^nep(141|245):/.test(origin.assetId)) throw new NearPublicError("intents: this origin_asset cannot be held in the intents balance; nothing was signed");
    if (p.deliver_to === "intents" && p.recipient) throw new NearPublicError("intents: deliver_to intents credits this NEAR account; do not pass recipient. Nothing was signed");
    const have = await this.intentsBalance(self, origin.assetId);
    if (have < BigInt(p.amount)) throw new NearPublicError(`intents: the intents balance holds ${have} of ${origin.symbol} (smallest units), needs ${p.amount}; see intents_balances. Nothing was signed`);
    const recipient = p.deliver_to === "intents" ? self : await this.recipient(userId, self, dest.blockchain, p.recipient);
    const deadline = new Date(this.now() + QUOTE_DEADLINE_MS).toISOString();
    const request = { dry: false, swapType: "EXACT_INPUT", slippageTolerance: p.slippage_bps, originAsset: origin.assetId, depositType: "INTENTS", destinationAsset: dest.assetId, amount: p.amount, refundTo: self, refundType: "INTENTS", recipient, recipientType: p.deliver_to === "intents" ? "INTENTS" : "DESTINATION_CHAIN", deadline, quoteWaitingTimeMs: 3000 };
    const q = await this.client.quote(request);
    const deposit = this.checkQuote(q, request, self);
    if (q.quote.depositMemo) throw new NearPublicError("intents: unexpected deposit memo for an intents-balance deposit; nothing was signed");
    const plan: IntentsPlan = { deposit_address: deposit, deposit_memo: null, correlation_id: q.correlationId ?? null, deadline, origin_asset: origin.assetId, destination_asset: dest.assetId, amount_in: p.amount, min_amount_out: q.quote.minAmountOut, recipient, pay_from: "intents", deliver_to: p.deliver_to };
    return { self, plan, have, description: this.describe(p, origin, dest, q, plan, 0n) };
  }

  submitDeposit(txHash: string, depositAddress: string, sender: string) { return this.client.submit(txHash, depositAddress, sender); }

  private describe(p: z.infer<typeof intentsSwapInput>, origin: OneClickToken, dest: OneClickToken, q: OneClickQuote, plan: IntentsPlan, wrap: bigint) {
    const fmt = (v: string, d: number) => formatUnits(BigInt(v), d);
    const warnings: string[] = [];
    if (p.recipient) warnings.push(`Recipient ${plan.recipient} was given explicitly; check it, delivery to a wrong address is irreversible.`);
    if (p.deliver_to === "chain" && EVM_CHAINS.has(dest.blockchain) && !SPENDABLE_EVM.has(dest.blockchain)) warnings.push(`Delivery on ${dest.blockchain}: the same key controls the address there, but this server's EVM tools only send on Base and Ethereum.`);
    const fees = q.quoteRequest.appFees;
    return {
      protocol: "near_intents_1click", pay_from: p.pay_from, deliver_to: p.deliver_to,
      origin: { asset_id: origin.assetId, symbol: origin.symbol, amount: p.amount, formatted: fmt(p.amount, origin.decimals), ...(wrap ? { wraps_near_yocto: wrap.toString(), wraps_near: fmt(wrap.toString(), 24) } : {}) },
      destination: { asset_id: dest.assetId, symbol: dest.symbol, blockchain: dest.blockchain, quoted: q.quote.amountOut, quoted_formatted: fmt(q.quote.amountOut, dest.decimals), minimum: q.quote.minAmountOut, minimum_formatted: fmt(q.quote.minAmountOut, dest.decimals), ...(q.quote.amountOutUsd ? { quoted_usd: q.quote.amountOutUsd } : {}) },
      ...(q.quote.amountInUsd ? { amount_in_usd: q.quote.amountInUsd } : {}),
      recipient: plan.recipient, refund_to: plan.pay_from === "intents" ? `intents balance of ${String(q.quoteRequest.refundTo)}` : String(q.quoteRequest.refundTo), deposit_address: plan.deposit_address, ...(q.quote.depositMemo ? { deposit_memo: q.quote.depositMemo } : {}),
      deposit_deadline: plan.deadline, ...(q.quote.timeEstimate !== undefined ? { time_estimate_seconds: q.quote.timeEstimate } : {}),
      ...(Array.isArray(fees) && fees.length ? { app_fees_bps: fees.map((f: any) => Number(f?.fee) || 0).reduce((a: number, b: number) => a + b, 0) } : {}),
      ...(q.quote.withdrawFee ? { destination_withdraw_fee: q.quote.withdrawFee } : {}),
      protection: `Solvers must deliver at least the minimum to the recipient; otherwise, or after the deposit deadline, 1Click refunds the deposit to this NEAR account${p.pay_from === "intents" ? "'s intents balance" : ""}.`,
      ...(warnings.length ? { warnings } : {}),
    };
  }

  private async assertPredecessorAuth(self: string) {
    const r = await this.ftView(INTENTS_CONTRACT, "is_auth_by_predecessor_id_enabled", { account_id: self });
    if (r !== true) throw new NearPublicError("intents: this account has disabled direct transactions on intents.near; nothing was signed");
  }

  private async intentsBalance(self: string, tokenId: string): Promise<bigint> {
    const r = await this.ftView(INTENTS_CONTRACT, "mt_balance_of", { account_id: self, token_id: tokenId });
    return typeof r === "string" && UINT.test(r) ? BigInt(r) : 0n;
  }

  // Everything held for this NEAR account inside intents.near (NEP-245),
  // labelled with 1Click metadata where known.
  async balances(userId: string) {
    const self = (await this.accounts.account(userId)).accountId;
    const owned = await this.ftView(INTENTS_CONTRACT, "mt_tokens_for_owner", { account_id: self, from_index: "0", limit: 200 });
    const ids = (Array.isArray(owned) ? owned : []).flatMap(t => typeof (t as any)?.token_id === "string" && (t as any).token_id.length < 300 ? [(t as any).token_id as string] : []);
    const amounts = ids.length ? await this.ftView(INTENTS_CONTRACT, "mt_batch_balance_of", { account_id: self, token_ids: ids }) : [];
    const meta = new Map((await this.client.tokens()).map(t => [t.assetId, t]));
    const balances = ids.flatMap((id, i) => {
      const raw = Array.isArray(amounts) ? amounts[i] : null;
      if (typeof raw !== "string" || !UINT.test(raw) || raw === "0") return [];
      const m = meta.get(id);
      const formatted = m ? formatUnits(BigInt(raw), m.decimals) : undefined;
      return [{ asset_id: id, amount: raw, ...(m ? { symbol: m.symbol, blockchain: m.blockchain, decimals: m.decimals, formatted, ...(m.price !== undefined ? { value_usd: Math.round(Number(formatted) * m.price * 100) / 100 } : {}) } : { note: "not listed by 1Click" }) }];
    });
    return {
      account_id: self, contract: INTENTS_CONTRACT, balances,
      total_value_usd: Math.round(balances.reduce((s, b) => s + (("value_usd" in b ? b.value_usd : 0) ?? 0), 0) * 100) / 100,
      note: "Assets in the NEAR Intents balance belong to this NEAR account and are spent only by its key: swap them with intents_swap_prepare pay_from intents, move NEAR-chain tokens back with intents_withdraw_prepare.",
    };
  }

  // Wallet -> intents balance: ft_transfer_call to intents.near (empty msg
  // credits the sender). NEAR is wrapped first. Executed with near_transaction_execute.
  async prepareDeposit(userId: string, input: z.input<typeof intentsTransferInput>) {
    const p = intentsTransferInput.parse(input);
    const self = (await this.accounts.account(userId)).accountId;
    const token = await this.resolve(p.asset, "asset");
    if (token.blockchain !== "near" || !token.assetId.startsWith("nep141:")) throw new NearPublicError("intents: only NEAR-chain NEP-141 tokens are deposited from the wallet; other chains arrive through intents_swap_prepare deliver_to intents. Nothing was signed");
    const contract = assertAccountId(token.assetId.slice("nep141:".length), "asset contract");
    const amount = BigInt(p.amount);
    const [balance, registered, bounds] = await Promise.all([this.ftView(contract, "ft_balance_of", { account_id: self }), this.ftView(contract, "storage_balance_of", { account_id: self }), this.ftView(contract, "storage_balance_bounds", {})]);
    const have = typeof balance === "string" && UINT.test(balance) ? BigInt(balance) : 0n;
    const wrap = contract === WRAP_NEAR && have < amount ? amount - have : 0n;
    if (have < amount && !wrap) throw new NearPublicError(`intents: the NEAR account holds ${have} of ${token.symbol} (smallest units), needs ${amount}; nothing was signed`);
    const call = (method: string, args: unknown, gas: bigint, d: bigint): NormalizedNearAction => ({ type: "function_call", method, args_base64: Buffer.from(JSON.stringify(args)).toString("base64"), gas: gas.toString(), deposit: d.toString() });
    const actions: NormalizedNearAction[] = [];
    if (registered === null) actions.push(call("storage_deposit", { account_id: self, registration_only: true }, STORAGE_GAS, storageMinOf(bounds)));
    if (wrap) actions.push(call("near_deposit", {}, WRAP_GAS, wrap));
    actions.push(call("ft_transfer_call", { receiver_id: INTENTS_CONTRACT, amount: p.amount, msg: "" }, FT_CALL_GAS, 1n));
    return this.operations.preview(userId, { receiverId: contract, actions }, "near_tx", null, {
      intents_deposit: { asset_id: token.assetId, symbol: token.symbol, amount: p.amount, formatted: formatUnits(amount, token.decimals), credited_to: self, contract: INTENTS_CONTRACT, ...(wrap ? { wraps_near: formatUnits(wrap, 24) } : {}) },
      next: "After confirmation execute with near_transaction_execute; then intents_balances.",
    });
  }

  // Intents balance -> wallet for NEAR-chain NEP-141 tokens: ft_withdraw on
  // intents.near, authorized by this account as predecessor.
  async prepareWithdraw(userId: string, input: z.input<typeof intentsTransferInput>) {
    const p = intentsTransferInput.parse(input);
    const self = (await this.accounts.account(userId)).accountId;
    const token = await this.resolve(p.asset, "asset");
    if (token.blockchain !== "near" || !token.assetId.startsWith("nep141:")) throw new NearPublicError("intents: withdraw to the wallet works for NEAR-chain NEP-141 tokens; for other chains use intents_swap_prepare with pay_from intents and deliver_to chain. Nothing was signed");
    const contract = assertAccountId(token.assetId.slice("nep141:".length), "asset contract");
    const amount = BigInt(p.amount);
    await this.assertPredecessorAuth(self);
    const [have, registered] = await Promise.all([this.intentsBalance(self, token.assetId), this.ftView(contract, "storage_balance_of", { account_id: self })]);
    if (have < amount) throw new NearPublicError(`intents: the intents balance holds ${have} of ${token.symbol} (smallest units), needs ${amount}; nothing was signed`);
    if (registered === null) throw new NearPublicError(`intents: this account is not registered on ${contract}; first call storage_deposit there (near_transaction_prepare) or the withdrawal is refunded. Nothing was signed`);
    const action: NormalizedNearAction = { type: "function_call", method: "ft_withdraw", args_base64: Buffer.from(JSON.stringify({ token: contract, receiver_id: self, amount: p.amount })).toString("base64"), gas: WITHDRAW_GAS.toString(), deposit: "1" };
    return this.operations.preview(userId, { receiverId: INTENTS_CONTRACT, actions: [action] }, "near_tx", null, {
      intents_withdraw: { asset_id: token.assetId, symbol: token.symbol, amount: p.amount, formatted: formatUnits(amount, token.decimals), from: INTENTS_CONTRACT, to: self, ...(contract === WRAP_NEAR ? { note: "Arrives as wNEAR; unwrap with near_withdraw on wrap.near if native NEAR is needed." } : {}) },
      next: "After confirmation execute with near_transaction_execute; then intents_balances.",
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
    return { operation_id: id, stage: "intents", near_transaction_hash: op.txHash, ...(await this.oneClickStatus(plan)) };
  }

  // 1Click's view of a funded deposit address (shared with relay-funded swaps).
  async oneClickStatus(plan: IntentsPlan) {
    const s = await this.client.status(plan.deposit_address);
    const d = s?.swapDetails ?? {};
    const hashes = (v: unknown) => Array.isArray(v) ? v.flatMap(x => typeof x?.hash === "string" ? [{ hash: x.hash.slice(0, 120), ...(typeof x.explorerUrl === "string" && /^https:\/\//.test(x.explorerUrl) ? { explorer_url: x.explorerUrl.slice(0, 300) } : {}) }] : []) : [];
    const clean = (v: unknown) => typeof v === "string" && UINT.test(v) ? v : undefined;
    return {
      deposit_address: plan.deposit_address,
      swap_status: typeof s?.status === "string" ? s.status.replace(/[^A-Z_]/g, "").slice(0, 40) : "UNKNOWN",
      recipient: plan.recipient, minimum_out: plan.min_amount_out,
      ...(clean(d.amountOut) ? { amount_out: d.amountOut } : {}), ...(clean(d.refundedAmount) && d.refundedAmount !== "0" ? { refunded_amount: d.refundedAmount } : {}),
      origin_tx: hashes(d.originChainTxHashes), destination_tx: hashes(d.destinationChainTxHashes),
      note: `SUCCESS: delivered. PENDING_DEPOSIT/KNOWN_DEPOSIT_TX/PROCESSING: in progress, check again. REFUNDED: returned to this NEAR account${plan.pay_from === "intents" ? "'s intents balance" : ""}. INCOMPLETE_DEPOSIT/FAILED: report the operation_id.`,
    };
  }
}

function formatUnits(v: bigint, decimals: number): string {
  const s = v.toString().padStart(decimals + 1, "0");
  const whole = s.slice(0, s.length - decimals), frac = s.slice(s.length - decimals).replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}

function storageMinOf(bounds: unknown): bigint {
  const v = String((bounds as { min?: unknown } | null)?.min ?? "0");
  return UINT.test(v) ? BigInt(v) : 0n;
}
