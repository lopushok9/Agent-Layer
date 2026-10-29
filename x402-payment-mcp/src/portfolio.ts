import { getAddress, hexToString, isAddress, parseAbi, parseAbiItem, type Address, type Hex, type PublicClient } from "viem";
import { z } from "zod";
import type { EnsoApi } from "./enso-routes.js";
import { chainIds, walletNetwork, type WalletNetwork } from "./transaction-builder.js";

export const portfolioInput = z.strictObject({
  network: walletNetwork,
  min_value_usd: z.number().min(0).max(1_000_000).default(0.01).describe("Hide assets worth less than this (dust); their count is still reported"),
});

type Wallets = { account(userId: string): Promise<{ address: Address }>; rpc(network: WalletNetwork): PublicClient };
type Balance = { token?: unknown; amount?: unknown; decimals?: unknown; price?: unknown; symbol?: unknown; name?: unknown };
type DefiToken = Record<string, any>;

const NATIVE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
const BLOCKS_PER_DAY: Record<WalletNetwork, bigint> = { base: 43_200n, ethereum: 7_200n };
const LOG_CHUNK = 2_000n;
const poolAbi = parseAbi([
  "function getReserves() view returns (uint256, uint256, uint256)",
  "function totalSupply() view returns (uint256)",
  "function token0() view returns (address)",
  "function token1() view returns (address)",
  "function stable() view returns (bool)",
  "function POOL_TYPE() view returns (bytes32)",
]);
const feesEvent = parseAbiItem("event Fees(address indexed sender, uint256 amount0, uint256 amount1)");

// One read of what the account holds, what it is worth and what each DeFi
// position earns. Balances and prices come from Enso's wallet API, APY and
// TVL from its token metadata; a position Enso has no APY for gets a fee APR
// from the pool's own events when it is a volatile Aerodrome/Velodrome v2 pool.
// Unpriced and dust tokens are hidden by count only: airdropped spam names
// are attacker-chosen text and never reach the agent.
export class Portfolio {
  private cache = new Map<string, { at: number; data: unknown }>();
  constructor(private api: EnsoApi, private wallets: Wallets, private now: () => number = Date.now) {}

  async portfolio(userId: string, input: z.input<typeof portfolioInput>) {
    const p = portfolioInput.parse(input);
    const { address } = await this.wallets.account(userId);
    const chainId = String(chainIds[p.network]);
    const balances = await this.cached(`balances:${chainId}:${address}`, 30_000, () => this.api.get("wallet/balances", { chainId, eoaAddress: address, useEoa: "true" }));
    const rows = (Array.isArray(balances) ? balances as Balance[] : []).flatMap(b => {
      const token = typeof b?.token === "string" ? b.token.toLowerCase() : "";
      const decimals = Number(b?.decimals), price = Number(b?.price);
      if (!(token === NATIVE || isAddress(token)) || !/^\d{1,78}$/.test(String(b?.amount)) || !Number.isInteger(decimals) || decimals < 0 || decimals > 36) return [];
      const amount = Number(BigInt(String(b.amount))) / 10 ** decimals;
      const value = Number.isFinite(price) && price > 0 ? amount * price : null;
      return [{ token, symbol: text(b.symbol, 30), amount_raw: String(b.amount), decimals, amount, price_usd: value === null ? null : price, value_usd: value }];
    });
    const shown = rows.filter(r => r.value_usd !== null && r.value_usd >= p.min_value_usd);
    const hidden = rows.length - shown.length;
    const erc20 = shown.filter(r => r.token !== NATIVE).map(r => getAddress(r.token));
    const meta = erc20.length ? await this.cached(`defi:${chainId}:${erc20.join(",")}`, 300_000, () => this.api.get("tokens", { chainId, type: "defi", includeMetadata: "true", address: erc20 })) : { data: [] };
    const defi = new Map((Array.isArray((meta as { data?: unknown })?.data) ? (meta as { data: DefiToken[] }).data : []).filter(x => typeof x?.address === "string").map(x => [x.address.toLowerCase(), x]));
    const assets = await Promise.all(shown.map(async r => {
      const d = defi.get(r.token);
      const base = { token: r.token === NATIVE ? "native" : getAddress(r.token), symbol: r.symbol, amount: r.amount, amount_raw: r.amount_raw, price_usd: r.price_usd, value_usd: round(r.value_usd) };
      return d ? { ...base, position: await this.position(p.network, getAddress(r.token), BigInt(r.amount_raw), r.decimals, r.price_usd, d) } : base;
    }));
    assets.sort((a, b) => (b.value_usd ?? 0) - (a.value_usd ?? 0));
    return {
      network: p.network, address,
      total_value_usd: round(shown.reduce((s, r) => s + (r.value_usd ?? 0), 0)),
      asset_count: assets.length, position_count: assets.filter(a => "position" in a).length,
      hidden_asset_count: hidden, hidden_reason: `no price, or worth less than $${p.min_value_usd}; names of hidden tokens are not shown (airdropped tokens are often spam)`,
      assets,
      trust: "Balances, prices, APY and TVL are Enso data; fee APR is estimated by this server from one day of pool events. Informational, not advice; past fees do not predict future ones.",
    };
  }

  private async position(network: WalletNetwork, token: Address, held: bigint, decimals: number, price: number | null, d: DefiToken) {
    const enso = { protocol: text(d.protocol ?? d.protocolSlug, 64), primary_address: typeof d.primaryAddress === "string" && isAddress(d.primaryAddress) ? getAddress(d.primaryAddress) : null, apy: num(d.apy), apy_base: num(d.apyBase), apy_reward: num(d.apyReward), tvl_usd: num(d.tvl), apy_source: num(d.apy) === null ? null : "enso" as string | null };
    const underlying = (Array.isArray(d.underlyingTokens) ? d.underlyingTokens : []).slice(0, 8).filter((u: any) => typeof u?.address === "string" && isAddress(u.address)).map((u: any) => ({ token: getAddress(u.address), symbol: text(u.symbol, 30), decimals: Number.isInteger(u.decimals) ? u.decimals as number : null }));
    if (!/^(aerodrome|velodrome)/.test(enso.protocol ?? "")) return { ...enso, underlying };
    // A v2 pool: the holding's share of each reserve, and a fee APR when Enso has none.
    try {
      const pool = await this.cached(`pool:${network}:${token}`, enso.apy === null ? 1_800_000 : 60_000, () => this.poolStats(network, token, enso.apy === null));
      const s = pool as Awaited<ReturnType<Portfolio["poolStats"]>>;
      const part = (t: Address, reserve: bigint) => {
        const raw = s.supply > 0n ? reserve * held / s.supply : 0n, u = underlying.find((x: { token: Address }) => x.token === t);
        return { token: t, symbol: u?.symbol ?? null, amount: u?.decimals == null ? null : Number(raw) / 10 ** u.decimals, amount_raw: raw.toString() };
      };
      const composition = [part(s.token0, s.reserve0), part(s.token1, s.reserve1)];
      // Enso prices the LP token even when it has no TVL for the pool.
      if (enso.tvl_usd === null && price !== null) enso.tvl_usd = round(price * Number(s.supply) / 10 ** decimals);
      if (enso.apy !== null) return { ...enso, underlying, composition };
      if (s.stable) return { ...enso, underlying, composition, apy_error: "stable or unknown pool curve: fee APR is not estimated (reserves may not be 50/50 in value)" };
      return { ...enso, underlying, composition, apy: s.feeApr, apy_base: s.feeApr, apy_reward: null, apy_source: "onchain_fees_24h", apy_note: "trading fees of the last ~24h annualised, paid to LP that is not staked in a gauge; no reward emissions included" };
    } catch {
      return { ...enso, underlying, apy_error: "pool data could not be read on-chain" };
    }
  }

  private async poolStats(network: WalletNetwork, pool: Address, withFees: boolean) {
    const rpc = this.wallets.rpc(network);
    const read = <T>(functionName: "getReserves" | "totalSupply" | "token0" | "token1" | "stable" | "POOL_TYPE") => rpc.readContract({ address: pool, abi: poolAbi, functionName }) as Promise<T>;
    // Classic v2 pools answer stable(); MetaDEX pools name their curve in
    // POOL_TYPE() ("V2_VOLATILE", "V2_STABLE"). Unknown counts as stable, so
    // no 50/50 fee estimate is made for it.
    const curve = read<boolean>("stable").catch(() => read<Hex>("POOL_TYPE").then(t => !hexToString(t, { size: 32 }).includes("VOLATILE"), () => true));
    const [[reserve0, reserve1], supply, token0, token1, stable] = await Promise.all([read<readonly [bigint, bigint, bigint]>("getReserves"), read<bigint>("totalSupply"), read<Address>("token0"), read<Address>("token1"), curve]);
    let feeApr: number | null = null;
    if (withFees && !stable && reserve0 > 0n && reserve1 > 0n) {
      const head = await rpc.getBlockNumber();
      let f0 = 0n, f1 = 0n;
      for (let from = head - BLOCKS_PER_DAY[network] + 1n; from <= head; from += LOG_CHUNK) {
        const to = from + LOG_CHUNK - 1n > head ? head : from + LOG_CHUNK - 1n;
        for (const l of await rpc.getLogs({ address: pool, event: feesEvent, fromBlock: from, toBlock: to })) { f0 += l.args.amount0 ?? 0n; f1 += l.args.amount1 ?? 0n; }
      }
      // In a volatile x*y=k pool both reserves hold half the value, so a fee
      // amount's share of its own reserve, halved, is its share of TVL.
      const daily = (Number(f0) / Number(reserve0) + Number(f1) / Number(reserve1)) / 2;
      feeApr = Math.round(daily * 365 * 100 * 100) / 100;
    }
    return { reserve0, reserve1, supply, token0: getAddress(token0), token1: getAddress(token1), stable, feeApr };
  }

  private async cached(key: string, ttl: number, load: () => Promise<unknown>) {
    const hit = this.cache.get(key);
    if (hit && this.now() - hit.at < ttl) return hit.data;
    const data = await load();
    this.cache.set(key, { at: this.now(), data });
    if (this.cache.size > 500) this.cache.delete(this.cache.keys().next().value!);
    return data;
  }
}

function num(x: unknown) { return typeof x === "number" && Number.isFinite(x) ? x : null; }
function round(x: number | null) { return x === null ? null : Math.round(x * 100) / 100; }
function text(x: unknown, max: number) { return typeof x === "string" ? x.replace(/[^\x20-\x7e]/g, "?").slice(0, max) : null; }
