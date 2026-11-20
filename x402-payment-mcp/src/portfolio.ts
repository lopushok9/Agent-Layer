import { getAddress, hexToString, isAddress, parseAbi, type Address, type Hex, type PublicClient } from "viem";
import { z } from "zod";
import type { EnsoApi } from "./enso-routes.js";
import { depositedShareTokens, WalletHistory, type History } from "./history.js";
import { PositionScanner, type Scan } from "./positions.js";
import { chainIds, walletNetwork, type WalletNetwork } from "./transaction-builder.js";

export const portfolioInput = z.strictObject({
  network: walletNetwork,
  min_value_usd: z.number().min(0).max(1_000_000).default(0.01).describe("Hide assets worth less than this (dust); their count is still reported"),
});

type Fetch = typeof fetch;
type Wallets = { account(userId: string): Promise<{ address: Address }>; rpc(network: WalletNetwork): PublicClient };
type DefiToken = Record<string, any>;
type Holding = { token: string; symbol: string | null; decimals: number; amount_raw: bigint; price: number | null; staked?: { gauge: Address; reward: unknown } };
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
const erc20Abi = parseAbi(["function balanceOf(address) view returns (uint256)", "function symbol() view returns (string)", "function decimals() view returns (uint8)"]);
// Vaults that balance indexes and Enso do not cover consistently: always read
// on-chain, with a protocol label. Other vaults are found from the account's
// transfer history (see discover).
const CURATED: Record<WalletNetwork, Record<string, string>> = {
  base: { "0x23574154842bc86cf5bbc5f99376cfa1e2f82497": "peapods-finance" },
  ethereum: {},
};
const MAX_DISCOVERED = 30;
// A DEX price is used only for a token whose pools hold at least this much.
const MIN_DEX_LIQUIDITY_USD = 10_000;
const GECKO_NETWORK: Record<WalletNetwork, string> = { base: "base", ethereum: "eth" };
const WETH_BASE = getAddress("0x4200000000000000000000000000000000000006");
const MORPHO_QUERY = `query Portfolio($address: String!, $chainId: Int!) { userByAddress(address: $address, chainId: $chainId) { marketPositions { market { marketId lltv loanAsset { address symbol decimals } collateralAsset { address symbol decimals } state { borrowApy } } state { supplyAssets supplyAssetsUsd borrowAssets borrowAssetsUsd collateral collateralUsd } } } }`;

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
  private scanner: PositionScanner;
  constructor(private api: EnsoApi, private wallets: Wallets, private rpcUrl: (network: WalletNetwork) => string | undefined, private fetcher: Fetch = fetch, private now: () => number = Date.now, private history: WalletHistory = new WalletHistory(wallets, rpcUrl, fetcher, now)) { this.scanner = new PositionScanner(network => this.wallets.rpc(network), (k, ttl, load) => this.cached(k, ttl, load)); }

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
    let history: History | null = null;
    const historyErrors: string[] = [];
    if (this.history.available(p.network)) {
      try { history = await this.history.load(p.network, address); }
      catch { historyErrors.push("Transfer history unavailable: positions found from it (vaults outside Enso, liquidity NFTs, gauge stakes, unrecognised contracts) may be missing"); }
    }
    const found = await this.discover(p.network, address, holdings, history);
    holdings = found.holdings;
    const prices = new Map(holdings.filter(h => h.price !== null).map(h => [h.token, h.price!]));
    if (p.network === "base" && prices.has(NATIVE) && !prices.has(WETH_BASE.toLowerCase())) prices.set(WETH_BASE.toLowerCase(), prices.get(NATIVE)!);
    if (prices.has(NATIVE)) prices.set("0x0000000000000000000000000000000000000000", prices.get(NATIVE)!);
    const dex = new Map<string, { price: number; liquidity_usd: number }>();
    const priceOf = async (t: Address) => {
      const k = t.toLowerCase();
      const known = prices.get(k) ?? await this.alchemyPrice(key, p.network, t);
      if (known !== null) return known;
      const d = (await this.dexPrices(p.network, [k])).get(k);
      if (d) dex.set(k, d);
      return d?.price ?? null;
    };
    const scan: Scan = await this.scanner.scan(p.network, address, history, priceOf);
    // LP staked in a gauge is held by the gauge; it is shown like a held LP.
    for (const st of scan.staked) {
      const meta = await this.scanner.token(p.network, st.pool).catch(() => null);
      if (meta) holdings.push({ token: st.pool.toLowerCase(), symbol: meta.symbol, decimals: meta.decimals, amount_raw: st.amount_raw, price: null, staked: { gauge: st.gauge, reward: st.reward } });
    }
    // Aave debt tokens are liabilities (in lending.aave_v3), not assets.
    const debtRows = holdings.filter(h => scan.debtTokens.has(h.token)).length;
    holdings = holdings.filter(h => !scan.debtTokens.has(h.token));
    const meta = await this.defiTokens(p.network, holdings.filter(h => h.token !== NATIVE).map(h => h.token));
    for (const token of found.candidates) {
      if (meta.has(token) || !holdings.some(h => h.token === token)) continue;
      const vault = await this.vaultMeta(p.network, token);
      if (vault) meta.set(token, vault);
    }
    for (const st of scan.staked) {
      const k = st.pool.toLowerCase();
      if (!meta.has(k)) { const lp = await this.lpMeta(p.network, st.pool).catch(() => null); if (lp) meta.set(k, lp); }
    }
    // Plain tokens without an index price: a DEX price when the token's pools
    // are deep enough, else they stay unpriced (and hidden as likely spam).
    const unpriced = holdings.filter(h => h.price === null && h.token !== NATIVE && !meta.has(h.token) && !scan.tokenUnderlying.has(h.token)).map(h => h.token);
    for (const [k, v] of await this.dexPrices(p.network, unpriced)) dex.set(k, v);
    const morphoApi = await this.morphoPositions(p.network, address).catch(() => null);
    const morpho = morphoApi ?? (history ? await this.scanner.morphoOnchain(p.network, address, priceOf).catch(() => null) : null);
    const rows = await Promise.all(holdings.map(async h => {
      const d = meta.get(h.token);
      const amount = Number(h.amount_raw) / 10 ** h.decimals;
      const base = { token: h.token === NATIVE ? NATIVE : getAddress(h.token), symbol: h.symbol, amount, amount_raw: h.amount_raw.toString(), ...(h.staked ? { staked_in_gauge: h.staked.gauge, pending_reward: h.staked.reward } : {}) };
      const underlying = scan.tokenUnderlying.get(h.token);
      if (!d && h.price === null && underlying) {
        const up = await priceOf(underlying);
        return { ...base, price_usd: up, value_usd: up === null ? null : round(amount * up), defi: true, price_source: "underlying asset 1:1 (lending receipt token)" };
      }
      if (!d) {
        const dx = h.price === null ? dex.get(h.token) : undefined;
        const price = h.price ?? dx?.price ?? null;
        return { ...base, price_usd: price, value_usd: price === null ? null : round(amount * price), defi: false, ...(dx ? { price_source: "dex", dex_liquidity_usd: Math.round(dx.liquidity_usd) } : {}) };
      }
      const { price_usd: computed, ...position } = await this.position(p.network, getAddress(h.token), h, d, key, prices, priceOf);
      const price = h.price ?? computed;
      return { ...base, price_usd: price, value_usd: price === null ? null : round(amount * price), defi: true, position };
    }));
    // A DeFi position stays visible without a price (its price_error says why);
    // anything else needs a price at or above the dust threshold.
    const shown = rows.filter(r => r.value_usd === null ? r.defi : r.value_usd >= p.min_value_usd);
    shown.sort((a, b) => (b.value_usd ?? -1) - (a.value_usd ?? -1));
    const discoveryErrors = [...historyErrors, ...found.errors, ...scan.errors];
    const walletTotal = shown.reduce((s, r) => s + (r.value_usd ?? 0), 0);
    // Totals: wallet assets (incl. receipt tokens and gauge-staked LP) plus
    // value held outside the wallet, minus debt. Unknown values make them
    // incomplete rather than wrong.
    const parts: { usd: number | null; debt?: boolean }[] = [
      ...(morpho ?? []).flatMap(m => [{ usd: m.supply > 0 ? m.supply_usd : 0 }, { usd: m.collateral > 0 ? m.collateral_usd : 0 }, { usd: m.borrow > 0 ? m.borrow_usd : 0, debt: true }]),
      ...scan.compound.flatMap(c => [{ usd: c.collateral_usd }, { usd: c.borrow > 0 ? c.borrow_usd : 0, debt: true }]),
      ...(scan.aave ? [{ usd: scan.aave.debt_usd, debt: true }] : []),
      ...scan.liquidity.flatMap(l => [{ usd: l.value_usd }, { usd: l.fees_usd ?? 0 }]),
    ];
    const outside = parts.filter(x => !x.debt), debts = parts.filter(x => x.debt);
    const sum = (xs: typeof parts) => xs.some(x => x.usd === null) ? null : xs.reduce((s, x) => s + x.usd!, 0);
    const outsideUsd = sum(outside), debtUsd = sum(debts);
    const totalsComplete = morpho !== null && discoveryErrors.length === 0 && shown.every(r => r.value_usd !== null) && outsideUsd !== null && debtUsd !== null;
    return {
      network: p.network, address,
      total_value_usd: round(walletTotal),
      asset_count: shown.length, position_count: shown.filter(r => r.defi).length,
      hidden_asset_count: rows.length - shown.length,
      hidden_reason: `no price and not a DeFi position, or worth less than $${p.min_value_usd}; names of hidden tokens are not shown (airdropped tokens are often spam)`,
      assets: shown.map(({ defi: _, ...r }) => r),
      morpho_market_positions: morpho,
      lending: { aave_v3: scan.aave, compound_v3: scan.compound },
      liquidity_positions: scan.liquidity,
      unrecognized_interactions: scan.unrecognized,
      ...(debtRows ? { debt_tokens_note: `${debtRows} Aave debt token(s) are shown as debt under lending.aave_v3, not as assets` } : {}),
      defi_errors: [...discoveryErrors, ...(morpho === null ? ["Morpho market positions unavailable"] : [])],
      defi_totals: { held_outside_wallet_usd: outsideUsd === null ? null : round(outsideUsd), debt_usd: debtUsd === null ? null : round(debtUsd), net_portfolio_usd: totalsComplete ? round(walletTotal + outsideUsd! - debtUsd!) : null, complete: totalsComplete, note: "total_value_usd is the wallet (including lending receipt tokens and gauge-staked LP). held_outside_wallet_usd adds Morpho supply and collateral, Compound collateral and liquidity NFTs with their fees; debt is Morpho, Aave and Compound borrowing. unrecognized_interactions and hidden assets are not included." },
      sources: { balances_and_prices: source, positions: "enso; ERC-4626 vaults from transfer history and curated vaults; Aave v3, Compound v3, Uniswap v3/v4 and Aerodrome Slipstream position NFTs, Aerodrome gauge stakes, read on-chain", morpho_markets: morphoApi ? "Morpho API" : "Morpho Blue events and state, read on-chain", position_prices: "on-chain (pool reserves and prices, ERC-4626 convertToAssets); a token without an index price may be priced from a DEX (GeckoTerminal) when its pools hold at least $" + MIN_DEX_LIQUIDITY_USD.toLocaleString("en-US") + ", or at a pool's own rate inside an LP position" },
      trust: "Balances, prices, APY and TVL are third-party data; fee APR is estimated by this server from one day of the pool's fee index. Informational, not advice; past fees do not predict future ones.",
    };
  }

  // Share tokens balance indexes and Enso may miss: those minted to the
  // account in one of its own deposits (from its transfer history), plus the
  // curated vaults. Their balances are read on-chain; a curated vault's
  // on-chain balance replaces whatever the index reported.
  private async discover(network: WalletNetwork, address: Address, holdings: Holding[], history: History | null) {
    const errors: string[] = [];
    const minted = history ? depositedShareTokens(history) : [];
    const curated = Object.keys(CURATED[network]);
    const candidates = [...new Set([...curated, ...minted])].slice(0, MAX_DISCOVERED);
    const rpc = this.wallets.rpc(network);
    const read = await Promise.all(candidates.map(async token => {
      if (!curated.includes(token) && holdings.some(h => h.token === token)) return null;
      const a = getAddress(token);
      try {
        const balance = await rpc.readContract({ address: a, abi: erc20Abi, functionName: "balanceOf", args: [address] });
        if (balance === 0n) return { token, holding: null };
        const [symbol, decimals] = await Promise.all([rpc.readContract({ address: a, abi: erc20Abi, functionName: "symbol" }).catch(() => null), rpc.readContract({ address: a, abi: erc20Abi, functionName: "decimals" })]);
        const d = Number(decimals);
        return { token, holding: Number.isInteger(d) && d >= 0 && d <= 36 ? { token, symbol: text(symbol, 30), decimals: d, amount_raw: balance, price: null } as Holding : null };
      } catch {
        errors.push(`Vault balance could not be read: ${a}`);
        return null;
      }
    }));
    const replaced = new Set(read.flatMap(r => r ? [r.token] : []));
    return {
      holdings: [...holdings.filter(h => !replaced.has(h.token)), ...read.flatMap(r => r?.holding ? [r.holding] : [])],
      candidates, errors,
    };
  }

  // ERC-4626 metadata for a found share token, read on-chain and cached per
  // token for an hour; null when it is not a vault (it stays a plain token).
  private async vaultMeta(network: WalletNetwork, token: string) {
    const meta = await this.cached(`vault:${network}:${token}`, 3600_000, async () => {
      const rpc = this.wallets.rpc(network);
      try {
        const asset = getAddress(await rpc.readContract({ address: getAddress(token), abi: vaultAbi, functionName: "asset" }));
        const [symbol, decimals] = await Promise.all([rpc.readContract({ address: asset, abi: erc20Abi, functionName: "symbol" }).catch(() => null), rpc.readContract({ address: asset, abi: erc20Abi, functionName: "decimals" })]);
        const label = CURATED[network][token];
        return { protocol: label ?? null, primaryAddress: getAddress(token), underlyingTokens: [{ address: asset, symbol: text(symbol, 30), decimals: Number(decimals) }], discovered: label ? "curated" : "transfer_history" };
      } catch { return null; }
    });
    return meta as DefiToken | null;
  }

  private async morphoPositions(network: WalletNetwork, address: Address) {
    const data = await this.cached(`morpho:${network}:${address}`, 30_000, async () => {
      const res = await this.fetcher("https://api.morpho.org/graphql", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query: MORPHO_QUERY, variables: { address, chainId: chainIds[network] } }), signal: AbortSignal.timeout(10_000) });
      if (!res.ok) throw new Error("Morpho API unavailable");
      const body = await res.json() as any;
      const positions = body?.data?.userByAddress?.marketPositions;
      if (body?.errors || !Array.isArray(positions)) throw new Error("Invalid Morpho response");
      return positions;
    }) as any[];
    if (data.length > 500) throw new Error("Too many Morpho positions");
    return data.map(row => {
      const m = row?.market, s = row?.state;
      const asset = (a: any) => {
        if (!isAddress(a?.address ?? "") || !Number.isInteger(a?.decimals) || a.decimals < 0 || a.decimals > 36) throw new Error("Invalid Morpho asset");
        return { token: getAddress(a.address), symbol: text(a.symbol, 30), decimals: a.decimals as number };
      };
      const loan = asset(m?.loanAsset), collateralAsset = asset(m?.collateralAsset);
      const quantity = (v: unknown, decimals: number) => {
        if (!(typeof v === "number" && Number.isFinite(v) && v >= 0 && Number.isInteger(v)) && !/^\d{1,78}$/.test(String(v))) throw new Error("Invalid Morpho amount");
        return Number(v) / 10 ** decimals;
      };
      if (typeof m?.marketId !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(m.marketId)) throw new Error("Invalid Morpho market");
      const supply = quantity(s?.supplyAssets, loan.decimals), borrow = quantity(s?.borrowAssets, loan.decimals), collateral = quantity(s?.collateral, collateralAsset.decimals);
      const collateralUsd = num(s?.collateralUsd), borrowUsd = num(s?.borrowAssetsUsd);
      return { market_id: m.marketId, protocol: "morpho", loan_asset: loan, collateral_asset: collateralAsset, supply, supply_usd: num(s?.supplyAssetsUsd), collateral, collateral_usd: collateralUsd, borrow, borrow_usd: borrowUsd, borrow_apy_percent: num(m?.state?.borrowApy) === null ? null : m.state.borrowApy * 100, liquidation_ltv_percent: /^\d{1,20}$/.test(String(m?.lltv)) ? Number(m.lltv) / 1e16 : null, ltv_percent: collateralUsd !== null && collateralUsd > 0 && borrowUsd !== null ? borrowUsd / collateralUsd * 100 : null };
    }).filter(m => m.supply > 0 || m.borrow > 0 || m.collateral > 0);
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

  private async position(network: WalletNetwork, token: Address, h: Holding, d: DefiToken, key: string | null, prices: Map<string, number>, fallbackPrice?: (t: Address) => Promise<number | null>) {
    const underlying: Underlying[] = (Array.isArray(d.underlyingTokens) ? d.underlyingTokens : []).slice(0, 8).filter((u: any) => typeof u?.address === "string" && isAddress(u.address)).map((u: any) => ({ token: getAddress(u.address), symbol: text(u.symbol, 30), decimals: Number.isInteger(u.decimals) ? u.decimals as number : null }));
    const out: Record<string, unknown> & { price_usd: number | null; tvl_usd: number | null; apy: number | null } = {
      protocol: text(d.protocol ?? d.protocolSlug, 64), primary_address: typeof d.primaryAddress === "string" && isAddress(d.primaryAddress) ? getAddress(d.primaryAddress) : null,
      apy: num(d.apy), apy_base: num(d.apyBase), apy_reward: num(d.apyReward), tvl_usd: num(d.tvl), apy_source: num(d.apy) === null ? null : "enso", underlying, price_usd: null,
      ...(d.discovered === "transfer_history" || d.discovered === "curated" ? { discovered_by: d.discovered, discovery_note: "ERC-4626 vault outside Enso's index; value is the vault's own convertToAssets, APY unknown" } : {}),
    };
    const info = (t: Address) => underlying.find(u => u.token === t);
    const priceOf = async (t: Address) => prices.get(t.toLowerCase()) ?? await this.alchemyPrice(key, network, t) ?? (fallbackPrice ? await fallbackPrice(t) : null);
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
        } else if ((p0 === null) !== (p1 === null) && !s.stable && d0 !== null && d1 !== null && s.supply > 0n && s.reserve0 > 0n && s.reserve1 > 0n) {
          // One side priced, x*y=k pool: both halves hold equal value, so the
          // pool is worth twice its priced side (the other token is valued at
          // the pool's own rate).
          const known = p0 !== null ? Number(s.reserve0) / 10 ** d0 * p0 : Number(s.reserve1) / 10 ** d1 * p1!;
          const tvl = 2 * known;
          out.price_usd = tvl / (Number(s.supply) / 10 ** h.decimals);
          out.tvl_usd ??= round(tvl);
          const unknown = p0 === null ? (info(s.token0)?.symbol ?? "token0") : (info(s.token1)?.symbol ?? "token1");
          Object.assign(out, { price_source: `${unknown} valued at the pool's own rate`, price_note: tvl < MIN_DEX_LIQUIDITY_USD ? `thin pool (about $${round(tvl)}): this value may not be realisable` : "derived from this pool's reserves; a thin pool can be far from the market" });
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

  // Pool metadata for a gauge-staked Aerodrome LP that Enso does not index.
  private async lpMeta(network: WalletNetwork, pool: Address): Promise<DefiToken | null> {
    const rpc = this.wallets.rpc(network);
    const [t0, t1] = await Promise.all([rpc.readContract({ address: pool, abi: poolAbi, functionName: "token0" }), rpc.readContract({ address: pool, abi: poolAbi, functionName: "token1" })]);
    const [a, b] = await Promise.all([this.scanner.token(network, getAddress(t0)), this.scanner.token(network, getAddress(t1))]);
    return { protocol: "aerodrome", primaryAddress: pool, underlyingTokens: [{ address: a.token, symbol: a.symbol, decimals: a.decimals }, { address: b.token, symbol: b.symbol, decimals: b.decimals }] };
  }

  // DEX prices from GeckoTerminal, kept only for tokens whose pools hold at
  // least MIN_DEX_LIQUIDITY_USD (a token with a shallow pool can be given any
  // price). Shared by all users for 5 minutes; failures mean no price.
  private async dexPrices(network: WalletNetwork, tokens: string[]) {
    const out = new Map<string, { price: number; liquidity_usd: number }>();
    const missing: string[] = [];
    for (const t of new Set(tokens)) {
      const hit = this.cache.get(`dex:${network}:${t}`);
      if (hit && this.now() - hit.at < 300_000) { if (hit.data) out.set(t, hit.data as { price: number; liquidity_usd: number }); }
      else missing.push(t);
    }
    for (let i = 0; i < Math.min(missing.length, 90); i += 30) {
      const batch = missing.slice(i, i + 30);
      try {
        const res = await this.fetcher(`https://api.geckoterminal.com/api/v2/networks/${GECKO_NETWORK[network]}/tokens/multi/${batch.join(",")}`, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(8_000) });
        if (!res.ok) break;
        const body = await res.json() as { data?: any[] };
        const found = new Map<string, { price: number; liquidity_usd: number }>();
        for (const row of Array.isArray(body?.data) ? body.data : []) {
          const a = row?.attributes, addr = typeof a?.address === "string" ? a.address.toLowerCase() : "";
          const price = positive(Number(a?.price_usd)), liquidity = Number(a?.total_reserve_in_usd);
          if (isAddress(addr) && price !== null && Number.isFinite(liquidity) && liquidity >= MIN_DEX_LIQUIDITY_USD) found.set(addr, { price, liquidity_usd: liquidity });
        }
        for (const t of batch) { const v = found.get(t) ?? null; this.cache.set(`dex:${network}:${t}`, { at: this.now(), data: v }); if (v) out.set(t, v); }
      } catch { break; }
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
