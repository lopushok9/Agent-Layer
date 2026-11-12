import { erc20Abi, getAddress, isAddress, type Address } from "viem";
import { STORAGE_BYTE_COST, type NearAccountService } from "./account.js";
import { EVM_CHAINS, type ChainSignatures, type EvmNetwork } from "./chain-signatures.js";
import type { NearIntents, OneClickToken } from "./intents.js";
import type { RheaLend } from "./rhea-lend.js";
import { assertAccountId, formatNear } from "./units.js";

// One read for everything this NEAR Omni Account holds: native NEAR and NEP-141
// tokens on the NEAR wallet, the NEAR Intents balance, and ETH plus listed
// ERC-20s on the Chain Signatures EVM address. Every source runs in parallel and
// fails on its own, so one slow provider never hides the others.
//
// Wallet token discovery asks the FastNEAR indexer which FT contracts the
// account touched; the indexer is only a hint, every amount shown comes from
// ft_balance_of on NEAR RPC. If the indexer is down, the NEAR-chain tokens
// listed by 1Click are checked instead. USD prices come from the cached 1Click
// token list.
export const FASTNEAR_URL = "https://api.fastnear.com";
const ALWAYS = ["wrap.near", "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1", "usdt.tether-token.near"];
const MAX_FT = 40, CONCURRENCY = 8;
const UINT = /^\d{1,78}$/;
const ONECLICK_CHAIN: Record<EvmNetwork, string> = { base: "base", ethereum: "eth" };

type Row = { symbol: string; asset: string; amount: string; formatted: string; decimals: number; value_usd: number | null; unlisted?: true };

export class OmniBalances {
  // Optional DeFi position readers (set by the app).
  lend: RheaLend | null = null;
  constructor(
    private accounts: NearAccountService,
    private intents: NearIntents,
    private cs: ChainSignatures | null,
    private fetcher: typeof fetch = globalThis.fetch,
    private indexer = FASTNEAR_URL,
    private now: () => number = Date.now,
  ) {}

  async all(userId: string) {
    const started = this.now();
    const self = (await this.accounts.account(userId)).accountId;
    const catalog = this.intents.catalog().catch(() => [] as OneClickToken[]);
    const errors: string[] = [];
    const guard = <T>(label: string, p: Promise<T>) => p.catch(e => { errors.push(`${label}: ${String((e as Error)?.message ?? e).replace(/[^\x20-\x7e]/g, "").slice(0, 160)}`); return null; });

    const [wallet, intents, evm, tokens, lend] = await Promise.all([
      guard("near wallet", this.wallet(self, catalog)),
      guard("intents", this.intents.balances(userId)),
      this.cs ? guard("evm", this.evm(self, catalog)) : Promise.resolve(null),
      catalog,
      this.lend ? guard("rhea lend", this.lend.positions(self)) : Promise.resolve(null),
    ]);
    if (!tokens.length) errors.push("prices: the 1Click token list is unavailable, USD values omitted");

    const intentRows: Row[] = (intents?.balances ?? []).map((b: any) => ({
      symbol: b.symbol ?? "?", asset: b.asset_id, amount: b.amount, formatted: b.formatted ?? b.amount, decimals: b.decimals ?? 0,
      value_usd: typeof b.value_usd === "number" ? b.value_usd : null, ...(b.symbol ? {} : { unlisted: true as const }),
    }));
    const sections = {
      near_wallet: wallet ? { account_id: self, assets: wallet.rows, total_value_usd: sum(wallet.rows), available_near: wallet.available, storage_locked_near: wallet.storageLocked, exists_on_chain: wallet.exists } : { account_id: self, error: "unavailable" },
      intents: intents ? { contract: "intents.near", assets: intentRows, total_value_usd: sum(intentRows) } : { contract: "intents.near", error: "unavailable" },
      ...(this.cs ? { evm: evm ? { address: evm.address, networks: evm.networks } : { error: "unavailable" } } : {}),
    };
    // Rhea Lend: supplied + collateral count positive, borrowed negative.
    const nearPrices = new Map(tokens.filter(t => t.blockchain === "near" && t.contractAddress).map(t => [t.contractAddress!, t.price]));
    const lendRows = (lend ?? []).map(r => { const price = nearPrices.get(r.token_id); return { ...r, value_usd: price === undefined ? null : usd(BigInt(r.amount), r.decimals, price) }; });
    const lendNet = round(lendRows.reduce((t, r) => t + (r.value_usd ?? 0) * (r.side === "borrowed" ? -1 : 1), 0));
    const defi = this.lend ? { rhea_lend: lend ? { contract: "contract.main.burrow.near", positions: lendRows, net_value_usd: lendNet } : { contract: "contract.main.burrow.near", error: "unavailable" } } : null;
    const total = round(sum(wallet?.rows ?? []) + sum(intentRows) + (evm?.networks ?? []).reduce((s, n) => s + ("total_value_usd" in n ? n.total_value_usd : 0), 0) + (lend ? lendNet : 0));
    return {
      account_id: self,
      ...sections,
      ...(defi ? { defi } : {}),
      total_value_usd: total,
      prices: "1Click token list (cached up to 5 min); assets without a price show value_usd null and are not in totals",
      ...(errors.length ? { partial: true, errors } : {}),
      took_ms: this.now() - started,
      next: [
        "Swap intents assets: intents_exchange_prepare. Move wallet tokens into intents: intents_deposit_prepare. Back to the wallet without gas: intents_withdraw_prepare.",
        "Fund the NEAR wallet at account_id; fund Base/Ethereum gas at evm.address.",
      ],
    };
  }

  private async wallet(self: string, catalog: Promise<OneClickToken[]>) {
    const [view, contracts, list] = await Promise.all([this.accounts.rpc.viewAccount(self), this.discover(self, catalog), catalog]);
    const prices = new Map(list.filter(t => t.blockchain === "near" && t.contractAddress).map(t => [t.contractAddress!, t]));
    const near = prices.get("wrap.near")?.price;
    const amount = BigInt(view?.amount ?? "0"), storage = BigInt(view?.storage_usage ?? 0) * STORAGE_BYTE_COST;
    const rows: Row[] = amount > 0n ? [{ symbol: "NEAR", asset: "native", amount: amount.toString(), formatted: formatNear(amount), decimals: 24, value_usd: near === undefined ? null : usd(amount, 24, near) }] : [];
    const fts = await pool(contracts, CONCURRENCY, async c => {
      const raw = await this.view(c, "ft_balance_of", { account_id: self }).catch(() => null);
      if (typeof raw !== "string" || !UINT.test(raw) || raw === "0") return null;
      const known = prices.get(c);
      const meta = known ? { symbol: known.symbol, decimals: known.decimals } : await this.metadata(c);
      if (!meta) return null;
      const v = BigInt(raw);
      return { symbol: meta.symbol, asset: `nep141:${c}`, amount: raw, formatted: fmt(v, meta.decimals), decimals: meta.decimals, value_usd: known?.price === undefined ? null : usd(v, meta.decimals, known.price), ...(known ? {} : { unlisted: true as const }) } satisfies Row;
    });
    rows.push(...fts.filter((r): r is NonNullable<typeof r> => r !== null).sort((a, b) => (b.value_usd ?? -1) - (a.value_usd ?? -1)));
    return { rows, exists: Boolean(view), available: formatNear(amount > storage ? amount - storage : 0n), storageLocked: formatNear(storage) };
  }

  // Candidate FT contracts: indexer hint plus the common ones; on indexer
  // failure, every NEAR-chain token 1Click lists.
  private async discover(self: string, catalog: Promise<OneClickToken[]>): Promise<string[]> {
    let hinted: string[] | null = null;
    try {
      const res = await this.fetcher(`${this.indexer}/v1/account/${encodeURIComponent(self)}/ft`, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(4_000) });
      const body = res.ok ? await res.json() as { tokens?: { contract_id?: unknown }[] } : null;
      if (body && Array.isArray(body.tokens)) hinted = body.tokens.flatMap(t => typeof t?.contract_id === "string" && validAccount(t.contract_id) ? [t.contract_id] : []);
    } catch { /* fall back below */ }
    const base = hinted ?? (await catalog).flatMap(t => t.blockchain === "near" && t.contractAddress && validAccount(t.contractAddress) ? [t.contractAddress] : []);
    return [...new Set([...ALWAYS, ...base])].slice(0, MAX_FT);
  }

  private async metadata(contract: string): Promise<{ symbol: string; decimals: number } | null> {
    const m = await this.view(contract, "ft_metadata", {}).catch(() => null) as { symbol?: unknown; decimals?: unknown } | null;
    if (!m || typeof m.symbol !== "string" || !Number.isInteger(m.decimals) || (m.decimals as number) < 0 || (m.decimals as number) > 36) return null;
    return { symbol: m.symbol.replace(/[^\x20-\x7e]/g, "?").slice(0, 20), decimals: m.decimals as number };
  }

  private async view(contract: string, method: string, args: unknown) { return (await this.accounts.rpc.callFunction(contract, method, args)).result; }

  private async evm(self: string, catalog: Promise<OneClickToken[]>) {
    const cs = this.cs!;
    const address = await cs.address(self);
    const list = await catalog;
    const networks = await Promise.all((Object.keys(EVM_CHAINS) as EvmNetwork[]).map(async network => {
      const chain = ONECLICK_CHAIN[network];
      const native = list.find(t => t.blockchain === chain && !t.contractAddress && t.symbol === "ETH")?.price;
      const erc20 = list.filter(t => t.blockchain === chain && t.contractAddress && isAddress(t.contractAddress, { strict: false }));
      try {
        const rpc = cs.rpcFor(network);
        const [wei, results] = await Promise.all([
          rpc.getBalance({ address }),
          erc20.length ? rpc.multicall({ allowFailure: true, contracts: erc20.map(t => ({ address: getAddress(t.contractAddress!) as Address, abi: erc20Abi, functionName: "balanceOf" as const, args: [address] as const })) }) : Promise.resolve([]),
        ]);
        const rows: Row[] = wei > 0n ? [{ symbol: "ETH", asset: "native", amount: wei.toString(), formatted: fmt(wei, 18), decimals: 18, value_usd: native === undefined ? null : usd(wei, 18, native) }] : [];
        results.forEach((r, i) => {
          if (r.status !== "success" || typeof r.result !== "bigint" || r.result === 0n) return;
          const t = erc20[i]!;
          rows.push({ symbol: t.symbol, asset: getAddress(t.contractAddress!), amount: r.result.toString(), formatted: fmt(r.result, t.decimals), decimals: t.decimals, value_usd: t.price === undefined ? null : usd(r.result, t.decimals, t.price) });
        });
        return { network, chain_id: EVM_CHAINS[network], assets: rows, total_value_usd: sum(rows) };
      } catch { return { network, chain_id: EVM_CHAINS[network], error: "balance unavailable" }; }
    }));
    return { address, networks };
  }
}

function validAccount(id: string) { try { assertAccountId(id); return true; } catch { return false; } }
function fmt(v: bigint, decimals: number): string {
  if (decimals === 0) return v.toString();
  const s = v.toString().padStart(decimals + 1, "0");
  const frac = s.slice(-decimals).replace(/0+$/, "");
  return frac ? `${s.slice(0, -decimals)}.${frac}` : s.slice(0, -decimals);
}
function usd(v: bigint, decimals: number, price: number) { return round(Number(fmt(v, decimals)) * price); }
function round(n: number) { return Math.round(n * 100) / 100; }
function sum(rows: Row[]) { return round(rows.reduce((s, r) => s + (r.value_usd ?? 0), 0)); }

async function pool<T, R>(items: T[], limit: number, fn: (t: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) { const i = next++; out[i] = await fn(items[i]!); }
  }));
  return out;
}
