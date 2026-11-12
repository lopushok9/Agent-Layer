import { getAddress, isAddress, parseAbi, type Address } from "viem";
import { z } from "zod";
import type { NearAccountService } from "./account.js";
import type { ChainSignatures, EvmNetwork } from "./chain-signatures.js";
import type { NearIntents, OneClickToken } from "./intents.js";

// Yield discovery for the NEAR Omni Account on NEAR, Base and Ethereum, without
// Enso. Sources, all read only:
// - DefiLlama yields: the broad index (every chain/protocol it tracks).
// - Rhea Lend (contract.main.burrow.near): supply APY computed on-chain from
//   each asset's utilization and rate model, replacing the index rows.
// - Morpho API: listed MetaMorpho vaults with their ERC-4626 address and net APY
//   after the curator fee, replacing the index rows.
// - Aave v3: the index APY of shown rows is re-checked on-chain with
//   Pool.getReserveData (currentLiquidityRate).
// Every field from these sources is untrusted third-party data; text is
// sanitised and nothing here can sign or move funds.
export const DEFILLAMA_URL = "https://yields.llama.fi/pools";
export const MORPHO_URL = "https://api.morpho.org/graphql";
export const RHEA_LEND = "contract.main.burrow.near";
const AAVE_POOL: Record<EvmNetwork, Address> = { base: "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5", ethereum: "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2" };
const LLAMA_CHAIN: Record<string, Network> = { Near: "near", Base: "base", Ethereum: "ethereum" };
const CHAIN_ID: Record<EvmNetwork, number> = { base: 8453, ethereum: 1 };
const CACHE_MS = 10 * 60_000;
const MS_PER_YEAR = 31_536_000_000, S_PER_YEAR = 31_536_000;
const RAY = 10n ** 27n;
const aaveAbi = parseAbi(["function getReserveData(address) view returns ((uint256 configuration,uint128 liquidityIndex,uint128 currentLiquidityRate,uint128 variableBorrowIndex,uint128 currentVariableBorrowRate,uint128 currentStableBorrowRate,uint40 lastUpdateTimestamp,uint16 id,address aTokenAddress,address stableDebtTokenAddress,address variableDebtTokenAddress,address interestRateStrategyAddress,uint128 accruedToTreasury,uint128 unbacked,uint128 isolationModeTotalDebt))"]);

type Network = "near" | "base" | "ethereum";
type Kind = "lending" | "vault" | "lp" | "staking" | "other";

export const yieldSearchInput = z.strictObject({
  networks: z.array(z.enum(["near", "base", "ethereum"])).min(1).max(3).default(["near", "base", "ethereum"]),
  token: z.string().regex(/^[A-Za-z0-9.$_-]{1,20}$/).optional().describe("Only opportunities holding this token symbol, e.g. USDC, NEAR, ETH (WETH/wNEAR match ETH/NEAR)"),
  kind: z.enum(["any", "lending", "vault", "lp", "staking"]).default("any").describe("lending: supply to a lending market; vault: curated ERC-4626 vault; lp: two-token liquidity (impermanent loss); staking: liquid staking"),
  stable_only: z.boolean().default(false).describe("Only stablecoin opportunities"),
  no_il: z.boolean().default(false).describe("Exclude positions with impermanent-loss risk"),
  exclude_rewards: z.boolean().default(false).describe("Rank and filter by base APY only (fees/interest), ignoring reward-token emissions"),
  include_outliers: z.boolean().default(false).describe("Include APYs DefiLlama flags as statistical outliers (usually short-lived)"),
  min_tvl_usd: z.number().min(0).max(1e12).default(250_000),
  min_apy: z.number().min(0).max(100_000).optional().describe("Minimum APY in percent"),
  sort_by: z.enum(["apy", "apy_base", "tvl"]).default("apy"),
  limit: z.number().int().min(1).max(50).default(15),
});

type Row = {
  network: Network; protocol: string; kind: Kind; name: string; tokens: string[];
  apy: number | null; apy_base: number | null; apy_reward: number | null; apy_30d_mean?: number | null;
  tvl_usd: number | null; stablecoin: boolean; il_risk: boolean; outlier?: boolean;
  source: "defillama" | "rhea_onchain" | "morpho_api";
  verified: "onchain" | "protocol_api" | "index_only";
  contract?: string; asset?: string; pool_id?: string;
  check?: Record<string, number | string | null>;
  warnings: string[];
  _underlying?: string[]; _meta?: string | null;
};

type LlamaPool = { chain?: unknown; project?: unknown; symbol?: unknown; pool?: unknown; poolMeta?: unknown; underlyingTokens?: unknown; rewardTokens?: unknown; apy?: unknown; apyBase?: unknown; apyReward?: unknown; apyMean30d?: unknown; tvlUsd?: unknown; stablecoin?: unknown; ilRisk?: unknown; exposure?: unknown; outlier?: unknown };

export class YieldSearch {
  private llama: { at: number; rows: Row[] } | null = null;
  private llamaInflight: Promise<Row[]> | null = null;
  private morpho: { at: number; rows: Row[] } | null = null;

  constructor(
    private accounts: NearAccountService,
    private intents: NearIntents,
    private cs: ChainSignatures | null,
    private fetcher: typeof fetch = globalThis.fetch,
    private now: () => number = Date.now,
  ) {}

  async search(input: z.input<typeof yieldSearchInput>) {
    const p = yieldSearchInput.parse(input);
    const started = this.now();
    const want = new Set<Network>(p.networks);
    const evm = (["base", "ethereum"] as const).filter(n => want.has(n));
    const errors: string[] = [];
    const guard = <T>(label: string, f: () => Promise<T>) => f().catch(e => { errors.push(`${label}: ${clean(String((e as Error)?.message ?? e), 160)}`); return null; });

    const [llama, rhea, morpho] = await Promise.all([
      guard("defillama", () => this.llamaRows()),
      want.has("near") ? guard("rhea_lend", () => this.rheaRows()) : Promise.resolve(null),
      evm.length ? guard("morpho_api", () => this.morphoRows()) : Promise.resolve(null),
    ]);

    let rows: Row[] = [];
    for (const r of llama ?? []) {
      if (!want.has(r.network)) continue;
      if (rhea && r.protocol === "rhea-lend") continue;          // replaced by on-chain rows
      if (morpho && r.protocol.startsWith("morpho")) continue;   // replaced by Morpho API vaults
      rows.push(r);
    }
    if (rhea) {
      const index = new Map((llama ?? []).filter(r => r.protocol === "rhea-lend").map(r => [r._underlying?.[0] ?? "", r]));
      for (const r of rhea) {
        const l = index.get(r.asset ?? "");
        if (l) r.check = { ...r.check, defillama_apy: l.apy };
        rows.push(r);
      }
    }
    for (const r of morpho ?? []) if (want.has(r.network)) rows.push(r);

    const score = (r: Row) => p.exclude_rewards ? r.apy_base : r.apy;
    const token = p.token ? norm(p.token) : null;
    rows = rows.filter(r => {
      if (r.tvl_usd === null || r.tvl_usd < p.min_tvl_usd) return false;
      if (p.kind !== "any" && r.kind !== p.kind) return false;
      if (p.stable_only && !r.stablecoin) return false;
      if (p.no_il && r.il_risk) return false;
      if (!p.include_outliers && r.outlier) return false;
      if (token && !r.tokens.some(t => norm(t) === token)) return false;
      const s = score(r);
      if (s === null || s <= 0) return false;
      if (p.min_apy !== undefined && s < p.min_apy) return false;
      return true;
    });
    const key = (r: Row) => p.sort_by === "tvl" ? r.tvl_usd : p.sort_by === "apy_base" ? r.apy_base : score(r);
    rows.sort((a, b) => (key(b) ?? -1) - (key(a) ?? -1));
    const matched = rows.length;
    const shown = rows.slice(0, p.limit);

    await guard("aave_onchain", () => this.verifyAave(shown));
    for (const r of shown) annotate(r);

    return {
      query: p,
      results: shown.map(({ _underlying, _meta, ...r }) => r),
      matched, shown: shown.length,
      sources: {
        defillama: llama ? "ok" : "failed", ...(want.has("near") ? { rhea_lend_onchain: rhea ? "ok" : "failed" } : {}),
        ...(evm.length ? { morpho_api: morpho ? "ok" : "failed", aave_onchain_check: this.cs ? "on shown rows" : "unavailable" } : {}),
      },
      ...(errors.length ? { partial: true, errors } : {}),
      took_ms: this.now() - started,
      notes: [
        "APY is variable and backward-looking; percent per year. Lending tvl_usd is available liquidity (supplied minus borrowed), as in DefiLlama. apy_base is fees/interest, apy_reward is token emissions whose value can drop. verified: onchain = recomputed from contract state now; protocol_api = the protocol's own API; index_only = DefiLlama only.",
        "Data comes from third parties and is not advice. Before depositing check the contract, the asset and the exit conditions (warnings).",
        "To enter a position build it with evm_batch_prepare (approve + deposit, Base/Ethereum) or near_transaction_prepare (NEAR) and confirm the preview; omni_balances shows what is available to deposit.",
      ],
    };
  }

  // ---- DefiLlama ---------------------------------------------------------
  private llamaRows(): Promise<Row[]> {
    if (this.llama && this.now() - this.llama.at < CACHE_MS) return Promise.resolve(this.llama.rows);
    this.llamaInflight ??= this.fetchLlama().then(rows => { this.llama = { at: this.now(), rows }; return rows; }).finally(() => { this.llamaInflight = null; });
    return this.llamaInflight;
  }

  private async fetchLlama(): Promise<Row[]> {
    const res = await this.fetcher(DEFILLAMA_URL, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(25_000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json() as { data?: LlamaPool[] };
    if (!Array.isArray(body?.data)) throw new Error("unexpected response");
    return body.data.flatMap(x => {
      const network = typeof x.chain === "string" ? LLAMA_CHAIN[x.chain] : undefined;
      if (!network || typeof x.project !== "string" || typeof x.symbol !== "string") return [];
      const project = clean(x.project, 40).toLowerCase();
      const symbol = clean(x.symbol, 60);
      const multi = x.exposure === "multi";
      const underlying = Array.isArray(x.underlyingTokens) ? x.underlyingTokens.filter((t): t is string => typeof t === "string").slice(0, 8).map(t => clean(t, 80)) : [];
      const meta = typeof x.poolMeta === "string" ? clean(x.poolMeta, 80) : null;
      return [{
        network, protocol: project, kind: classify(project, multi), name: symbol + (meta ? ` (${meta})` : ""),
        tokens: symbol.split(/[-/ ]+/).filter(Boolean).slice(0, 8),
        apy: num(x.apy), apy_base: num(x.apyBase), apy_reward: num(x.apyReward), apy_30d_mean: num(x.apyMean30d),
        tvl_usd: num(x.tvlUsd), stablecoin: x.stablecoin === true, il_risk: x.ilRisk === "yes", outlier: x.outlier === true,
        source: "defillama", verified: "index_only", ...(typeof x.pool === "string" ? { pool_id: clean(x.pool, 64) } : {}),
        ...(network === "near" && underlying[0] ? { asset: underlying[0] } : {}),
        ...(Array.isArray(x.rewardTokens) && x.rewardTokens.length ? { check: { reward_tokens: x.rewardTokens.filter(t => typeof t === "string").slice(0, 4).map(t => clean(t as string, 80)).join(",") } } : {}),
        warnings: [], _underlying: underlying, _meta: meta,
      } satisfies Row];
    });
  }

  // ---- Rhea Lend (on-chain) ----------------------------------------------
  private async rheaRows(): Promise<Row[]> {
    const [assets, catalog] = await Promise.all([this.rheaAssets(), this.intents.catalog().catch(() => [] as OneClickToken[])]);
    const known = new Map(catalog.filter(t => t.blockchain === "near" && t.contractAddress).map(t => [t.contractAddress!, t]));
    return assets.flatMap(([id, a]) => {
      const t = known.get(id);
      const c = a?.config;
      if (!t || !c || c.can_deposit !== true) return [];
      const supplied = big(a.supplied?.balance), reserved = big(a.reserved), borrowed = big(a.borrowed?.balance);
      const extra = Number.isInteger(c.extra_decimals) ? c.extra_decimals as number : 0;
      if (supplied === null || reserved === null || borrowed === null) return [];
      const apy = rheaSupplyApy(supplied + reserved, borrowed, c);
      if (apy === null) return [];
      // Same convention as the index for lending: TVL = liquidity still available (supplied - borrowed).
      const usd = (v: bigint) => t.price === undefined ? null : round(Number(v) / 10 ** (t.decimals + extra) * t.price, 0);
      const tvl = usd(supplied + reserved > borrowed ? supplied + reserved - borrowed : 0n);
      return [{
        network: "near", protocol: "rhea-lend", kind: "lending", name: `${t.symbol} supply`, tokens: [t.symbol],
        apy: round(apy.supply, 4), apy_base: round(apy.supply, 4), apy_reward: null, tvl_usd: tvl,
        stablecoin: /^(USDC|USDT|DAI|FRAX|USDC\.E|USDT\.E|USN)$/i.test(t.symbol), il_risk: false,
        source: "rhea_onchain", verified: "onchain", contract: RHEA_LEND, asset: id,
        check: { utilization_percent: round(apy.utilization * 100, 2), borrow_apy: round(apy.borrow, 4), total_supplied_usd: usd(supplied) },
        warnings: [],
      } satisfies Row];
    });
  }

  private async rheaAssets(): Promise<[string, any][]> {
    const out: [string, any][] = [];
    for (let from = 0; from < 300; from += 100) {
      const page = (await this.accounts.rpc.callFunction(RHEA_LEND, "get_assets_paged", { from_index: from, limit: 100 })).result;
      if (!Array.isArray(page)) throw new Error("unexpected get_assets_paged result");
      for (const e of page) if (Array.isArray(e) && typeof e[0] === "string" && e[0].length <= 64) out.push([e[0], e[1]]);
      if (page.length < 100) break;
    }
    return out;
  }

  // ---- Morpho vaults ------------------------------------------------------
  private async morphoRows(): Promise<Row[]> {
    if (this.morpho && this.now() - this.morpho.at < CACHE_MS) return this.morpho.rows;
    const query = `{ vaults(first: 200, orderBy: TotalAssetsUsd, orderDirection: Desc, where: { chainId_in: [8453, 1], listed: true, totalAssetsUsd_gte: 10000 }) { items { address name chain { id } asset { address symbol } state { totalAssetsUsd apy netApy netApyExcludingRewards fee } } } }`;
    const res = await this.fetcher(MORPHO_URL, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query }), signal: AbortSignal.timeout(12_000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json() as { data?: { vaults?: { items?: any[] } } };
    const items = body?.data?.vaults?.items;
    if (!Array.isArray(items)) throw new Error("unexpected response");
    const rows = items.flatMap(v => {
      const network: EvmNetwork | null = v?.chain?.id === 8453 ? "base" : v?.chain?.id === 1 ? "ethereum" : null;
      if (!network || typeof v.address !== "string" || !isAddress(v.address, { strict: false }) || typeof v?.asset?.symbol !== "string" || typeof v?.asset?.address !== "string" || !isAddress(v.asset.address, { strict: false })) return [];
      const s = v.state ?? {};
      const net = num(s.netApy), base = num(s.netApyExcludingRewards);
      const symbol = clean(v.asset.symbol, 20);
      return [{
        network, protocol: "morpho", kind: "vault", name: clean(String(v.name ?? "Morpho vault"), 60), tokens: [symbol],
        apy: net === null ? null : round(net * 100, 4), apy_base: base === null ? null : round(base * 100, 4),
        apy_reward: net !== null && base !== null ? round((net - base) * 100, 4) : null,
        tvl_usd: num(s.totalAssetsUsd) === null ? null : round(num(s.totalAssetsUsd)!, 0),
        stablecoin: /^(USDC|USDT|DAI|USDS|EURC|PYUSD|USDE|GHO|FRAX|RLUSD|USD0|USDA|SDAI|SUSDS)$/i.test(symbol), il_risk: false,
        source: "morpho_api", verified: "protocol_api", contract: getAddress(v.address), asset: getAddress(v.asset.address),
        ...(num(s.fee) !== null ? { check: { curator_fee_percent: round(num(s.fee)! * 100, 2) } } : {}),
        warnings: [],
      } satisfies Row];
    });
    this.morpho = { at: this.now(), rows };
    return rows;
  }

  // ---- Aave v3 on-chain check --------------------------------------------
  private async verifyAave(rows: Row[]) {
    if (!this.cs) return;
    const byNet = new Map<EvmNetwork, Row[]>();
    for (const r of rows) {
      const u = r._underlying?.[0];
      if (r.protocol === "aave-v3" && r.network !== "near" && u && isAddress(u, { strict: false })) byNet.set(r.network, [...(byNet.get(r.network) ?? []), r]);
    }
    await Promise.all([...byNet].map(async ([network, list]) => {
      const results = await this.cs!.rpcFor(network).multicall({ allowFailure: true, contracts: list.map(r => ({ address: AAVE_POOL[network], abi: aaveAbi, functionName: "getReserveData" as const, args: [getAddress(r._underlying![0]!)] as const })) });
      results.forEach((res, i) => {
        const r = list[i]!;
        if (res.status !== "success") return;
        const rate = (res.result as { currentLiquidityRate: bigint }).currentLiquidityRate;
        const apr = Number(rate * 1_000_000n / RAY) / 1e6;
        const apy = round((Math.pow(1 + apr / S_PER_YEAR, S_PER_YEAR) - 1) * 100, 4);
        r.check = { ...r.check, onchain_supply_apy: apy, defillama_apy_base: r.apy_base };
        r.contract = AAVE_POOL[network];
        r.asset = getAddress(r._underlying![0]!);
        r.verified = "onchain";
        if (r.apy_base !== null && Math.abs(apy - r.apy_base) > Math.max(0.5, r.apy_base * 0.2)) r.warnings.push(`on-chain supply APY ${apy}% differs from the index (${r.apy_base}%)`);
        r.apy_base = apy;
        r.apy = round(apy + (r.apy_reward ?? 0), 4);
      });
    }));
  }
}

// Rhea Lend (Burrow) rate model: per-millisecond rate with 27 decimals, linear
// up to target utilization and then to the max rate; suppliers get the borrow
// interest pro rata minus the reserve ratio.
export function rheaSupplyApy(totalSupplied: bigint, borrowed: bigint, c: Record<string, any>): { supply: number; borrow: number; utilization: number } | null {
  const tr = big(c.target_utilization_rate), mr = big(c.max_utilization_rate);
  const tu = Number(c.target_utilization) / 10_000, reserve = Number(c.reserve_ratio) / 10_000;
  if (tr === null || mr === null || !(tu > 0 && tu < 1) || !(reserve >= 0 && reserve <= 1)) return null;
  if (totalSupplied === 0n) return { supply: 0, borrow: 0, utilization: 0 };
  const u = Math.min(Number(borrowed * 1_000_000_000n / totalSupplied) / 1e9, 1);
  const t = Number(tr - RAY) / 1e27, m = Number(mr - RAY) / 1e27;
  const excess = u < tu ? u * t / tu : t + (u - tu) * (m - t) / (1 - tu);
  const borrow = Math.expm1(MS_PER_YEAR * Math.log1p(excess));
  return { supply: borrow * u * (1 - reserve) * 100, borrow: borrow * 100, utilization: u };
}

function annotate(r: Row) {
  if (r.outlier) r.warnings.push("DefiLlama flags this APY as a statistical outlier");
  if ((r.apy ?? 0) > 100) r.warnings.push("APY above 100% is rarely sustained");
  if ((r.apy_reward ?? 0) > 0 && (r.apy_base ?? 0) <= 0) r.warnings.push("yield is only reward-token emissions; it changes with that token's price");
  else if ((r.apy_reward ?? 0) > (r.apy_base ?? 0)) r.warnings.push("most of the yield is reward-token emissions");
  if (r.il_risk) r.warnings.push("two-token liquidity: impermanent loss risk");
  if (r.apy_30d_mean != null && r.apy != null && r.apy > 2 * r.apy_30d_mean + 1) r.warnings.push(`current APY is far above its 30-day mean (${round(r.apy_30d_mean, 2)}%)`);
  if ((r.tvl_usd ?? 0) < 1_000_000) r.warnings.push("TVL below $1M: thin liquidity, APY moves fast");
  if (r._meta && /fee|lock|cooldown|exit/i.test(r._meta)) r.warnings.push(`pool note: ${r._meta}`);
  if (r.source === "rhea_onchain") r.warnings.push("Rhea farm rewards are not included");
  if (r.kind === "other") r.warnings.push("protocol type not classified (often RWA, credit or structured products): check what backs the yield");
  if (r.stablecoin && (r.apy ?? 0) > 20) r.warnings.push("stablecoin yield above 20% usually means credit, leverage or emission risk");
  if (r.kind === "staking") r.warnings.push("liquid staking: unstaking may take days; the token can trade below its value");
}

function classify(project: string, multi: boolean): Kind {
  if (multi) return "lp";
  if (/lst|lido|staking|stake|rocket|ether\.?fi|renzo|kelp|swell|stader|linear|meta-pool|binance-staked|coinbase-wrapped/.test(project)) return "staking";
  if (/lend|aave|compound|spark|moonwell|fluid|euler|silo|radiant|seamless|venus|benqi|sky-lending|maker/.test(project)) return "lending";
  if (/vault|yearn|beefy|morpho|harvest|convex|pendle|sommelier|idle|ipor|gearbox|summer|yo-protocol|wasabi/.test(project)) return "vault";
  return "other";
}
const ALIASES: Record<string, string> = { WETH: "ETH", WNEAR: "NEAR", "USDC.E": "USDC", "USDT.E": "USDT", USDBC: "USDC" };
function norm(s: string) { const u = s.toUpperCase(); return ALIASES[u] ?? u; }
function clean(s: string, n: number) { return s.replace(/[^\x20-\x7e]/g, "?").slice(0, n); }
function num(v: unknown): number | null { return typeof v === "number" && Number.isFinite(v) ? v : null; }
function big(v: unknown): bigint | null { return typeof v === "string" && /^\d{1,78}$/.test(v) ? BigInt(v) : null; }
function round(n: number, d = 2) { const f = 10 ** d; return Math.round(n * f) / f; }
