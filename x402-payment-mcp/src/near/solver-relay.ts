import { createHash, randomBytes } from "node:crypto";
import { baseEncode } from "@near-js/utils";
import { z } from "zod";
import type { NearAccountService } from "./account.js";
import { INTENTS_CONTRACT, type NearIntents } from "./intents.js";
import { NearPublicError } from "./operations.js";
import { NearRpcError } from "./rpc.js";
import type { NearStore } from "./store.js";

// Swaps inside the NEAR Intents balance through the Solver Relay, without
// 1Click: solvers quote, the NEAR account signs one NEP-413 token_diff intent
// with its own key, and the relay settles it on intents.near in one NEAR
// transaction it pays for. No deposit address, storage deposit or NEAR gas.
export const SOLVER_RELAY_URL = "https://solver-relay-v2.chaindefuser.com/rpc";
const NEP413_TAG = 2147484061; // 2^31 + 413
const VERSIONED_NONCE_PREFIX = Buffer.from("5628f6c6", "hex");
const QUOTE_WINDOW_MS = 60_000;
const INTENT_LIFETIME_MS = 45_000;
const UINT = /^\d{1,78}$/;
const TOKEN_ID = /^nep(141|245):[a-z0-9._:-]{2,200}$/i;

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
export function tokenDiffMessage(signerId: string, deadline: string, diff: Record<string, string>): string {
  return JSON.stringify({ signer_id: signerId, deadline, intents: [{ intent: "token_diff", diff }] });
}

// ---- Relay client ----
export type RelayQuote = { quote_hash: string; amount_in: string; amount_out: string; expiration_time: string; defuse_asset_identifier_in: string; defuse_asset_identifier_out: string };
export class SolverRelayClient {
  constructor(private url = SOLVER_RELAY_URL, private fetcher: typeof fetch = globalThis.fetch, private apiKey?: string) {}
  private async rpc<T>(method: string, params: unknown): Promise<T> {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (this.apiKey) headers["x-api-key"] = this.apiKey;
    let res: Response;
    try { res = await this.fetcher(this.url, { method: "POST", headers, body: JSON.stringify({ id: 1, jsonrpc: "2.0", method, params: [params] }), signal: AbortSignal.timeout(15_000) }); }
    catch { throw new SolverRelayUnreachable(); }
    const body = await res.json().catch(() => null) as { result?: T; error?: { message?: string } } | null;
    if (!res.ok || !body || body.error) throw new NearPublicError(`intents: the Solver Relay refused ${method} (${String(body?.error?.message ?? `HTTP ${res.status}`).replace(/[^\x20-\x7e]/g, "").slice(0, 160)})`);
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
  publish(quoteHash: string, signed: SignedNep413) { return this.rpc<{ status: string; intent_hash?: string; reason?: string }>("publish_intent", { quote_hashes: [quoteHash], signed_data: signed }); }
  status(intentHash: string) { return this.rpc<{ status: string; status_details?: string; data?: { hash?: string }; filled_amounts?: string[] }>("get_status", { intent_hash: intentHash }); }
}
export class SolverRelayUnreachable extends Error { constructor() { super("Solver Relay unreachable"); } }
export type SignedNep413 = { standard: "nep413"; payload: { recipient: string; nonce: string; message: string }; public_key: string; signature: string };

export const intentsTradeInput = z.strictObject({
  token_in: z.string().min(2).max(200).describe("Asset to sell from the intents balance: 1Click assetId (e.g. nep141:wrap.near), \"NEAR\" for wNEAR, or SYMBOL@chain such as USDC@near, SOL@sol"),
  token_out: z.string().min(2).max(200).describe("Asset to receive into the intents balance, same formats"),
  amount_in: z.string().regex(/^[1-9]\d{0,77}$/).describe("Exact amount to sell, in token_in's smallest unit"),
  slippage_bps: z.number().int().min(1).max(500).default(50).describe("At execution the best fresh quote must give at least the previewed quote minus this many bps, otherwise nothing is signed"),
});
export type IntentsTradePlan = { token_in: string; token_out: string; amount_in: string; quoted_out: string; min_amount_out: string };

export class IntentsTrades {
  constructor(private accounts: NearAccountService, private store: NearStore, private intents: NearIntents, private relay = new SolverRelayClient(), private now: () => number = Date.now) {}
  private get rpc() { return this.accounts.rpc; }
  private async view(method: string, args: unknown) { return (await this.rpc.callFunction(INTENTS_CONTRACT, method, args)).result; }

  private async bestQuote(tokenIn: string, tokenOut: string, amountIn: string) {
    const quotes = await this.relay.quote(tokenIn, tokenOut, amountIn);
    const live = quotes.filter(q => Date.parse(q.expiration_time) > this.now() + 5_000);
    return { count: live.length, best: live.reduce<RelayQuote | null>((b, q) => !b || BigInt(q.amount_out) > BigInt(b.amount_out) ? q : b, null) };
  }

  async prepare(userId: string, input: z.input<typeof intentsTradeInput>) {
    const p = intentsTradeInput.parse(input);
    const account = await this.accounts.account(userId);
    const [tin, tout] = await Promise.all([this.intents.asset(p.token_in, "token_in"), this.intents.asset(p.token_out, "token_out")]);
    if (!TOKEN_ID.test(tin.assetId) || !TOKEN_ID.test(tout.assetId)) throw new NearPublicError("intents: both tokens must be NEP-141/NEP-245 assets held on intents.near; nothing was signed");
    if (tin.assetId === tout.assetId) throw new NearPublicError("intents: token_in and token_out are the same; nothing was signed");
    const have = await this.intents.intentsBalanceOf(account.accountId, tin.assetId);
    if (have < BigInt(p.amount_in)) throw new NearPublicError(`intents: the intents balance holds ${have} of ${tin.symbol} (smallest units), needs ${p.amount_in}; see intents_balances. Nothing was signed`);
    const { count, best } = await this.bestQuote(tin.assetId, tout.assetId, p.amount_in);
    if (!best) throw new NearPublicError(`intents: no solver quotes ${tin.symbol} -> ${tout.symbol} for this amount right now (small sizes and illiquid pairs often get none; try a larger amount or route via USDC). Nothing was signed`);
    const minOut = BigInt(best.amount_out) * BigInt(10_000 - p.slippage_bps) / 10_000n;
    const plan: IntentsTradePlan = { token_in: tin.assetId, token_out: tout.assetId, amount_in: p.amount_in, quoted_out: best.amount_out, min_amount_out: minOut.toString() };
    const fingerprint = createHash("sha256").update(JSON.stringify(["intents-trade:v1", account.accountId, account.publicKey, plan])).digest("hex");
    const description = { type: "nep413_token_diff", verifying_contract: INTENTS_CONTRACT, signer_id: account.accountId, sell: { asset_id: tin.assetId, amount: p.amount_in }, buy_at_least: { asset_id: tout.assetId, amount: minOut.toString() } };
    const op = await this.store.createOperation({ userId, network: this.accounts.config.network, accountId: account.accountId, publicKey: account.publicKey, kind: "intents_trade", receiverId: INTENTS_CONTRACT, actions: [], descriptions: [description], plan: { trade: plan }, fingerprint }, this.accounts.config.previewTtlSeconds);
    const fmt = (v: string, d: number) => formatUnits(BigInt(v), d);
    return {
      operation_id: op.id, kind: "intents_trade", signer_id: account.accountId, verifying_contract: INTENTS_CONTRACT,
      sell: { asset_id: tin.assetId, symbol: tin.symbol, amount: p.amount_in, formatted: fmt(p.amount_in, tin.decimals) },
      buy: { asset_id: tout.assetId, symbol: tout.symbol, quoted: best.amount_out, quoted_formatted: fmt(best.amount_out, tout.decimals), minimum: minOut.toString(), minimum_formatted: fmt(minOut.toString(), tout.decimals) },
      solver_quotes: count, slippage_bps: p.slippage_bps, intents_balance_before: { [tin.symbol]: fmt(have.toString(), tin.decimals) },
      network_fee: "none for this account: the relay submits and pays for the settlement transaction",
      expires_at: op.expiresAt.toISOString(),
      how_it_executes: `At execution the server takes a fresh solver quote, refuses if it is below the minimum, and signs ONE NEP-413 token_diff message with this NEAR account's key (-${p.amount_in} ${tin.assetId}, +quoted ${tout.assetId}, ${INTENT_LIFETIME_MS / 1000}s deadline, single-use nonce). intents.near settles it atomically or not at all; funds never leave the intents balance otherwise.`,
      confirmation: "Show sell, buy (quoted and minimum) and the signed-message description to the user; call intents_trade_execute only after they confirm this exact preview.",
    };
  }

  async execute(userId: string, id: string, purpose: string) {
    const op = await this.store.reserve(userId, id, "intents_trade", purpose);
    let signed = false;
    try {
      const account = await this.accounts.account(userId);
      if (account.accountId !== op.accountId || account.publicKey !== op.publicKey) throw new Error("preview no longer matches this NEAR account");
      const plan = (op.plan as { trade: IntentsTradePlan }).trade;
      if (createHash("sha256").update(JSON.stringify(["intents-trade:v1", op.accountId, op.publicKey, plan])).digest("hex") !== op.fingerprint) throw new Error("preview binding mismatch");
      const have = await this.intents.intentsBalanceOf(op.accountId, plan.token_in);
      if (have < BigInt(plan.amount_in)) throw new NearPublicError("intents: the intents balance no longer covers amount_in; nothing was signed");
      const { best } = await this.bestQuote(plan.token_in, plan.token_out, plan.amount_in);
      if (!best) throw new NearPublicError("intents: no solver quote at execution time; nothing was signed");
      if (BigInt(best.amount_out) < BigInt(plan.min_amount_out)) throw new NearPublicError(`intents: best fresh quote ${best.amount_out} is below the confirmed minimum ${plan.min_amount_out}; nothing was signed`);

      const salt = await this.view("current_salt", {});
      const deadlineMs = Math.min(this.now() + INTENT_LIFETIME_MS, Date.parse(best.expiration_time) - 2_000);
      if (deadlineMs < this.now() + 10_000) throw new NearPublicError("intents: the solver quote expires too soon; nothing was signed");
      const deadline = new Date(deadlineMs).toISOString();
      const nonce = versionedNonce(String(salt), deadlineMs);
      const message = tokenDiffMessage(op.accountId, deadline, { [plan.token_in]: `-${plan.amount_in}`, [plan.token_out]: best.amount_out });
      const payload = { message, nonce, recipient: INTENTS_CONTRACT };
      const hash = nep413Prehash(payload);
      const signer = await this.accounts.signer(account);
      const signature = await signer.sign(hash);
      const signedData: SignedNep413 = { standard: "nep413", payload: { recipient: INTENTS_CONTRACT, nonce: nonce.toString("base64"), message }, public_key: op.publicKey, signature: `ed25519:${baseEncode(signature)}` };
      const intentHash = baseEncode(hash);
      // Dry run on intents.near: signature, nonce, deadline and balance must
      // pass; only the counterparty half (the solver's intent) is missing.
      await this.simulate(signedData);
      await this.store.markSigning(userId, id, nonce.toString("base64"), intentHash, JSON.stringify({ signed: signedData, quote_hash: best.quote_hash, deadline, amount_out: best.amount_out }));
      signed = true;
      const r = await this.relay.publish(best.quote_hash, signedData);
      if (r?.status !== "OK") {
        await this.store.update(userId, id, { status: "failed", error: `relay did not accept the intent: ${String(r?.reason ?? r?.status ?? "unknown").replace(/[^\x20-\x7e]/g, "").slice(0, 160)}` });
        throw new NearPublicError(`intents: the Solver Relay did not accept the signed intent (${String(r?.reason ?? r?.status).replace(/[^\x20-\x7e]/g, "").slice(0, 160)}); it expires at ${deadline} and cannot execute after that`);
      }
      await this.store.update(userId, id, { status: "submitted", result: { intent_hash: intentHash, quote_hash: best.quote_hash, amount_out: best.amount_out, deadline } });
      for (let i = 0; i < 6; i++) {
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

  private async simulate(signed: SignedNep413) {
    let m = "";
    try {
      const r = await this.rpc.call<{ result?: number[]; error?: string }>("query", { request_type: "call_function", finality: "final", account_id: INTENTS_CONTRACT, method_name: "simulate_intents", args_base64: Buffer.from(JSON.stringify({ signed: [signed] })).toString("base64") });
      if (typeof r.error === "string") m = r.error;
      else if (Array.isArray(r.result)) return;
    } catch (e) { m = e instanceof NearRpcError ? `${e.message} ${JSON.stringify(e.data ?? "")}` : "rpc failure"; }
    {
      // An unmatched token_diff only violates the invariant; anything else
      // (signature, nonce, deadline, balance) stops before publishing.
      if (/invariant/i.test(m)) return;
      throw new NearPublicError(`intents: intents.near rejected the signed intent in simulation${m ? ` (${m.replace(/[^\x20-\x7e]/g, "").slice(0, 200)})` : ""}; nothing was published`);
    }
  }

  async status(userId: string, id: string): Promise<Record<string, unknown> & { status: string }> {
    const op = await this.store.operation(userId, id);
    if (!op || op.kind !== "intents_trade") throw new NearPublicError("operation not found for this user, or not an intents trade");
    const base = { operation_id: id, kind: "intents_trade", intent_hash: op.txHash };
    if (!op.txHash || !["signing", "submitted", "unknown"].includes(op.status)) return { ...base, status: op.status, result: op.result, error: op.error };
    const saved = JSON.parse(op.signedTx ?? "{}") as { deadline?: string; amount_out?: string };
    let relay: Awaited<ReturnType<SolverRelayClient["status"]>> | null = null;
    try { relay = await this.relay.status(op.txHash); } catch { /* fall back to chain */ }
    if (relay?.status === "SETTLED") {
      const result = { intent_hash: op.txHash, settlement_tx: relay.data?.hash ?? null, amount_out: saved.amount_out, filled_amounts: relay.filled_amounts ?? null };
      await this.store.update(userId, id, { status: "confirmed", result });
      return { ...base, status: "confirmed", ...result, ...(relay.data?.hash ? { explorer_url: `https://nearblocks.io/txns/${relay.data.hash}` } : {}) };
    }
    const expired = saved.deadline && Date.parse(saved.deadline) + 10_000 < this.now();
    if (expired) {
      const used = await this.view("is_nonce_used", { account_id: op.accountId, nonce: op.nonce });
      if (used === false) {
        await this.store.update(userId, id, { status: "failed", error: "intent expired without settlement; nothing moved" });
        return { ...base, status: "failed", message: "The intent expired without settlement; the intents balance is unchanged." };
      }
      if (used === true) {
        await this.store.update(userId, id, { status: "confirmed", result: { intent_hash: op.txHash, amount_out: saved.amount_out, note: "nonce consumed on intents.near" } });
        return { ...base, status: "confirmed", amount_out: saved.amount_out };
      }
    }
    return { ...base, status: "submitted", relay_status: relay?.status ?? "unavailable", deadline: saved.deadline, message: "Waiting for settlement; check again shortly." };
  }
}

function formatUnits(v: bigint, decimals: number): string {
  const s = v.toString().padStart(decimals + 1, "0");
  const whole = s.slice(0, s.length - decimals), frac = s.slice(s.length - decimals).replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole;
}
