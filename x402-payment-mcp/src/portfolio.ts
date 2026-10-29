import { getAddress, hexToString, isAddress, parseAbi, type Address, type Hex, type PublicClient } from "viem";
import { z } from "zod";
import type { EnsoApi } from "./enso-routes.js";
import { chainIds, walletNetwork, type WalletNetwork } from "./transaction-builder.js";

export const portfolioInput = z.strictObject({
  network: walletNetwork,
  min_value_usd: z.number().min(0).max(1_000_000).default(0.01).describe("Hide assets worth less than this (dust); their count is still reported"),
});

type Fetch = typeof fetch;
type Wallets = { account(userId: string): Promise<{ address: Address }>; rpc(network: WalletNetwork): PublicClient };
type DefiToken = Record<string, any>;
type Holding = { token: string; symbol: string | null; decimals: number; amount_raw: bigint; price: number | null };
type Pool = Awaited<ReturnType<Portfolio["poolStats"]>>;
type Underlying = { token: Address; symbol: string | null; decimals: number | null };

const NATIVE = "native";
const ALCHEMY_NETWORK: Record<WalletNetwork, string> = { base: "base-mainnet", ethereum: "eth-mainnet" };
const BLOCKS_PER_DAY: Record<WalletNetwork, bigint> = { base: 43_200n, ethereum: 7_200n };
const poolAbi = parseAbi([
  "function getReserves() view returns (uint256, uint256, uint256)",
  "function totalSupply() view returns (uint256)",
  "function token0() view returns (address)",
  "function token1() view returns (address)",
  "function stable() view returns (bool)",
  "function POOL_TYPE() view returns (bytes32)",
  "function index0() view returns (uint256)",
  "function index1() view returns (uint256)",
]);
const vaultAbi = parseAbi(["function convertToAssets(uint256 shares) view returns (uint256)", "function asset() view returns (address)"]);

// One read of what the account holds, what it is worth and what each DeFi
// position earns. Alchemy's Portfolio API gives balances and plain-token
// prices in one per-user call; Enso is asked only which tokens are DeFi
// positions (APY, TVL, underlying), cached per token for every user, so its
// calls grow with distinct positions, not users. Positions Alchemy cannot
// price (LP, vault shares) are priced on-chain from their underlying tokens.
// Unpriced non-DeFi tokens are hidden by count only: airdropped spam names
// are attacker-chosen text and never reach the agent.
export class Portfolio {
  private cache = new Map<string, { at: number; data: unknown }>();
  private defi = new Map<string, { at: number; data: DefiToken | null }>();
  constructor(private api: EnsoApi, private wallets: Wallets, private rpcUrl: (network: WalletNetwork) => string | undefined, private fetcher: Fetch = fetch, private now: () => number = Date.now) {}

  async portfolio(userId: string, input: z.input<typeof portfolioInput>) {
    const p = portfolioInput.parse(input);
    const { address } = await this.wallets.account(userId);
    const key = alchemyKey(this.rpcUrl(p.network));
    let source = "alchemy";
    let holdings: Holding[];
    try {
      if (!key) throw new Error("no Alchemy key");
      holdings = await this.cached(`alchemy:${p.network}:${address}`, 30_000, () => this.alchemyHoldings(key, p.network, address)) as Holding[];
    } catch {
      source = "enso";
      holdings = await this.cached(`enso:${p.network}:${address}`, 30_000, () => this.ensoHoldings(p.network, address)) as Holding[];
    }
    const meta = await this.defiTokens(p.network, holdings.filter(h => h.token !== NATIVE).map(h => h.token));
    const prices = new Map(holdings.filter(h => h.price !== null).map(h => [h.token, h.price!]));
    const rows = await Promise.all(holdings.map(async h => {
      const d = meta.get(h.token);
      const amount = Number(h.amount_raw) / 10 ** h.decimals;
      const base = { token: h.token === NATIVE ? NATIVE : getAddress(h.token), symbol: h.symbol, amount, amount_raw: h.amount_raw.toString() };
      if (!d) return { ...base, price_usd: h.price, value_usd: h.price === null ? null : round(amount * h.price), defi: false };
      const { price_usd: computed, ...position } = await this.position(p.network, getAddress(h.token), h, d, key, prices);
      const price = h.price ?? computed;
      return { ...base, price_usd: price, value_usd: price === null ? null : round(amount * price), defi: true, position };
    }));
    // A DeFi position stays visible without a price (its price_error says why);
    // anything else needs a price at or above the dust threshold.
    const shown = rows.filter(r => r.value_usd === null ? r.defi : r.value_usd >= p.min_value_usd);
    shown.sort((a, b) => (b.value_usd ?? -1) - (a.value_usd ?? -1));
    return {
      network: p.network, address,
      total_value_usd: round(shown.reduce((s, r) => s + (r.value_usd ?? 0), 0)),
      asset_count: shown.length, position_count: shown.filter(r => r.defi).length,
      hidden_asset_count: rows.length - shown.length,
      hidden_reason: `no price and not a DeFi position, or worth less than $${p.min_value_usd}; names of hidden tokens are not shown (airdropped tokens are often spam)`,
      assets: shown.map(({ defi: _, ...r }) => r),
      sources: { balances_and_prices: source, positions: "enso", position_prices: "on-chain (pool reserves, ERC-4626 convertToAssets)" },
      trust: "Balances, prices, APY and TVL are third-party data; fee APR is estimated by this server from one day of the pool's fee index. Informational, not advice; past fees do not predict future ones.",
    };
  }

  private async alchemyHoldings(key: string, network: WalletNetwork, address: Address): Promise<Holding[]> {
    const out: Holding[] = [];
    let pageKey: string | undefined;
    for (let page = 0; page < 5; page++) {
      const res = await this.fetcher(`https://api.g.alchemy.com/data/v1/${key}/assets/tokens/by-address`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ addresses: [{ address, networks: [ALCHEMY_NETWORK[network]] }], withMetadata: true, withPrices: true, ...(pageKey ? { pageKey } : {}) }), signal: AbortSignal.timeout(15_000) });
      if (!res.ok) throw new Error("Alchemy portfolio is unavailable");
      const body = await res.json() as { data?: { tokens?: any[]; pageKey?: unknown } };
      for (const t of body?.data?.tokens ?? []) {
        const token = t?.tokenAddress === null ? NATIVE : typeof t?.tokenAddress === "string" && isAddress(t.tokenAddress) ? t.tokenAddress.toLowerCase() : null;
        if (!token || typeof t?.tokenBalance !== "string" || !/^0x[0-9a-fA-F]{1,64}$/.test(t.tokenBalance)) continue;
        const amount_raw = BigInt(t.tokenBalance);
        const decimals = token === NATIVE ? 18 : Number(t?.tokenMetadata?.decimals);
        if (amount_raw === 0n || !Number.isInteger(decimals) || decimals < 0 || decimals > 36) continue;
        const usd = (Array.isArray(t?.tokenPrices) ? t.tokenPrices : []).find((x: any) => x?.currency === "usd");
        out.push({ token, symbol: token === NATIVE ? "ETH" : text(t?.tokenMetadata?.symbol, 30), decimals, amount_raw, price: positive(Number(usd?.value)) });
      }
      pageKey = typeof body?.data?.pageKey === "string" && body.data.pageKey ? body.data.pageKey : undefined;
      if (!pageKey) break;
    }
    return out;
  }

  // Fallback when Alchemy is not configured or fails: Enso's wallet balances.
  private async ensoHoldings(network: WalletNetwork, address: Address): Promise<Holding[]> {
    const rows = await this.api.get("wallet/balances", { chainId: String(chainIds[network]), eoaAddress: address, useEoa: "true" });
    return (Array.isArray(rows) ? rows : []).flatMap((b: any) => {
      const raw = typeof b?.token === "string" ? b.token.toLowerCase() : "";
      const token = raw === "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee" ? NATIVE : isAddress(raw) ? raw : null;
      const decimals = Number(b?.decimals);
      if (!token || !/^\d{1,78}$/.test(String(b?.amount)) || BigInt(String(b.amount)) === 0n || !Number.isInteger(decimals) || decimals < 0 || decimals > 36) return [];
      return [{ token, symbol: text(b.symbol, 30), decimals, amount_raw: BigInt(String(b.amount)), price: positive(Number(b?.price)) }];
    });
  }

  // Enso DeFi metadata per token, shared by every user: a position is asked
  // again after 5 minutes, and a token that is not one (spam, plain ERC-20)
  // is remembered for 6 hours.
  private async defiTokens(network: WalletNetwork, tokens: string[]) {
    const chainId = String(chainIds[network]);
    const keyOf = (t: string) => `${chainId}:${t}`;
    const fresh = (t: string) => { const hit = this.defi.get(keyOf(t)); return !!hit && this.now() - hit.at < (hit.data ? 300_000 : 6 * 3600_000); };
    const missing = [...new Set(tokens)].filter(t => !fresh(t));
    for (let i = 0; i < missing.length; i += 50) {
      const batch = missing.slice(i, i + 50);
      const r = await this.api.get("tokens", { chainId, type: "defi", includeMetadata: "true", address: batch.map(t => getAddress(t)) }) as { data?: unknown };
      const found = new Map((Array.isArray(r?.data) ? r.data as DefiToken[] : []).filter(x => typeof x?.address === "string").map(x => [x.address.toLowerCase(), x]));
      for (const t of batch) this.defi.set(keyOf(t), { at: this.now(), data: found.get(t) ?? null });
    }
    while (this.defi.size > 5_000) this.defi.delete(this.defi.keys().next().value!);
    return new Map(tokens.flatMap(t => { const d = this.defi.get(keyOf(t))?.data; return d ? [[t, d] as const] : []; }));
  }

  private async position(network: WalletNetwork, token: Address, h: Holding, d: DefiToken, key: string | null, prices: Map<string, number>) {
    const underlying: Underlying[] = (Array.isArray(d.underlyingTokens) ? d.underlyingTokens : []).slice(0, 8).filter((u: any) => typeof u?.address === "string" && isAddress(u.address)).map((u: any) => ({ token: getAddress(u.address), symbol: text(u.symbol, 30), decimals: Number.isInteger(u.decimals) ? u.decimals as number : null }));
    const out: Record<string, unknown> & { price_usd: number | null; tvl_usd: number | null; apy: number | null } = {
      protocol: text(d.protocol ?? d.protocolSlug, 64), primary_address: typeof d.primaryAddress === "string" && isAddress(d.primaryAddress) ? getAddress(d.primaryAddress) : null,
      apy: num(d.apy), apy_base: num(d.apyBase), apy_reward: num(d.apyReward), tvl_usd: num(d.tvl), apy_source: num(d.apy) === null ? null : "enso", underlying, price_usd: null,
    };
    const info = (t: Address) => underlying.find(u => u.token === t);
    const priceOf = async (t: Address) => prices.get(t.toLowerCase()) ?? await this.alchemyPrice(key, network, t);
    if (/^(aerodrome|velodrome)/.test(String(out.protocol))) {
      try {
        const s = await this.cached(`pool:${network}:${token}`, 60_000, () => this.poolStats(network, token)) as Pool;
        const part = (t: Address, reserve: bigint) => { const raw = s.supply > 0n ? reserve * h.amount_raw / s.supply : 0n, dd = info(t)?.decimals ?? null; return { token: t, symbol: info(t)?.symbol ?? null, amount: dd === null ? null : Number(raw) / 10 ** dd, amount_raw: raw.toString() }; };
        out.composition = [part(s.token0, s.reserve0), part(s.token1, s.reserve1)];
        const [p0, p1] = await Promise.all([priceOf(s.token0), priceOf(s.token1)]);
        const [d0, d1] = [info(s.token0)?.decimals ?? null, info(s.token1)?.decimals ?? null];
        if (p0 !== null && p1 !== null && d0 !== null && d1 !== null && s.supply > 0n) {
          const tvl = Number(s.reserve0) / 10 ** d0 * p0 + Number(s.reserve1) / 10 ** d1 * p1;
          out.price_usd = tvl / (Number(s.supply) / 10 ** h.decimals);
          out.tvl_usd ??= round(tvl);
        } else if (h.price === null) out.price_error = "no price for the pool's tokens";
        if (out.apy === null) {
          if (s.stable) out.apy_error = "stable or unknown pool curve: fee APR is not estimated (reserves may not be 50/50 in value)";
          else if (s.feeApr === null) out.apy_error = "the pool's fee index one day ago could not be read";
          else Object.assign(out, { apy: s.feeApr, apy_base: s.feeApr, apy_reward: null, apy_source: "onchain_fee_index_24h", apy_note: "trading fees of the last ~24h annualised, paid to LP that is not staked in a gauge; no reward emissions included" });
        }
      } catch {
        out.apy_error ??= "pool data could not be read on-chain";
        if (h.price === null) out.price_error = "pool data could not be read on-chain";
      }
      return out;
    }
    if (h.price === null) {
      // ERC-4626 shares: the assets one share redeems for, at the asset's price.
      try {
        const rpc = this.wallets.rpc(network);
        const [assets, asset] = await Promise.all([rpc.readContract({ address: token, abi: vaultAbi, functionName: "convertToAssets", args: [10n ** BigInt(h.decimals)] }), rpc.readContract({ address: token, abi: vaultAbi, functionName: "asset" })]);
        const ad = info(getAddress(asset))?.decimals ?? null, ap = await priceOf(getAddress(asset));
        if (ad !== null && ap !== null) out.price_usd = Number(assets) / 10 ** ad * ap;
        else out.price_error = "no price for the vault's asset";
      } catch { out.price_error = "not priced: not an ERC-4626 vault or a supported pool"; }
    }
    return out;
  }

  // The price of an underlying token the account does not hold itself.
  private async alchemyPrice(key: string | null, network: WalletNetwork, token: Address) {
    if (!key) return null;
    const v = await this.cached(`price:${network}:${token.toLowerCase()}`, 60_000, async () => {
      const res = await this.fetcher(`https://api.g.alchemy.com/prices/v1/${key}/tokens/by-address`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ addresses: [{ network: ALCHEMY_NETWORK[network], address: token }] }), signal: AbortSignal.timeout(10_000) });
      if (!res.ok) return null;
      const b = await res.json() as { data?: any[] };
      return positive(Number((b?.data?.[0]?.prices ?? []).find((x: any) => x?.currency === "usd")?.value));
    }).catch(() => null);
    return typeof v === "number" ? v : null;
  }

  private async poolStats(network: WalletNetwork, pool: Address) {
    const rpc = this.wallets.rpc(network);
    const read = <T>(functionName: "getReserves" | "totalSupply" | "token0" | "token1" | "stable" | "POOL_TYPE" | "index0" | "index1", blockNumber?: bigint) => rpc.readContract({ address: pool, abi: poolAbi, functionName, ...(blockNumber === undefined ? {} : { blockNumber }) }) as Promise<T>;
    // Classic v2 pools answer stable(); MetaDEX pools name their curve in
    // POOL_TYPE() ("V2_VOLATILE", "V2_STABLE"). Unknown counts as stable, so
    // no 50/50 fee estimate is made for it.
    const curve = read<boolean>("stable").catch(() => read<Hex>("POOL_TYPE").then(t => !hexToString(t, { size: 32 }).includes("VOLATILE"), () => true));
    const head = await rpc.getBlockNumber(), dayAgo = head - BLOCKS_PER_DAY[network];
    const [[reserve0, reserve1], supply, token0, token1, stable] = await Promise.all([read<readonly [bigint, bigint, bigint]>("getReserves", head), read<bigint>("totalSupply", head), read<Address>("token0"), read<Address>("token1"), curve]);
    let feeApr: number | null = null;
    if (!stable && reserve0 > 0n && reserve1 > 0n && supply > 0n) {
      // index0/index1 accumulate fees per LP token (scaled 1e18). One day of
      // their growth, as a share of the reserves one LP token holds, is the
      // day's fee yield; both halves hold equal value in an x*y=k pool.
      const indexes = await Promise.all([read<bigint>("index0", head), read<bigint>("index1", head), read<bigint>("index0", dayAgo), read<bigint>("index1", dayAgo)]).catch(() => null);
      if (indexes) {
        const [i0, i1, p0, p1] = indexes;
        const perLp = (grown: bigint, reserve: bigint) => Number(grown) / 1e18 / (Number(reserve) / Number(supply));
        feeApr = Math.round((perLp(i0 - p0, reserve0) + perLp(i1 - p1, reserve1)) / 2 * 365 * 100 * 100) / 100;
      }
    }
    return { reserve0, reserve1, supply, token0: getAddress(token0), token1: getAddress(token1), stable, feeApr };
  }

  private async cached(key: string, ttl: number, load: () => Promise<unknown>) {
    const hit = this.cache.get(key);
    if (hit && this.now() - hit.at < ttl) return hit.data;
    const data = await load();
    this.cache.set(key, { at: this.now(), data });
    while (this.cache.size > 2_000) this.cache.delete(this.cache.keys().next().value!);
    return data;
  }
}

// The key of an Alchemy RPC URL (https://<net>.g.alchemy.com/v2/<key>), which
// also authorises its Portfolio and Prices APIs.
export function alchemyKey(url: string | undefined) {
  const m = url?.match(/^https:\/\/[a-z0-9-]+\.g\.alchemy\.com\/v2\/([A-Za-z0-9_-]{8,128})\/?$/);
  return m ? m[1]! : null;
}

function num(x: unknown) { return typeof x === "number" && Number.isFinite(x) ? x : null; }
function positive(x: number) { return Number.isFinite(x) && x > 0 ? x : null; }
function round(x: number | null) { return x === null ? null : Math.round(x * 100) / 100; }
function text(x: unknown, max: number) { return typeof x === "string" ? x.replace(/[^\x20-\x7e]/g, "?").slice(0, max) : null; }
