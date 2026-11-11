import { createHash, randomBytes } from "node:crypto";
import { baseEncode } from "@near-js/utils";
import { z } from "zod";
import type { NearAccountService } from "./account.js";
import { INTENTS_CONTRACT, WRAP_NEAR, type IntentsPlan, type IntentsSwapInput, type NearIntents } from "./intents.js";
import { NearPublicError } from "./operations.js";
import { NearRpcError } from "./rpc.js";
import type { NearStore } from "./store.js";

// Signed NEAR Intents published through the Solver Relay. The NEAR account
// signs NEP-413 messages for intents.near with its own key and the relay
// submits execute_intents and pays the gas, so nothing here needs NEAR in the
// wallet:
// - trades: token_diff against a solver quote, optionally followed in the same
//   signed message by a withdrawal of the bought amount to the wallet;
// - withdrawals: ft_withdraw to the wallet, or native_withdraw of wNEAR as
//   native NEAR (which also refills gas for the wallet);
// - 1Click swaps paid from the intents balance: a transfer intent to the
//   quote's deposit address, as the near-intents.org app does.
export const SOLVER_RELAY_URL = "https://solver-relay-v2.chaindefuser.com/rpc";
const NEP413_TAG = 2147484061; // 2^31 + 413
const VERSIONED_NONCE_PREFIX = Buffer.from("5628f6c6", "hex");
const QUOTE_WINDOW_MS = 60_000;
const INTENT_LIFETIME_MS = 45_000;
const UINT = /^\d{1,78}$/;
const TOKEN_ID = /^nep(141|245):[a-z0-9._:-]{2,200}$/i;
const WNEAR_ID = `nep141:${WRAP_NEAR}`;
// ft_withdraw's ft_transfer, as used by the official intents SDK (+10% margin).
const FT_WITHDRAW_MIN_GAS = "17050000000000";
// The signed transfer must settle well before the 1Click deposit deadline.
const ONECLICK_MARGIN_MS = 2 * 60_000;

// ---- NEP-413 ----
export type Nep413Payload = { message: string; nonce: Buffer; recipient: string };
function borshString(s: string): Buffer {
  const b = Buffer.from(s, "utf8"), len = Buffer.alloc(4);
  len.writeUInt32LE(b.length);
  return Buffer.concat([len, b]);
}
export function nep413Prehash(p: Nep413Payload): Buffer {
  if (p.nonce.length !== 32) throw new Error("NEP-413 nonce must be 32 bytes");
  const tag = Buffer.alloc(4);
  tag.writeUInt32LE(NEP413_TAG);
  // (tag, { message, nonce: [u8;32], recipient, callback_url: None })
  return createHash("sha256").update(Buffer.concat([tag, borshString(p.message), p.nonce, borshString(p.recipient), Buffer.from([0])])).digest();
}
// Versioned nonce V1 accepted by intents.near:
// prefix(4) || version 0 || salt(4) || deadline i64 ns LE (8) || random(15).
export function versionedNonce(saltHex: string, deadlineMs: number, random: Buffer = randomBytes(15)): Buffer {
  if (!/^[0-9a-f]{8}$/.test(saltHex)) throw new Error("invalid intents salt");
  const deadline = Buffer.alloc(8);
  deadline.writeBigInt64LE(BigInt(deadlineMs) * 1_000_000n);
  return Buffer.concat([VERSIONED_NONCE_PREFIX, Buffer.from([0]), Buffer.from(saltHex, "hex"), deadline, random.subarray(0, 15)]);
}
export type IntentJson = Record<string, unknown> & { intent: string };
export function intentsMessage(signerId: string, deadline: string, intents: IntentJson[]): string {
  return JSON.stringify({ signer_id: signerId, deadline, intents });
}
export function tokenDiffMessage(signerId: string, deadline: string, diff: Record<string, string>): string {
  return intentsMessage(signerId, deadline, [{ intent: "token_diff", diff }]);
}
// Moves `amount` of a NEAR-chain token from the intents balance to `receiver`:
// wNEAR arrives as native NEAR (no storage needed); other NEP-141 tokens via
// ft_transfer, which intents.near refunds to the intents balance if it fails.
export function withdrawIntent(assetId: string, amount: string, receiver: string, storageDeposit?: string): IntentJson {
  if (assetId === WNEAR_ID) return { intent: "native_withdraw", receiver_id: receiver, amount };
  if (!assetId.startsWith("nep141:")) throw new Error("only NEP-141 tokens can be withdrawn to a NEAR account");
  return { intent: "ft_withdraw", token: assetId.slice("nep141:".length), receiver_id: receiver, amount, ...(storageDeposit ? { storage_deposit: storageDeposit } : {}), min_gas: FT_WITHDRAW_MIN_GAS };
}

// ---- Relay client ----
export type RelayQuote = { quote_hash: string; amount_in: string; amount_out: string; expiration_time: string; defuse_asset_identifier_in: string; defuse_asset_identifier_out: string };
export class SolverRelayClient {
  constructor(private url = SOLVER_RELAY_URL, private fetcher: typeof fetch = globalThis.fetch, private apiKey?: string) {}
  private async rpc<T>(method: string, params: unknown): Promise<T> {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (this.apiKey) headers.authorization = `Bearer ${this.apiKey}`;
    let res: Response;
    try { res = await this.fetcher(this.url, { method: "POST", headers, body: JSON.stringify({ id: 1, jsonrpc: "2.0", method, params: [params] }), signal: AbortSignal.timeout(15_000) }); }
    catch { throw new SolverRelayUnreachable(); }
    const body = await res.json().catch(() => null) as { result?: T; error?: { message?: string } } | null;
    if (!res.ok || !body || body.error) throw new NearPublicError(`intents: the Solver Relay refused ${method} (${clean(String(body?.error?.message ?? `HTTP ${res.status}`))})`);
    return body.result as T;
  }
  async quote(tokenIn: string, tokenOut: string, amountIn: string): Promise<RelayQuote[]> {
    const r = await this.rpc<unknown[] | null>("quote", { defuse_asset_identifier_in: tokenIn, defuse_asset_identifier_out: tokenOut, exact_amount_in: amountIn, min_deadline_ms: QUOTE_WINDOW_MS });
    return (Array.isArray(r) ? r : []).filter((q): q is RelayQuote => {
      const x = q as Record<string, unknown>;
      return typeof x?.quote_hash === "string" && x.quote_hash.length < 100 && typeof x.amount_out === "string" && UINT.test(x.amount_out) && x.amount_in === amountIn
        && x.defuse_asset_identifier_in === tokenIn && x.defuse_asset_identifier_out === tokenOut && typeof x.expiration_time === "string" && !Number.isNaN(Date.parse(x.expiration_time));
    });
  }
  // publish_intents as the official SDK uses it: quote hashes for solver
  // matches, none for intents that need no counterparty (withdrawals).
  publish(quoteHashes: string[], signed: SignedNep413) { return this.rpc<{ status: string; intent_hashes?: string[]; reason?: string }>("publish_intents", { quote_hashes: quoteHashes, signed_datas: [signed] }); }
  status(intentHash: string) { return this.rpc<{ status: string; status_details?: string; data?: { hash?: string }; filled_amounts?: string[] }>("get_status", { intent_hash: intentHash }); }
}
export class SolverRelayUnreachable extends Error { constructor() { super("Solver Relay unreachable"); } }
export type SignedNep413 = { standard: "nep413"; payload: { recipient: string; nonce: string; message: string }; public_key: string; signature: string };
const clean = (s: string, n = 160) => s.replace(/[^\x20-\x7e]/g, "").slice(0, n);

export const intentsTradeInput = z.strictObject({
  token_in: z.string().min(2).max(200).describe("Asset to sell from the intents balance: 1Click assetId (e.g. nep141:wrap.near), \"NEAR\" for wNEAR, or SYMBOL@chain such as USDC@near, SOL@sol"),
  token_out: z.string().min(2).max(200).describe("Asset to buy, same formats"),
  amount_in: z.string().regex(/^[1-9]\d{0,77}$/).describe("Exact amount to sell, in token_in's smallest unit"),
  slippage_bps: z.number().int().min(1).max(500).default(50).describe("At execution the best fresh quote must give at least the previewed quote minus this many bps, otherwise nothing is signed"),
  deliver_to: z.enum(["intents", "wallet"]).default("intents").describe("intents: keep the bought asset in the intents balance; wallet: withdraw it to the NEAR wallet in the same signed intent (NEAR-chain tokens only; NEAR arrives as native NEAR)"),
});
export const intentsExchangeInput = z.strictObject({
  token_in: z.string().min(2).max(200).describe("Asset to sell from the intents balance: \"NEAR\" for wNEAR, a 1Click assetId, or SYMBOL@chain such as USDC@near, SOL@sol"),
  token_out: z.string().min(2).max(200).describe("Asset to buy, same formats"),
  amount_in: z.string().regex(/^[1-9]\d{0,77}$/).describe("Exact amount to sell, in token_in's smallest unit"),
  slippage_bps: z.number().int().min(1).max(500).default(50).describe("Minimum accepted below the quote, in bps"),
  deliver_to: z.enum(["intents", "wallet"]).default("intents").describe("intents: keep the bought asset in the intents balance; wallet: deliver it to the NEAR wallet (NEAR-chain tokens only)"),
});
// Prefer the Solver Relay (one settlement, seconds) unless 1Click pays this much more.
const RELAY_PREFERENCE_BPS = 50n;
export const intentsWithdrawInput = z.strictObject({
  asset: z.string().min(2).max(200).describe("\"NEAR\" (arrives as native NEAR, e.g. to refill gas) or a NEAR-chain NEP-141 token held in the intents balance (assetId or SYMBOL@near)"),
  amount: z.string().regex(/^[1-9]\d{0,77}$/).describe("Amount in the token's smallest unit (NEAR: yocto, 24 decimals)"),
});
export type IntentsTradePlan = { token_in: string; token_out: string; amount_in: string; quoted_out: string; min_amount_out: string; deliver_to?: "intents" | "wallet"; storage_deposit?: string | null };
export type IntentsWithdrawPlan = { asset_id: string; amount: string; receiver_id: string; storage_deposit: string | null };
type SignedPlan = { trade: IntentsTradePlan } | { withdraw: IntentsWithdrawPlan } | { oneclick: IntentsPlan };
type PlanKind = "trade" | "withdraw" | "oneclick";
const KIND_NAME: Record<PlanKind, string> = { trade: "intents_trade", withdraw: "intents_withdraw", oneclick: "intents_swap" };
const planKind = (plan: SignedPlan): PlanKind => "trade" in plan ? "trade" : "withdraw" in plan ? "withdraw" : "oneclick";
const transferIntent = (plan: IntentsPlan): IntentJson => ({ intent: "transfer", receiver_id: plan.deposit_address, tokens: { [plan.origin_asset]: plan.amount_in } });
type Asset = { assetId: string; symbol: string; decimals: number; blockchain?: string };

export class IntentsTrades {
  constructor(private accounts: NearAccountService, private store: NearStore, private intents: NearIntents, private relay = new SolverRelayClient(), private now: () => number = Date.now) {}
  private get rpc() { return this.accounts.rpc; }
  private async view(contract: string, method: string, args: unknown) { return (await this.rpc.callFunction(contract, method, args)).result; }
  // Plans round-trip through Postgres jsonb, which reorders object keys, so the
  // binding hashes a key-sorted encoding.
  private fingerprint(accountId: string, publicKey: string, plan: unknown) { return createHash("sha256").update(canonicalJson(["intents-signed:v2", accountId, publicKey, plan])).digest("hex"); }

  private async bestQuote(tokenIn: string, tokenOut: string, amountIn: string) {
    const quotes = await this.relay.quote(tokenIn, tokenOut, amountIn);
    const live = quotes.filter(q => Date.parse(q.expiration_time) > this.now() + 5_000);
    return { count: live.length, best: live.reduce<RelayQuote | null>((b, q) => !b || BigInt(q.amount_out) > BigInt(b.amount_out) ? q : b, null) };
  }

  // Delivery to the NEAR wallet: NEAR-chain NEP-141 only. A token the wallet is
  // not registered on gets storage_deposit paid from wNEAR in the intents
  // balance; without that wNEAR the withdrawal would only bounce back.
  private async walletDelivery(self: string, asset: Asset, role: string): Promise<{ storage: bigint }> {
    if (!asset.assetId.startsWith("nep141:") || (asset.blockchain && asset.blockchain !== "near"))
      throw new NearPublicError(`intents: ${role} ${asset.symbol} is not a NEAR-chain token and cannot be held in the NEAR wallet; keep it in the intents balance or send it to its chain with intents_swap_prepare. Nothing was signed`);
    if (asset.assetId === WNEAR_ID) return { storage: 0n };
    const contract = asset.assetId.slice("nep141:".length);
    const [registered, bounds] = await Promise.all([this.view(contract, "storage_balance_of", { account_id: self }), this.view(contract, "storage_balance_bounds", {})]);
    if (registered !== null && registered !== undefined) return { storage: 0n };
    const min = String((bounds as { min?: unknown } | null)?.min ?? "");
    if (!UINT.test(min)) throw new NearPublicError(`intents: ${contract} did not report its storage deposit; nothing was signed`);
    return { storage: BigInt(min) };
  }

  private async assertStorageFunds(self: string, storage: bigint, alsoSpent: bigint, symbol: string) {
    const wnear = await this.intents.intentsBalanceOf(self, WNEAR_ID);
    if (wnear < storage + alsoSpent) throw new NearPublicError(`intents: the NEAR wallet is not registered on ${symbol}; registering costs ${formatUnits(storage, 24)} NEAR, paid from wNEAR in the intents balance, which holds too little. Register first with near_transaction_prepare (storage_deposit on the token) or keep the asset in the intents balance. Nothing was signed`);
  }

  private async preview(userId: string, account: { accountId: string; publicKey: string }, plan: SignedPlan, description: unknown) {
    const fingerprint = this.fingerprint(account.accountId, account.publicKey, plan);
    return this.store.createOperation({ userId, network: this.accounts.config.network, accountId: account.accountId, publicKey: account.publicKey, kind: "intents_trade", receiverId: INTENTS_CONTRACT, actions: [], descriptions: [description], plan, fingerprint }, this.accounts.config.previewTtlSeconds);
  }

  async prepare(userId: string, input: z.input<typeof intentsTradeInput>) {
    const p = intentsTradeInput.parse(input);
    const account = await this.accounts.account(userId);
    const self = account.accountId;
    const [tin, tout] = await Promise.all([this.intents.asset(p.token_in, "token_in"), this.intents.asset(p.token_out, "token_out")]);
    if (!TOKEN_ID.test(tin.assetId) || !TOKEN_ID.test(tout.assetId)) throw new NearPublicError("intents: both tokens must be NEP-141/NEP-245 assets held on intents.near; nothing was signed");
    if (tin.assetId === tout.assetId) throw new NearPublicError("intents: token_in and token_out are the same; nothing was signed");
    const toWallet = p.deliver_to === "wallet";
    const storage = toWallet ? (await this.walletDelivery(self, tout, "token_out")).storage : 0n;
    const have = await this.intents.intentsBalanceOf(self, tin.assetId);
    if (have < BigInt(p.amount_in)) throw new NearPublicError(`intents: the intents balance holds ${have} of ${tin.symbol} (smallest units), needs ${p.amount_in}; see intents_balances. Nothing was signed`);
    if (storage) await this.assertStorageFunds(self, storage, tin.assetId === WNEAR_ID ? BigInt(p.amount_in) : 0n, tout.symbol);
    const { count, best } = await this.bestQuote(tin.assetId, tout.assetId, p.amount_in);
    if (!best) throw new NearPublicError(`intents: no solver quotes ${tin.symbol} -> ${tout.symbol} for this amount right now (small sizes and illiquid pairs often get none; try a larger amount, route via USDC, or use intents_swap_prepare with pay_from intents, which goes through 1Click). Nothing was signed`);
    const minOut = BigInt(best.amount_out) * BigInt(10_000 - p.slippage_bps) / 10_000n;
    const plan: IntentsTradePlan = { token_in: tin.assetId, token_out: tout.assetId, amount_in: p.amount_in, quoted_out: best.amount_out, min_amount_out: minOut.toString(), deliver_to: p.deliver_to, storage_deposit: storage ? storage.toString() : null };
    const nativeOut = toWallet && tout.assetId === WNEAR_ID;
    const description = { type: "nep413_intents", verifying_contract: INTENTS_CONTRACT, signer_id: self, intents: ["token_diff", ...(toWallet ? [nativeOut ? "native_withdraw" : "ft_withdraw"] : [])], sell: { asset_id: tin.assetId, amount: p.amount_in }, buy_at_least: { asset_id: tout.assetId, amount: minOut.toString() }, deliver_to: toWallet ? self : `intents balance of ${self}` };
    const op = await this.preview(userId, account, { trade: plan }, description);
    const fmt = (v: string, d: number) => formatUnits(BigInt(v), d);
    return {
      operation_id: op.id, kind: "intents_trade", signer_id: self, verifying_contract: INTENTS_CONTRACT,
      sell: { asset_id: tin.assetId, symbol: tin.symbol, amount: p.amount_in, formatted: fmt(p.amount_in, tin.decimals) },
      buy: { asset_id: tout.assetId, symbol: nativeOut ? "NEAR (native)" : tout.symbol, quoted: best.amount_out, quoted_formatted: fmt(best.amount_out, tout.decimals), minimum: minOut.toString(), minimum_formatted: fmt(minOut.toString(), tout.decimals) },
      deliver_to: toWallet ? { wallet: self, how: nativeOut ? "native_withdraw in the same signed message: arrives as native NEAR" : "ft_withdraw in the same signed message; if the token transfer fails the tokens return to the intents balance" } : { intents_balance: self },
      ...(storage ? { storage_deposit: { contract: tout.assetId.slice("nep141:".length), near: fmt(storage.toString(), 24), paid_from: "wNEAR in the intents balance (registers the wallet on the token, not refundable)" } } : {}),
      solver_quotes: count, slippage_bps: p.slippage_bps, intents_balance_before: { [tin.symbol]: fmt(have.toString(), tin.decimals) },
      network_fee: "none for this account: the relay submits and pays for the settlement transaction",
      expires_at: op.expiresAt.toISOString(),
      how_it_executes: `At execution the server takes a fresh solver quote, refuses if it is below the minimum, and signs ONE NEP-413 message with this NEAR account's key: token_diff (-${p.amount_in} ${tin.assetId}, +quoted ${tout.assetId})${toWallet ? ", then the withdrawal of exactly that amount to the wallet" : ""}; ${INTENT_LIFETIME_MS / 1000}s deadline, single-use nonce. intents.near settles the message atomically or not at all.`,
      confirmation: "Show sell, buy (quoted and minimum), deliver_to and the signed-message description to the user; call intents_trade_execute only after they confirm this exact preview.",
    };
  }

  // Intents balance -> NEAR wallet, signed and relayed: no NEAR gas needed, so
  // it also works to refill an empty wallet with native NEAR.
  async prepareWithdraw(userId: string, input: z.input<typeof intentsWithdrawInput>) {
    const p = intentsWithdrawInput.parse(input);
    const account = await this.accounts.account(userId);
    const self = account.accountId;
    const asset = await this.intents.asset(p.asset, "asset");
    const { storage } = await this.walletDelivery(self, asset, "asset");
    const amount = BigInt(p.amount);
    const have = await this.intents.intentsBalanceOf(self, asset.assetId);
    if (have < amount) throw new NearPublicError(`intents: the intents balance holds ${have} of ${asset.symbol} (smallest units), needs ${p.amount}; see intents_balances. Nothing was signed`);
    if (storage) await this.assertStorageFunds(self, storage, 0n, asset.symbol);
    const native = asset.assetId === WNEAR_ID;
    const plan: IntentsWithdrawPlan = { asset_id: asset.assetId, amount: p.amount, receiver_id: self, storage_deposit: storage ? storage.toString() : null };
    const intent = withdrawIntent(plan.asset_id, plan.amount, self, plan.storage_deposit ?? undefined);
    const op = await this.preview(userId, account, { withdraw: plan }, { type: "nep413_intents", verifying_contract: INTENTS_CONTRACT, signer_id: self, intents: [intent] });
    return {
      operation_id: op.id, kind: "intents_withdraw", signer_id: self, verifying_contract: INTENTS_CONTRACT,
      withdraw: { asset_id: asset.assetId, symbol: native ? "NEAR (native)" : asset.symbol, amount: p.amount, formatted: formatUnits(amount, asset.decimals), to: self, intent },
      ...(storage ? { storage_deposit: { near: formatUnits(storage, 24), paid_from: "wNEAR in the intents balance (registers the wallet on the token, not refundable)" } } : {}),
      intents_balance_before: formatUnits(have, asset.decimals),
      network_fee: "none for this account: the relay submits and pays for the transaction",
      expires_at: op.expiresAt.toISOString(),
      how_it_executes: `At execution the server signs ONE NEP-413 ${intent.intent} intent with this NEAR account's key (${INTENT_LIFETIME_MS / 1000}s deadline, single-use nonce), dry-runs it on intents.near and publishes it to the Solver Relay.${native ? " wNEAR is unwrapped and arrives as native NEAR." : " If the token transfer fails, intents.near returns the tokens to the intents balance."}`,
      confirmation: "Show withdraw and any storage_deposit to the user; call intents_withdraw_execute only after they confirm this exact preview.",
    };
  }

  // One entry point for swaps from the intents balance: ask the Solver Relay and
  // 1Click (non-binding) in parallel, take the relay when it quotes within
  // RELAY_PREFERENCE_BPS of 1Click (single settlement, seconds), otherwise
  // 1Click (any pair, ~20-60 s), then return that route's normal preview.
  async prepareAuto(userId: string, input: z.input<typeof intentsExchangeInput>) {
    const p = intentsExchangeInput.parse(input);
    const self = (await this.accounts.account(userId)).accountId;
    const [tin, tout] = await Promise.all([this.intents.asset(p.token_in, "token_in"), this.intents.asset(p.token_out, "token_out")]);
    if (tin.assetId === tout.assetId) throw new NearPublicError("intents: token_in and token_out are the same; nothing was signed");
    const toWallet = p.deliver_to === "wallet";
    const storage = toWallet ? (await this.walletDelivery(self, tout, "token_out")).storage : 0n;
    const have = await this.intents.intentsBalanceOf(self, tin.assetId);
    if (have < BigInt(p.amount_in)) throw new NearPublicError(`intents: the intents balance holds ${have} of ${tin.symbol} (smallest units), needs ${p.amount_in}; see intents_balances. Nothing was signed`);
    const oneclickInput = { origin_asset: tin.assetId, destination_asset: tout.assetId, amount: p.amount_in, deliver_to: toWallet ? "chain" as const : "intents" as const, slippage_bps: p.slippage_bps };
    const [relay, oneclick] = await Promise.all([
      TOKEN_ID.test(tin.assetId) && TOKEN_ID.test(tout.assetId) ? this.bestQuote(tin.assetId, tout.assetId, p.amount_in).then(r => r.best).catch(() => null) : Promise.resolve(null),
      this.intents.dryQuoteFromIntents(userId, oneclickInput).catch(() => null),
    ]);
    const relayOut = relay ? BigInt(relay.amount_out) : null, ocOut = oneclick ? BigInt(oneclick.amountOut) : null;
    const comparison = { solver_relay_out: relay?.amount_out ?? "no quote", oneclick_out: oneclick?.amountOut ?? "no quote" };
    const useRelay = relayOut !== null && (ocOut === null || relayOut * (10_000n + RELAY_PREFERENCE_BPS) >= ocOut * 10_000n);
    if (useRelay) {
      try {
        const preview = await this.prepare(userId, { token_in: tin.assetId, token_out: tout.assetId, amount_in: p.amount_in, slippage_bps: p.slippage_bps, deliver_to: p.deliver_to });
        return { ...preview, route: { chosen: "solver_relay", why: ocOut === null ? "1Click gave no quote" : `relay quote is within ${Number(RELAY_PREFERENCE_BPS) / 100}% of 1Click or better; one settlement`, expected_seconds: "~5", quotes: comparison }, confirmation: "Show route, sell, buy (quoted and minimum) and deliver_to; call intents_exchange_execute only after the user confirms this exact preview." };
      } catch (e) { if (ocOut === null) throw e; /* relay quote vanished: fall through to 1Click */ }
    }
    if (ocOut === null) throw new NearPublicError(`intents: neither the Solver Relay nor 1Click quotes ${tin.symbol} -> ${tout.symbol} for this amount right now; try a larger amount. Nothing was signed`);
    if (toWallet && storage) throw new NearPublicError(`intents: only 1Click quotes this pair, and it cannot register the wallet on ${tout.symbol}; use deliver_to intents and then intents_withdraw_prepare. Nothing was signed`);
    const preview = await this.prepareOneClick(userId, oneclickInput);
    return { ...preview, route: { chosen: "1click", why: relayOut === null ? "the Solver Relay gave no quote for this pair or size" : `1Click pays more than ${Number(RELAY_PREFERENCE_BPS) / 100}% above the relay`, expected_seconds: oneclick?.timeEstimate !== undefined ? `~${oneclick.timeEstimate + 30} (1Click estimate ${oneclick.timeEstimate} s plus deposit detection)` : "~20-60", quotes: comparison, ...(toWallet && tout.assetId === WNEAR_ID ? { note: "Through 1Click NEAR is delivered to the wallet as wNEAR." } : {}) }, confirmation: "Show route, intents.origin, intents.destination (quoted and minimum), recipient and signed_intent; call intents_exchange_execute only after the user confirms this exact preview." };
  }

  // 1Click paid from the intents balance with ONE signed transfer intent to the
  // quote's deposit address; refunds return to the intents balance. No NEAR
  // transaction, so the wallet needs no gas.
  async prepareOneClick(userId: string, input: IntentsSwapInput) {
    const account = await this.accounts.account(userId);
    const { self, plan, have, description } = await this.intents.quoteFromIntents(userId, input);
    if (self !== account.accountId) throw new Error("account mismatch");
    const intent = transferIntent(plan);
    const op = await this.preview(userId, account, { oneclick: plan }, { type: "nep413_intents", verifying_contract: INTENTS_CONTRACT, signer_id: self, intents: [intent] });
    return {
      operation_id: op.id, kind: "intents_swap", signer_id: self, intents: description, signed_intent: intent,
      intents_balance_before: have.toString(),
      network_fee: "none for this account: the relay submits and pays for the transfer; 1Click fees are inside the quote",
      expires_at: op.expiresAt.toISOString(),
      how_it_executes: `At execution the server signs ONE NEP-413 transfer intent with this NEAR account's key moving ${plan.amount_in} ${plan.origin_asset} inside intents.near to the 1Click deposit account ${plan.deposit_address} (${INTENT_LIFETIME_MS / 1000}s deadline, single-use nonce), dry-runs it and publishes it to the Solver Relay; 1Click then delivers at least the minimum or refunds to the intents balance.`,
      confirmation: "Show intents.origin, intents.destination (quoted and minimum), recipient, deposit_address and signed_intent to the user; call intents_swap_execute only after they confirm this exact preview.",
    };
  }

  // One signed message per operation: build it from the confirmed plan (trades
  // re-quote first), dry-run it on intents.near, persist, then publish.
  async execute(userId: string, id: string, purpose: string, expect?: PlanKind) {
    if (expect) {
      const peek = await this.store.operation(userId, id);
      if (peek?.kind === "intents_trade" && planKind(peek.plan as SignedPlan) !== expect) throw new NearPublicError(`intents: this operation is not an ${KIND_NAME[expect]}; use the matching execute tool. Nothing was signed`);
    }
    const op = await this.store.reserve(userId, id, "intents_trade", purpose);
    let signed = false;
    try {
      const account = await this.accounts.account(userId);
      if (account.accountId !== op.accountId || account.publicKey !== op.publicKey) throw new Error("preview no longer matches this NEAR account");
      const plan = op.plan as SignedPlan;
      if (this.fingerprint(op.accountId, op.publicKey, plan) !== op.fingerprint) throw new Error("preview binding mismatch");

      let intents: IntentJson[], quoteHashes: string[], expected: Record<string, unknown>, matched: boolean;
      let deadlineMs = this.now() + INTENT_LIFETIME_MS;
      if ("trade" in plan) {
        const t = plan.trade;
        const have = await this.intents.intentsBalanceOf(op.accountId, t.token_in);
        if (have < BigInt(t.amount_in)) throw new NearPublicError("intents: the intents balance no longer covers amount_in; nothing was signed");
        const { best } = await this.bestQuote(t.token_in, t.token_out, t.amount_in);
        if (!best) throw new NearPublicError("intents: no solver quote at execution time; nothing was signed");
        if (BigInt(best.amount_out) < BigInt(t.min_amount_out)) throw new NearPublicError(`intents: best fresh quote ${best.amount_out} is below the confirmed minimum ${t.min_amount_out}; nothing was signed`);
        deadlineMs = Math.min(deadlineMs, Date.parse(best.expiration_time) - 2_000);
        intents = [{ intent: "token_diff", diff: { [t.token_in]: `-${t.amount_in}`, [t.token_out]: best.amount_out } }];
        if (t.deliver_to === "wallet") intents.push(withdrawIntent(t.token_out, best.amount_out, op.accountId, t.storage_deposit ?? undefined));
        quoteHashes = [best.quote_hash];
        expected = { amount_out: best.amount_out, deliver_to: t.deliver_to ?? "intents" };
        matched = true;
      } else if ("oneclick" in plan) {
        const o = plan.oneclick;
        if (Date.parse(o.deadline) - ONECLICK_MARGIN_MS < this.now()) throw new NearPublicError("intents: the 1Click deposit deadline is too close; prepare a new swap. Nothing was signed");
        const have = await this.intents.intentsBalanceOf(op.accountId, o.origin_asset);
        if (have < BigInt(o.amount_in)) throw new NearPublicError("intents: the intents balance no longer covers the swap; nothing was signed");
        intents = [transferIntent(o)];
        quoteHashes = [];
        expected = { deposit_address: o.deposit_address, amount_in: o.amount_in, min_amount_out: o.min_amount_out };
        matched = false;
      } else {
        const w = plan.withdraw;
        const have = await this.intents.intentsBalanceOf(op.accountId, w.asset_id);
        if (have < BigInt(w.amount)) throw new NearPublicError("intents: the intents balance no longer covers the withdrawal; nothing was signed");
        intents = [withdrawIntent(w.asset_id, w.amount, w.receiver_id, w.storage_deposit ?? undefined)];
        quoteHashes = [];
        expected = { withdrawn: w.amount, asset_id: w.asset_id, to: w.receiver_id };
        matched = false;
      }
      if (deadlineMs < this.now() + 10_000) throw new NearPublicError("intents: the solver quote expires too soon; nothing was signed");

      const salt = await this.view(INTENTS_CONTRACT, "current_salt", {});
      const deadline = new Date(deadlineMs).toISOString();
      const nonce = versionedNonce(String(salt), deadlineMs);
      const message = intentsMessage(op.accountId, deadline, intents);
      const hash = nep413Prehash({ message, nonce, recipient: INTENTS_CONTRACT });
      const signature = await (await this.accounts.signer(account)).sign(hash);
      const signedData: SignedNep413 = { standard: "nep413", payload: { recipient: INTENTS_CONTRACT, nonce: nonce.toString("base64"), message }, public_key: op.publicKey, signature: `ed25519:${baseEncode(signature)}` };
      const intentHash = baseEncode(hash);
      // Dry run on intents.near: signature, nonce, deadline and balances must
      // pass. A trade alone only lacks the solver's half (invariant); a
      // withdrawal has no counterparty and must simulate cleanly.
      await this.simulate(signedData, matched);
      await this.store.markSigning(userId, id, nonce.toString("base64"), intentHash, JSON.stringify({ signed: signedData, quote_hashes: quoteHashes, deadline, ...expected }));
      signed = true;
      const r = await this.relay.publish(quoteHashes, signedData);
      if (r?.status !== "OK") {
        const reason = clean(String(r?.reason ?? r?.status ?? "unknown"));
        await this.store.update(userId, id, { status: "failed", error: `relay did not accept the intent: ${reason}` });
        throw new NearPublicError(`intents: the Solver Relay did not accept the signed intent (${reason}); it expires at ${deadline} and cannot execute after that`);
      }
      await this.store.update(userId, id, { status: "submitted", result: { intent_hash: intentHash, deadline, ...expected } });
      for (let i = 0; i < 8; i++) {
        const s = await this.status(userId, id);
        if (s.status !== "submitted") return s;
        await new Promise(res => setTimeout(res, 1_500));
      }
      return this.status(userId, id);
    } catch (e) {
      if (!signed) { await this.store.update(userId, id, { status: "failed", error: e instanceof NearPublicError ? e.message : "stopped before signing" }); throw e; }
      if (e instanceof NearPublicError) throw e;
      await this.store.update(userId, id, { status: "unknown", error: "publish result unknown" });
      return { operation_id: id, status: "unknown", message: "The signed intent may or may not have reached the relay. It expires within a minute; call intents_status to reconcile. Do not prepare it again before that." };
    }
  }

  private async simulate(signed: SignedNep413, matched: boolean) {
    let m = "";
    try {
      const r = await this.rpc.call<{ result?: number[]; error?: string }>("query", { request_type: "call_function", finality: "final", account_id: INTENTS_CONTRACT, method_name: "simulate_intents", args_base64: Buffer.from(JSON.stringify({ signed: [signed] })).toString("base64") });
      if (typeof r.error === "string") m = r.error;
      else if (Array.isArray(r.result)) return;
    } catch (e) { m = e instanceof NearRpcError ? `${e.message} ${JSON.stringify(e.data ?? "")}` : "rpc failure"; }
    if (matched && /invariant/i.test(m)) return;
    throw new NearPublicError(`intents: intents.near rejected the signed intent in simulation${m ? ` (${clean(m, 200)})` : ""}; nothing was published`);
  }

  async status(userId: string, id: string): Promise<Record<string, unknown> & { status: string }> {
    const op = await this.store.operation(userId, id);
    if (!op || op.kind !== "intents_trade") throw new NearPublicError("operation not found for this user, or not an intents trade");
    const plan = op.plan as SignedPlan;
    const base = { operation_id: id, kind: KIND_NAME[planKind(plan)], intent_hash: op.txHash };
    // A funded 1Click swap continues off this account: report 1Click's status.
    const swap = async () => "oneclick" in plan ? { oneclick: await this.intents.oneClickStatus(plan.oneclick).catch(() => ({ swap_status: "UNAVAILABLE" })) } : {};
    if (!op.txHash || !["signing", "submitted", "unknown"].includes(op.status)) return { ...base, status: op.status, result: op.result, error: op.error, ...(op.status === "confirmed" ? await swap() : {}) };
    const { signed: _s, quote_hashes: _q, deadline, ...expected } = JSON.parse(op.signedTx ?? "{}") as Record<string, unknown> & { deadline?: string };
    let relay: Awaited<ReturnType<SolverRelayClient["status"]>> | null = null;
    try { relay = await this.relay.status(op.txHash); } catch { /* fall back to chain */ }
    if (relay?.status === "SETTLED") {
      const result = { intent_hash: op.txHash, settlement_tx: relay.data?.hash ?? null, ...expected, ...(relay.filled_amounts ? { filled_amounts: relay.filled_amounts } : {}) };
      await this.store.update(userId, id, { status: "confirmed", result });
      // Like the official app: tell 1Click the settlement hash, best effort
      // (it also detects the transfer on its own).
      if ("oneclick" in plan && relay.data?.hash) await this.intents.submitDeposit(relay.data.hash, plan.oneclick.deposit_address, op.accountId).catch(() => undefined);
      return { ...base, status: "confirmed", ...result, ...(relay.data?.hash ? { explorer_url: `https://nearblocks.io/txns/${relay.data.hash}` } : {}), ...(await swap()) };
    }
    if (deadline && Date.parse(deadline) + 10_000 < this.now()) {
      const used = await this.view(INTENTS_CONTRACT, "is_nonce_used", { account_id: op.accountId, nonce: op.nonce });
      if (used === false) {
        await this.store.update(userId, id, { status: "failed", error: "intent expired without settlement; nothing moved" });
        return { ...base, status: "failed", message: "The intent expired without settlement; the intents balance is unchanged." };
      }
      if (used === true) {
        await this.store.update(userId, id, { status: "confirmed", result: { intent_hash: op.txHash, ...expected, note: "nonce consumed on intents.near" } });
        return { ...base, status: "confirmed", ...expected, ...(await swap()) };
      }
    }
    return { ...base, status: "submitted", relay_status: relay?.status ?? "unavailable", deadline, message: "Waiting for settlement; check again shortly." };
  }
}

export function canonicalJson(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonicalJson).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonicalJson((v as Record<string, unknown>)[k])}`).join(",")}}`;
  return JSON.stringify(v) ?? "null";
}

export function formatUnits(v: bigint, decimals: number): string {
  const s = v.toString().padStart(decimals + 1, "0");
  const whole = s.slice(0, s.length - decimals), frac = s.slice(s.length - decimals).replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}
