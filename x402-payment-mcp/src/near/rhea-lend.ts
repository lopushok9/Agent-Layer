import { z } from "zod";
import type { NearAccountService } from "./account.js";
import { NearPublicError } from "./operations.js";
import { call, ftTransferCall, needsStorage, ONE_YOCTO, storageDeposit, type NearPlans, type PlanAction, type PlanCheck } from "./plan.js";
import { formatUnits, parseUnits } from "./rhea.js";
import { formatNear } from "./units.js";

// Rhea Lend (formerly Burrow) on contract.main.burrow.near. Knowledge fixed here
// (burrowland source + live contract):
// - registration: NEP-145 storage_deposit of at least storage_balance_bounds.min
//   (0.1 NEAR on mainnet); storage_unregister always panics, so this NEAR stays
//   locked while the account exists (only the part above the minimum can be
//   withdrawn with storage_withdraw);
// - supply: ft_transfer_call(token -> burrow, msg "") credits the "supplied"
//   balance (earns supply APY, not collateral, cannot be liquidated);
// - balances inside Burrow use token decimals + asset.config.extra_decimals;
// - withdraw: execute({actions:[{Withdraw:{token_id, max_amount?}}]}) with
//   1 yocto; without amount it withdraws all supplied shares. It panics when the
//   asset's free liquidity (supplied + reserved - borrowed) is lower, so nothing
//   moves in that case. Burrow then ft_transfers the token to the wallet (wNEAR
//   stays wNEAR; an optional near_withdraw step unwraps it).
export const RHEA_LEND = "contract.main.burrow.near";
const WNEAR = "wrap.near";
const DEC = /^\d{1,30}(\.\d{1,36})?$/;
const ALIASES: Record<string, string> = { NEAR: WNEAR, WNEAR: WNEAR, USDC: "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1", USDT: "usdt.tether-token.near" };
const CATALOG_TTL = 10 * 60_000;
// execute(Withdraw): own work + ft_transfer (10 TGas) + after_ft_transfer (20 TGas).
// Kept low because NEAR prepays gas at min_gas_purchase_price (1e9 yocto/gas:
// 100 TGas = 0.1 NEAR up front, refunded after). Too little gas makes execute
// panic before anything moves.
const WITHDRAW_TGAS = 60;

const tokenField = z.string().min(1).max(64).describe('Token symbol (NEAR, USDC, USDT, ...) or NEP-141 contract id; NEAR means wrap.near');
export const rheaLendSupplyInput = z.strictObject({
  token: tokenField,
  amount: z.string().min(1).max(70).describe('Human amount, e.g. "0.5"'),
});
export const rheaLendWithdrawInput = z.strictObject({
  token: tokenField,
  amount: z.string().min(1).max(70).default("all").describe('Human amount, or "all" (default) for the whole supplied balance'),
  unwrap_near: z.boolean().default(true).describe("For NEAR: unwrap the withdrawn wNEAR to native NEAR in a second step"),
});

type Meta = { id: string; symbol: string; decimals: number };
type Asset = { token_id: string; supplied: { balance: string }; borrowed: { balance: string }; reserved: string; margin_debt?: { balance: string }; supply_apr?: string; config: { extra_decimals: number; can_deposit: boolean; can_withdraw: boolean; supplied_limit?: string | null } };
type AccountAsset = { token_id: string; balance: string; shares: string; apr?: string };
type LendAccount = { supplied: AccountAsset[]; collateral: AccountAsset[]; borrowed: AccountAsset[] };
export type LendRow = { side: "supplied" | "collateral" | "borrowed"; symbol: string; token_id: string; amount: string; formatted: string; decimals: number; apr_percent: number | null };

export class RheaLend {
  private catalogCache: { at: number; list: Promise<Meta[]> } | null = null;
  constructor(private accounts: NearAccountService, private plans: NearPlans, private now: () => number = Date.now) {}
  private get rpc() { return this.accounts.rpc; }
  private async view<T = any>(contract: string, method: string, args: unknown): Promise<T> { return (await this.rpc.callFunction(contract, method, args)).result as T; }

  // Listed Burrow assets with their FT metadata (cached).
  private catalog(): Promise<Meta[]> {
    if (this.catalogCache && this.now() - this.catalogCache.at < CATALOG_TTL) return this.catalogCache.list;
    const list = (async () => {
      const assets = await this.view<[string, unknown][] | { token_id: string }[]>(RHEA_LEND, "get_assets_paged", { from_index: 0, limit: 100 });
      const ids = (assets ?? []).map((a: any) => Array.isArray(a) ? a[0] : a?.token_id).filter((x: unknown): x is string => typeof x === "string");
      const metas = await Promise.all(ids.map(id => this.metadata(id).catch(() => null)));
      return metas.filter((m): m is Meta => m !== null);
    })();
    list.catch(() => { this.catalogCache = null; });
    this.catalogCache = { at: this.now(), list };
    return list;
  }
  private async metadata(id: string): Promise<Meta | null> {
    const m = await this.view(id, "ft_metadata", {}).catch(() => null);
    if (!m || !Number.isInteger(m.decimals) || m.decimals < 0 || m.decimals > 36) return null;
    return { id, symbol: String(m.symbol ?? id).replace(/[^\x20-\x7e]/g, "?").slice(0, 20), decimals: m.decimals };
  }
  private async resolve(token: string): Promise<Meta> {
    const t = token.trim(), u = t.toUpperCase();
    const direct = ALIASES[u] ?? (t.includes(".") || /^[0-9a-f]{64}$/.test(t) ? t : null);
    if (direct) {
      const m = await this.metadata(direct);
      if (!m) throw new NearPublicError(`token ${direct.slice(0, 64)} has no valid ft_metadata; nothing was signed`);
      return m;
    }
    const matches = (await this.catalog()).filter(m => m.symbol.toUpperCase() === u);
    if (matches.length === 1) return matches[0]!;
    if (matches.length > 1) throw new NearPublicError(`several Rhea Lend assets are called ${token.slice(0, 20)} (${matches.map(m => m.id).join(", ")}); pass the contract id. Nothing was signed`);
    throw new NearPublicError(`${token.slice(0, 40)} is not a Rhea Lend asset; nothing was signed`);
  }
  private async asset(id: string): Promise<Asset> {
    const a = await this.view<Asset | null>(RHEA_LEND, "get_asset", { token_id: id }).catch(() => null);
    if (!a?.config) throw new NearPublicError(`${id} is not listed on Rhea Lend; nothing was signed`);
    return a;
  }
  private account(self: string) { return this.view<LendAccount | null>(RHEA_LEND, "get_account", { account_id: self }); }

  async prepareSupply(userId: string, input: z.input<typeof rheaLendSupplyInput>) {
    const p = rheaLendSupplyInput.parse(input);
    const self = (await this.accounts.account(userId)).accountId;
    const t = await this.resolve(p.token);
    if (!DEC.test(p.amount.trim())) throw new NearPublicError('amount must be a decimal like "0.5"; nothing was signed');
    const amount = parseUnits(p.amount.trim(), t.decimals);
    if (amount <= 0n) throw new NearPublicError("amount must be positive; nothing was signed");
    const [asset, reg, wallet, wrapReg, before] = await Promise.all([
      this.asset(t.id),
      needsStorage(this.rpc, RHEA_LEND, self),
      this.view<string>(t.id, "ft_balance_of", { account_id: self }).then(v => BigInt(v ?? "0")).catch(() => 0n),
      t.id === WNEAR ? needsStorage(this.rpc, WNEAR, self) : Promise.resolve(null),
      this.account(self).catch(() => null),
    ]);
    if (!asset.config.can_deposit) throw new NearPublicError(`Rhea Lend does not accept ${t.symbol} deposits right now; nothing was signed`);
    const scale = 10n ** BigInt(asset.config.extra_decimals ?? 0);
    const limit = asset.config.supplied_limit ? BigInt(asset.config.supplied_limit) : null;
    if (limit !== null && BigInt(asset.supplied.balance) + amount * scale > limit) throw new NearPublicError(`Rhea Lend ${t.symbol} supply cap would be exceeded; nothing was signed`);

    const steps: { title: string; transaction: { receiver_id: string; actions: PlanAction[] }; checks: PlanCheck[] }[] = [];
    if (reg) steps.push({ title: `Register on Rhea Lend (${formatNear(reg)} NEAR storage, not refundable)`, transaction: { receiver_id: RHEA_LEND, actions: [storageDeposit(self, reg, true)] }, checks: [] });
    const actions: PlanAction[] = [];
    let wrap = 0n;
    if (t.id === WNEAR && wallet < amount) {
      wrap = amount - wallet;
      if (wrapReg) actions.push(storageDeposit(self, wrapReg));
      actions.push(call("near_deposit", {}, wrap.toString(), 8));
    } else if (wallet < amount) {
      throw new NearPublicError(`not enough ${t.symbol} in the wallet: need ${formatUnits(amount, t.decimals)}, have ${formatUnits(wallet, t.decimals)}; nothing was signed`);
    }
    actions.push(ftTransferCall(RHEA_LEND, amount));
    steps.push({
      title: `${wrap ? `Wrap ${formatNear(wrap)} NEAR and supply` : "Supply"} ${formatUnits(amount, t.decimals)} ${t.symbol} to Rhea Lend`,
      transaction: { receiver_id: t.id, actions },
      checks: [{ label: "account is registered on Rhea Lend", contract_id: RHEA_LEND, method_name: "storage_balance_of", args: { account_id: self }, path: ["total"], op: "gte", value: "1" }],
    });
    const had = before?.supplied?.find(s => s.token_id === t.id);
    return this.plans.prepare(userId, { title: `Supply ${formatUnits(amount, t.decimals)} ${t.symbol} to Rhea Lend`, steps }, {
      lend: { contract: RHEA_LEND, token: t.symbol, token_id: t.id, amount: formatUnits(amount, t.decimals), supply_apr_percent: aprPercent(asset.supply_apr), ...(had ? { already_supplied: formatUnits(BigInt(had.balance) / scale, t.decimals) } : {}) },
      ...(wrap ? { wrapped_from_native_near: formatNear(wrap) } : {}),
      ...(reg ? { registration_near: formatNear(reg) } : {}),
      notes: [
        "Supplied tokens earn the variable supply APY and are not used as collateral, so they cannot be liquidated. Withdraw with rhea_lend_withdraw_prepare.",
        ...(reg ? [`Registration attaches ${formatNear(reg)} NEAR of storage. Rhea Lend never unregisters accounts, so this NEAR stays locked in the contract.`] : []),
        "Withdrawals need free liquidity in the market: at very high utilization a withdrawal can fail (nothing moves) until borrowers repay.",
      ],
    });
  }

  async prepareWithdraw(userId: string, input: z.input<typeof rheaLendWithdrawInput>) {
    const p = rheaLendWithdrawInput.parse(input);
    const self = (await this.accounts.account(userId)).accountId;
    const t = await this.resolve(p.token);
    const [asset, acct, reg] = await Promise.all([this.asset(t.id), this.account(self).catch(() => null), needsStorage(this.rpc, t.id, self)]);
    if (!asset.config.can_withdraw) throw new NearPublicError(`Rhea Lend withdrawals of ${t.symbol} are paused; nothing was signed`);
    const scale = 10n ** BigInt(asset.config.extra_decimals ?? 0);
    const supplied = acct?.supplied?.find(s => s.token_id === t.id);
    const have = supplied ? BigInt(supplied.balance) : 0n;
    if (have === 0n) throw new NearPublicError(`nothing supplied in ${t.symbol} on Rhea Lend${acct?.collateral?.some(c => c.token_id === t.id) ? " (there is collateral, which this tool does not move)" : ""}; nothing was signed`);
    const all = p.amount.trim().toLowerCase() === "all";
    let inner: bigint;
    if (all) inner = have;
    else {
      if (!DEC.test(p.amount.trim())) throw new NearPublicError('amount must be a decimal like "0.5" or "all"; nothing was signed');
      inner = parseUnits(p.amount.trim(), t.decimals) * scale;
      if (inner <= 0n) throw new NearPublicError("amount must be positive; nothing was signed");
      if (inner > have) throw new NearPublicError(`only ${formatUnits(have / scale, t.decimals)} ${t.symbol} supplied; nothing was signed`);
    }
    const out = inner / scale; // what arrives in the wallet (token units)
    const free = BigInt(asset.supplied.balance) + BigInt(asset.reserved ?? "0") - BigInt(asset.borrowed.balance) - BigInt(asset.margin_debt?.balance ?? "0");
    const warnings = inner > free ? [`the market has only ~${formatUnits((free > 0n ? free : 0n) / scale, t.decimals)} ${t.symbol} free liquidity now; the withdrawal will fail (nothing moves) unless borrowers repay first`] : [];

    const steps: { title: string; transaction: { receiver_id: string; actions: PlanAction[] }; checks: PlanCheck[] }[] = [];
    if (reg) steps.push({ title: `Register the wallet on ${t.symbol}`, transaction: { receiver_id: t.id, actions: [storageDeposit(self, reg)] }, checks: [] });
    const withdraw = all ? { token_id: t.id } : { token_id: t.id, max_amount: inner.toString() };
    steps.push({ title: `Withdraw ${all ? "all supplied" : formatUnits(out, t.decimals)} ${t.symbol} from Rhea Lend`, transaction: { receiver_id: RHEA_LEND, actions: [call("execute", { actions: [{ Withdraw: withdraw }] }, ONE_YOCTO, WITHDRAW_TGAS)] }, checks: [] });
    const unwrap = t.id === WNEAR && p.unwrap_near && out > 0n;
    if (unwrap) steps.push({
      title: `Unwrap ${formatNear(out)} wNEAR to NEAR`,
      transaction: { receiver_id: WNEAR, actions: [call("near_withdraw", { amount: out.toString() }, ONE_YOCTO, 10)] },
      checks: [{ label: `wallet wNEAR >= ${formatNear(out)}`, contract_id: WNEAR, method_name: "ft_balance_of", args: { account_id: self }, path: [], op: "gte", value: out.toString() }],
    });
    return this.plans.prepare(userId, { title: `Withdraw ${all ? "all" : formatUnits(out, t.decimals)} ${t.symbol} from Rhea Lend`, steps }, {
      lend: { contract: RHEA_LEND, token: t.symbol, token_id: t.id, supplied: formatUnits(have / scale, t.decimals), withdraw: all ? `all (~${formatUnits(out, t.decimals)} now, interest keeps accruing)` : formatUnits(out, t.decimals), receive: unwrap ? "native NEAR" : t.symbol },
      ...(warnings.length ? { warnings } : {}),
      notes: ["If the token transfer to the wallet fails, Rhea Lend credits the amount back to the supplied balance."],
    });
  }

  // Positions for omni_balances.
  async positions(self: string): Promise<LendRow[]> {
    const acct = await this.account(self);
    if (!acct) return [];
    const entries = ([["supplied", acct.supplied], ["collateral", acct.collateral], ["borrowed", acct.borrowed]] as const).flatMap(([side, list]) => (list ?? []).map(a => ({ side, a })));
    if (!entries.length) return [];
    const ids = [...new Set(entries.map(e => e.a.token_id))];
    const info = new Map(await Promise.all(ids.map(async id => [id, await Promise.all([this.metadata(id), this.view<Asset | null>(RHEA_LEND, "get_asset", { token_id: id }).catch(() => null)])] as const)));
    return entries.flatMap(({ side, a }) => {
      const [m, asset] = info.get(a.token_id) ?? [null, null];
      if (!m || !asset) return [];
      const v = BigInt(a.balance) / 10n ** BigInt(asset.config.extra_decimals ?? 0);
      if (v === 0n) return [];
      return [{ side, symbol: m.symbol, token_id: a.token_id, amount: v.toString(), formatted: formatUnits(v, m.decimals), decimals: m.decimals, apr_percent: aprPercent(a.apr) }];
    });
  }
}

// The contract's own annual rate (apr field of get_asset / get_account).
function aprPercent(apr?: string | null): number | null {
  const r = Number(apr);
  if (!apr || !Number.isFinite(r)) return null;
  return Math.round(r * 10_000) / 100;
}
