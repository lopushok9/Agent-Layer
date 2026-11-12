import { z } from "zod";
import type { NearAccountService } from "./account.js";
import { NearPublicError } from "./operations.js";
import { call, ftTransferCall, needsStorage, ONE_YOCTO, storageDeposit, type NearPlans, type PlanAction, type PlanCheck } from "./plan.js";
import { formatNear } from "./units.js";

// Rhea (Ref) classic pools on v2.ref-finance.near: SIMPLE_POOL, STABLE_SWAP,
// RATED_SWAP and DEGEN_SWAP. Knowledge fixed here (from the audited
// ref-exchange source) so the agent does not rediscover it:
// - liquidity is added from the account's internal Ref balance, so tokens are
//   first deposited with ft_transfer_call(msg "") to the exchange;
// - account storage: 102 bytes + 148 bytes per registered token (1e19 yocto/byte);
//   register_tokens (1 yocto) also lets non-whitelisted tokens be deposited;
// - simple pools: add_liquidity(amounts, min_amounts), amounts are rebalanced to
//   the pool ratio (predict_add_simple_liquidity gives need_amounts);
//   other kinds: add_stable_liquidity(amounts, min_shares) with
//   predict_add_{stable,rated,degen}_liquidity; adding attaches NEAR for the LP
//   share storage, the excess is refunded;
// - exit: remove_liquidity(shares, min_amounts) then withdraw(token, 0 = all)
//   per token in the same transaction; wNEAR is unwrapped to native NEAR.
// Concentrated (DCL) pools live on dclv2.ref-labs.near and are not handled.
export const RHEA_EXCHANGE = "v2.ref-finance.near";
const WNEAR = "wrap.near";
const BYTE = 10n ** 19n, ACCOUNT_BYTES = 102n, TOKEN_BYTES = 148n;
const ADD_STORAGE = 5n * 10n ** 21n; // 0.005 NEAR for the LP share record, excess refunded
const KINDS = new Set(["SIMPLE_POOL", "STABLE_SWAP", "RATED_SWAP", "DEGEN_SWAP"]);
const PREDICT: Record<string, string> = { STABLE_SWAP: "predict_add_stable_liquidity", RATED_SWAP: "predict_add_rated_liquidity", DEGEN_SWAP: "predict_add_degen_liquidity" };
const DEC = /^\d{1,30}(\.\d{1,36})?$/;

export const rheaLpInput = z.strictObject({
  pool_id: z.number().int().min(0).max(100_000_000).describe("Rhea pool id (pool_id from yield_search, contract v2.ref-finance.near)"),
  amounts: z.record(z.string().min(1).max(64), z.string().min(1).max(70)).describe('Per pool token: key = token symbol (NEAR/wNEAR mean wrap.near) or contract id; value = human amount like "0.01", or "auto" for the amount matching the pool ratio (exactly one token must be fixed). Missing tokens add 0 (not allowed for simple pools)'),
  slippage_bps: z.number().int().min(1).max(500).default(100),
});
export const rheaLpExitInput = z.strictObject({
  pool_id: z.number().int().min(0).max(100_000_000),
  shares: z.string().regex(/^\d{1,40}$/).optional().describe("LP shares to remove; default all"),
  slippage_bps: z.number().int().min(1).max(500).default(100),
});

type Token = { id: string; symbol: string; decimals: number };

export class RheaPools {
  constructor(private accounts: NearAccountService, private plans: NearPlans) {}
  private get rpc() { return this.accounts.rpc; }
  private async view<T = any>(contract: string, method: string, args: unknown): Promise<T> { return (await this.rpc.callFunction(contract, method, args)).result as T; }

  private async pool(poolId: number) {
    const p = await this.view(RHEA_EXCHANGE, "get_pool", { pool_id: poolId }).catch(() => null);
    if (!p || !Array.isArray(p.token_account_ids)) throw new NearPublicError(`Rhea pool ${poolId} not found on ${RHEA_EXCHANGE}; nothing was signed`);
    if (!KINDS.has(p.pool_kind)) throw new NearPublicError(`Rhea pool ${poolId} is ${String(p.pool_kind).slice(0, 20)}; only simple, stable, rated and degen pools are supported. Nothing was signed`);
    const ids: string[] = p.token_account_ids;
    const tokens: Token[] = await Promise.all(ids.map(async id => {
      const m = await this.view(id, "ft_metadata", {}).catch(() => null);
      if (!m || !Number.isInteger(m.decimals) || m.decimals < 0 || m.decimals > 36) throw new NearPublicError(`token ${id} has no valid ft_metadata; nothing was signed`);
      return { id, symbol: String(m.symbol ?? id).replace(/[^\x20-\x7e]/g, "?").slice(0, 20), decimals: m.decimals };
    }));
    const reserves = (p.amounts as string[]).map(a => BigInt(a));
    return { kind: p.pool_kind as string, tokens, reserves };
  }

  async prepareAdd(userId: string, input: z.input<typeof rheaLpInput>) {
    const p = rheaLpInput.parse(input);
    const self = (await this.accounts.account(userId)).accountId;
    const pool = await this.pool(p.pool_id);
    const { kind, tokens, reserves } = pool;

    // amounts in pool token order
    const index = (key: string) => {
      const k = key.trim(), u = k.toUpperCase();
      const i = tokens.findIndex(t => t.id === k || t.symbol.toUpperCase() === u || ((u === "NEAR" || u === "WNEAR") && t.id === WNEAR));
      if (i < 0) throw new NearPublicError(`"${key.slice(0, 40)}" is not a token of pool ${p.pool_id} (${tokens.map(t => `${t.symbol} ${t.id}`).join(", ")}); nothing was signed`);
      return i;
    };
    const fixed = new Map<number, bigint>(), auto = new Set<number>();
    for (const [k, v] of Object.entries(p.amounts)) {
      const i = index(k);
      if (fixed.has(i) || auto.has(i)) throw new NearPublicError(`token ${tokens[i]!.symbol} is given twice; nothing was signed`);
      if (v.trim().toLowerCase() === "auto") auto.add(i);
      else if (DEC.test(v.trim())) fixed.set(i, parseUnits(v.trim(), tokens[i]!.decimals));
      else throw new NearPublicError(`amount for ${tokens[i]!.symbol} must be a decimal like "0.01" or "auto"; nothing was signed`);
    }
    if (auto.size && fixed.size !== 1) throw new NearPublicError('"auto" needs exactly one token with a fixed amount; nothing was signed');
    let amounts = tokens.map((_, i) => fixed.get(i) ?? 0n);
    if (auto.size) {
      const [base, amt] = [...fixed][0]!;
      if (reserves[base] === 0n) throw new NearPublicError("pool is empty; cannot match its ratio. Nothing was signed");
      for (const i of auto) amounts[i] = amt * reserves[i]! / reserves[base]!;
    }
    if (amounts.every(a => a === 0n)) throw new NearPublicError("nothing to add; nothing was signed");
    if (kind === "SIMPLE_POOL" && amounts.some(a => a === 0n)) throw new NearPublicError('simple pools need every token; give each amount or use "auto". Nothing was signed');

    // prediction (simple pools also rebalance the amounts)
    let minShares: bigint, predictCheck: PlanCheck, predicted: bigint, finalCall: PlanAction;
    const amountArgs = () => amounts.map(a => a.toString());
    if (kind === "SIMPLE_POOL") {
      const r = await this.view(RHEA_EXCHANGE, "predict_add_simple_liquidity", { pool_id: p.pool_id, amounts: amountArgs() });
      const need = (r?.need_amounts ?? []).map((x: string) => BigInt(x));
      predicted = BigInt(r?.mint_shares ?? "0");
      if (need.length !== tokens.length) throw new NearPublicError("unexpected prediction from Rhea; nothing was signed");
      amounts = need;
      minShares = predicted * BigInt(10_000 - p.slippage_bps) / 10_000n;
      const minAmounts = amounts.map(a => (a * BigInt(10_000 - p.slippage_bps) / 10_000n).toString());
      finalCall = call("add_liquidity", { pool_id: p.pool_id, amounts: amountArgs(), min_amounts: minAmounts }, ADD_STORAGE.toString(), 30);
      predictCheck = { label: `predicted LP shares still >= ${minShares}`, contract_id: RHEA_EXCHANGE, method_name: "predict_add_simple_liquidity", args: { pool_id: p.pool_id, amounts: amountArgs() }, path: ["mint_shares"], op: "gte", value: minShares.toString() };
    } else {
      const method = PREDICT[kind]!;
      const args: Record<string, unknown> = { pool_id: p.pool_id, amounts: amountArgs(), ...(kind === "RATED_SWAP" ? { rates: null } : kind === "DEGEN_SWAP" ? { degens: null } : {}) };
      predicted = BigInt(await this.view<string>(RHEA_EXCHANGE, method, args));
      minShares = predicted * BigInt(10_000 - p.slippage_bps) / 10_000n;
      finalCall = call("add_stable_liquidity", { pool_id: p.pool_id, amounts: amountArgs(), min_shares: minShares.toString() }, ADD_STORAGE.toString(), 30);
      predictCheck = { label: `predicted LP shares still >= ${minShares}`, contract_id: RHEA_EXCHANGE, method_name: method, args, path: [], op: "gte", value: minShares.toString() };
    }
    if (predicted <= 0n) throw new NearPublicError("the pool predicts 0 LP shares for these amounts; nothing was signed");

    // account state: Ref storage/deposits, wallet balances, wrap.near registration
    const [storage, deposits, wallet, wrapStorage, shares] = await Promise.all([
      this.view(RHEA_EXCHANGE, "get_user_storage_state", { account_id: self }),
      this.view<Record<string, string>>(RHEA_EXCHANGE, "get_deposits", { account_id: self }).catch(() => ({} as Record<string, string>)),
      Promise.all(tokens.map(t => this.view<string>(t.id, "ft_balance_of", { account_id: self }).then(v => BigInt(v ?? "0")).catch(() => 0n))),
      tokens.some(t => t.id === WNEAR) ? needsStorage(this.rpc, WNEAR, self) : Promise.resolve(null),
      this.view<string>(RHEA_EXCHANGE, "get_pool_shares", { pool_id: p.pool_id, account_id: self }).catch(() => "0"),
    ]);
    const have = (id: string) => BigInt(deposits?.[id] ?? "0");
    const newTokens = tokens.filter(t => amounts[tokens.indexOf(t)]! > 0n && deposits?.[t.id] === undefined).map(t => t.id);
    let storageNeed = 0n;
    if (!storage) storageNeed = (ACCOUNT_BYTES + TOKEN_BYTES * BigInt(newTokens.length)) * BYTE;
    else {
      const after = BigInt(storage.usage) + TOKEN_BYTES * BigInt(newTokens.length) * BYTE;
      if (after > BigInt(storage.deposit)) storageNeed = after - BigInt(storage.deposit);
    }

    const steps: { title: string; transaction: { receiver_id: string; actions: PlanAction[] }; checks: PlanCheck[] }[] = [];
    if (storageNeed > 0n || newTokens.length) {
      const actions: PlanAction[] = [];
      if (storageNeed > 0n) actions.push(storageDeposit(self, storageNeed, false));
      if (newTokens.length) actions.push(call("register_tokens", { token_ids: newTokens }, ONE_YOCTO, 10));
      steps.push({ title: storage ? "Top up Rhea storage and register tokens" : "Register on Rhea (storage for account and tokens)", transaction: { receiver_id: RHEA_EXCHANGE, actions }, checks: [] });
    }
    const moves: Record<string, unknown>[] = [];
    tokens.forEach((t, i) => {
      const need = amounts[i]! - have(t.id);
      if (need <= 0n) return;
      const actions: PlanAction[] = [];
      let wrap = 0n;
      if (t.id === WNEAR && wallet[i]! < need) {
        wrap = need - wallet[i]!;
        if (wrapStorage) actions.push(storageDeposit(self, wrapStorage));
        actions.push(call("near_deposit", {}, wrap.toString(), 8));
      } else if (wallet[i]! < need) {
        throw new NearPublicError(`not enough ${t.symbol} in the wallet: need ${formatUnits(need, t.decimals)}, have ${formatUnits(wallet[i]!, t.decimals)}; nothing was signed`);
      }
      actions.push(ftTransferCall(RHEA_EXCHANGE, need));
      steps.push({ title: `${wrap ? `Wrap ${formatNear(wrap)} NEAR and deposit` : "Deposit"} ${formatUnits(need, t.decimals)} ${t.symbol} into Rhea`, transaction: { receiver_id: t.id, actions }, checks: [] });
      moves.push({ token: t.symbol, from_wallet: formatUnits(need, t.decimals), ...(wrap ? { wrapped_from_native_near: formatNear(wrap) } : {}) });
    });
    steps.push({
      title: `Add liquidity to Rhea pool ${p.pool_id}`,
      transaction: { receiver_id: RHEA_EXCHANGE, actions: [finalCall] },
      checks: [
        ...tokens.flatMap((t, i) => amounts[i]! > 0n ? [{ label: `Rhea balance of ${t.symbol} >= ${formatUnits(amounts[i]!, t.decimals)}`, contract_id: RHEA_EXCHANGE, method_name: "get_deposits", args: { account_id: self }, path: [t.id], op: "gte" as const, value: amounts[i]!.toString() }] : []),
        predictCheck,
      ],
    });

    return this.plans.prepare(userId, { title: `Add liquidity to Rhea pool ${p.pool_id} (${tokens.map(t => t.symbol).join("/")})`, steps }, {
      pool: { pool_id: p.pool_id, contract: RHEA_EXCHANGE, kind, tokens: tokens.map(t => ({ symbol: t.symbol, token_id: t.id, decimals: t.decimals })) },
      add: tokens.map((t, i) => ({ token: t.symbol, amount: formatUnits(amounts[i]!, t.decimals) })),
      moves_from_wallet: moves,
      predicted_shares: predicted.toString(), min_shares: minShares.toString(), slippage_bps: p.slippage_bps,
      ...(BigInt(shares || "0") > 0n ? { existing_shares: shares } : {}),
      ...(storageNeed > 0n ? { rhea_storage_deposit_near: formatNear(storageNeed) } : {}),
      notes: [
        "Steps run in order; tokens deposited into Rhea stay on the account's Rhea balance if a later step stops, and rhea_lp_exit_prepare or a new rhea_lp_prepare continues from there.",
        `Up to ${formatNear(ADD_STORAGE)} NEAR is attached to the add call for the LP share storage; the unused part is refunded. Rhea storage deposits are refundable with storage_withdraw.`,
        ...(kind === "SIMPLE_POOL" ? ["Simple pools take amounts in the pool ratio (shown in add); anything left over stays on the Rhea balance."] : ["Amounts away from the pool ratio pay a small imbalance fee in shares; \"auto\" avoids it."]),
      ],
    });
  }

  async prepareExit(userId: string, input: z.input<typeof rheaLpExitInput>) {
    const p = rheaLpExitInput.parse(input);
    const self = (await this.accounts.account(userId)).accountId;
    const pool = await this.pool(p.pool_id);
    const owned = BigInt(await this.view<string>(RHEA_EXCHANGE, "get_pool_shares", { pool_id: p.pool_id, account_id: self }).catch(() => "0"));
    const shares = p.shares ? BigInt(p.shares) : owned;
    if (owned === 0n) throw new NearPublicError(`this account has no shares in Rhea pool ${p.pool_id}; nothing was signed`);
    if (shares <= 0n || shares > owned) throw new NearPublicError(`shares must be between 1 and ${owned}; nothing was signed`);
    const out = (await this.view<string[]>(RHEA_EXCHANGE, "predict_remove_liquidity", { pool_id: p.pool_id, shares: shares.toString() })).map(x => BigInt(x));
    const min = out.map(a => a * BigInt(10_000 - p.slippage_bps) / 10_000n);
    const deposits = await this.view<Record<string, string>>(RHEA_EXCHANGE, "get_deposits", { account_id: self }).catch(() => ({} as Record<string, string>));
    // The wallet must be registered on each token it receives (wNEAR arrives as native NEAR).
    const regs = await Promise.all(pool.tokens.map(t => t.id === WNEAR ? Promise.resolve(null) : needsStorage(this.rpc, t.id, self)));
    const steps: { title: string; transaction: { receiver_id: string; actions: PlanAction[] }; checks: PlanCheck[] }[] = [];
    pool.tokens.forEach((t, i) => { if (regs[i]) steps.push({ title: `Register the wallet on ${t.symbol}`, transaction: { receiver_id: t.id, actions: [storageDeposit(self, regs[i]!)] }, checks: [] }); });
    const withdraws = pool.tokens.flatMap((t, i) => out[i]! + BigInt(deposits?.[t.id] ?? "0") > 0n ? [call("withdraw", { token_id: t.id, amount: "0", unregister: false, skip_unwrap_near: false }, ONE_YOCTO, 60)] : []);
    steps.push({
      title: `Remove liquidity from Rhea pool ${p.pool_id} and withdraw to the wallet`,
      transaction: { receiver_id: RHEA_EXCHANGE, actions: [call("remove_liquidity", { pool_id: p.pool_id, shares: shares.toString(), min_amounts: min.map(String) }, ONE_YOCTO, 30), ...withdraws] },
      checks: [{ label: `account still holds >= ${shares} shares`, contract_id: RHEA_EXCHANGE, method_name: "get_pool_shares", args: { pool_id: p.pool_id, account_id: self }, path: [], op: "gte", value: shares.toString() }],
    });
    return this.plans.prepare(userId, { title: `Exit Rhea pool ${p.pool_id} (${pool.tokens.map(t => t.symbol).join("/")})`, steps }, {
      pool: { pool_id: p.pool_id, contract: RHEA_EXCHANGE, kind: pool.kind },
      shares: shares.toString(), shares_owned: owned.toString(),
      receive: pool.tokens.map((t, i) => ({ token: t.id === WNEAR ? "NEAR (unwrapped)" : t.symbol, expected: formatUnits(out[i]!, t.decimals), minimum: formatUnits(min[i]!, t.decimals), ...(BigInt(deposits?.[t.id] ?? "0") > 0n ? { plus_existing_rhea_balance: formatUnits(BigInt(deposits[t.id]!), t.decimals) } : {}) })),
      slippage_bps: p.slippage_bps,
      notes: ["remove_liquidity and the withdrawals run in ONE transaction: withdraw amount 0 sends the whole Rhea balance of each token to the wallet. If a token transfer fails, Rhea credits it back to the Rhea balance."],
    });
  }
}

export function parseUnits(v: string, decimals: number): bigint {
  const [w, f = ""] = v.split(".");
  if (f.length > decimals) throw new NearPublicError(`too many decimals (max ${decimals}); nothing was signed`);
  return BigInt(w!) * 10n ** BigInt(decimals) + BigInt((f + "0".repeat(decimals)).slice(0, decimals) || "0");
}
export function formatUnits(v: bigint, decimals: number): string {
  if (decimals === 0) return v.toString();
  const s = v.toString().padStart(decimals + 1, "0");
  const frac = s.slice(-decimals).replace(/0+$/, "");
  return frac ? `${s.slice(0, -decimals)}.${frac}` : s.slice(0, -decimals);
}
