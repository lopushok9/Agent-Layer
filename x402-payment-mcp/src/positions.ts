import { encodeAbiParameters, getAddress, isAddress, keccak256, pad, parseAbi, parseAbiItem, parseAbiParameters, toHex, type Address, type Hex, type PublicClient } from "viem";
import { ENTRYPOINTS, ZERO, type History } from "./history.js";
import type { WalletNetwork } from "./transaction-builder.js";
import { v4PositionManagers } from "./uniswap-v4-constants.js";

// Positions that are not a token in the wallet, found from what the account
// has done (its transfer history) and from a few protocols checked directly,
// then read on-chain. Every address below was checked on-chain (factory,
// pool manager, base token or provider answers) when it was added.
//
// - Lending: Aave v3 (account data and per-reserve balances), Compound v3
//   (borrow and collateral), Morpho Blue read from its own events when the
//   Morpho API is down.
// - Liquidity: concentrated-liquidity NFTs (Uniswap v3 and forks such as
//   Aerodrome Slipstream, Uniswap v4), owned or staked in an Aerodrome gauge;
//   Aerodrome v2 LP staked in a gauge.
// - Anything else the account sent tokens to without getting anything back in
//   the same transaction is listed as unrecognised, not silently dropped.

const AAVE_PROVIDER: Record<WalletNetwork, Address> = { base: "0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D", ethereum: "0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e" };
const COMETS: Record<WalletNetwork, Address[]> = {
  base: ["0xb125E6687d4313864e53df431d5425969c15Eb2F", "0x46e6b214b524310239732D51387075E0e70970bf", "0x784efeB622244d2348d4F2522f8860B96fbEcE89", "0x9c4ec768c28520B50860ea7a15bd7213a9fF58bf"],
  ethereum: ["0xc3d688B66703497DAA19211EEdff47f25384cdc3", "0xA17581A9E3356d9A858b789D68B4d866e593aE94", "0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840"],
};
export const MORPHO_BLUE: Address = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb";
const AERODROME_VOTER: Partial<Record<WalletNetwork, Address>> = { base: "0x16613524e02ad97eDfeF371bC883F2F5d6C480A5" };
const STATE_VIEW: Record<WalletNetwork, Address> = { base: "0xa3c0c9b65bad0b08107aa264b0f3db444b867a71", ethereum: "0x7ffe42c4a5deea5b0fec41c94c136cf115597227" };
const NPM_LABELS: Record<WalletNetwork, Record<string, string>> = {
  base: { "0x03a520b32c04bf3beef7beb72e919cf822ed34f1": "uniswap-v3", "0x827922686190790b37229fd06084350e74485b72": "aerodrome-slipstream" },
  ethereum: { "0xc36442b4a4522e871399cd717abdd847ab11fe88": "uniswap-v3" },
};
const MAX_CANDIDATES = 40, MAX_NFTS = 40, MAX_UNRECOGNIZED = 10;
const Q128 = 1n << 128n, U256 = (1n << 256n) - 1n, U128 = (1n << 128n) - 1n;

const erc20 = parseAbi(["function balanceOf(address) view returns (uint256)", "function symbol() view returns (string)", "function decimals() view returns (uint8)"]);
const aaveProviderAbi = parseAbi(["function getPool() view returns (address)", "function getPoolDataProvider() view returns (address)"]);
const aavePoolAbi = parseAbi(["function getUserAccountData(address) view returns (uint256 totalCollateralBase, uint256 totalDebtBase, uint256 availableBorrowsBase, uint256 currentLiquidationThreshold, uint256 ltv, uint256 healthFactor)"]);
const aaveDataAbi = parseAbi([
  "struct TokenData { string symbol; address tokenAddress; }",
  "function getAllReservesTokens() view returns (TokenData[])",
  "function getAllATokens() view returns (TokenData[])",
  "function getUserReserveData(address asset, address user) view returns (uint256 currentATokenBalance, uint256 currentStableDebt, uint256 currentVariableDebt, uint256 principalStableDebt, uint256 scaledVariableDebt, uint256 stableBorrowRate, uint256 liquidityRate, uint40 stableRateLastUpdated, bool usageAsCollateralEnabled)",
  "function getReserveTokensAddresses(address asset) view returns (address aTokenAddress, address stableDebtTokenAddress, address variableDebtTokenAddress)",
  "function getReserveData(address asset) view returns (uint256 unbacked, uint256 accruedToTreasuryScaled, uint256 totalAToken, uint256 totalStableDebt, uint256 totalVariableDebt, uint256 liquidityRate, uint256 variableBorrowRate, uint256 stableBorrowRate, uint256 averageStableBorrowRate, uint256 liquidityIndex, uint256 variableBorrowIndex, uint40 lastUpdateTimestamp)",
]);
const cometAbi = parseAbi([
  "struct AssetInfo { uint8 offset; address asset; address priceFeed; uint64 scale; uint64 borrowCollateralFactor; uint64 liquidateCollateralFactor; uint64 liquidationFactor; uint128 supplyCap; }",
  "function baseToken() view returns (address)", "function balanceOf(address) view returns (uint256)", "function borrowBalanceOf(address) view returns (uint256)",
  "function numAssets() view returns (uint8)", "function getAssetInfo(uint8 i) view returns (AssetInfo)", "function userCollateral(address, address) view returns (uint128 balance, uint128 reserved)",
]);
const morphoAbi = parseAbi([
  "function position(bytes32 id, address user) view returns (uint256 supplyShares, uint128 borrowShares, uint128 collateral)",
  "function market(bytes32 id) view returns (uint128 totalSupplyAssets, uint128 totalSupplyShares, uint128 totalBorrowAssets, uint128 totalBorrowShares, uint128 lastUpdate, uint128 fee)",
  "function idToMarketParams(bytes32 id) view returns (address loanToken, address collateralToken, address oracle, address irm, uint256 lltv)",
]);
const morphoEvents = [parseAbiItem("event SupplyCollateral(bytes32 indexed id, address indexed caller, address indexed onBehalf, uint256 assets)"), parseAbiItem("event Supply(bytes32 indexed id, address indexed caller, address indexed onBehalf, uint256 assets, uint256 shares)")];
const voterAbi = parseAbi(["function isGauge(address) view returns (bool)"]);
const gaugeAbi = parseAbi(["function stakingToken() view returns (address)", "function balanceOf(address) view returns (uint256)", "function earned(address) view returns (uint256)", "function rewardToken() view returns (address)", "function stakedContains(address depositor, uint256 tokenId) view returns (bool)", "function earned(address account, uint256 tokenId) view returns (uint256)"]);
const npmAbi = parseAbi([
  "function positions(uint256 tokenId) view returns (uint96 nonce, address operator, address token0, address token1, int24 feeOrTickSpacing, int24 tickLower, int24 tickUpper, uint128 liquidity, uint256 feeGrowthInside0LastX128, uint256 feeGrowthInside1LastX128, uint128 tokensOwed0, uint128 tokensOwed1)",
  "function factory() view returns (address)", "function ownerOf(uint256) view returns (address)",
  "struct CollectParams { uint256 tokenId; address recipient; uint128 amount0Max; uint128 amount1Max; }",
  "function collect(CollectParams params) payable returns (uint256 amount0, uint256 amount1)",
]);
const v3FactoryAbi = parseAbi(["function getPool(address, address, uint24) view returns (address)"]);
const clFactoryAbi = parseAbi(["function getPool(address, address, int24) view returns (address)"]);
const slot0Abi = parseAbi(["function slot0() view returns (uint160 sqrtPriceX96, int24 tick)"]);
const v4PmAbi = parseAbi([
  "struct PoolKey { address currency0; address currency1; uint24 fee; int24 tickSpacing; address hooks; }",
  "function getPoolAndPositionInfo(uint256 tokenId) view returns (PoolKey, uint256)", "function getPositionLiquidity(uint256 tokenId) view returns (uint128)", "function ownerOf(uint256) view returns (address)",
]);
const stateViewAbi = parseAbi([
  "function getSlot0(bytes32 poolId) view returns (uint160 sqrtPriceX96, int24 tick, uint24 protocolFee, uint24 lpFee)",
  "function getPositionInfo(bytes32 poolId, address owner, int24 tickLower, int24 tickUpper, bytes32 salt) view returns (uint128 liquidity, uint256 feeGrowthInside0LastX128, uint256 feeGrowthInside1LastX128)",
  "function getFeeGrowthInside(bytes32 poolId, int24 tickLower, int24 tickUpper) view returns (uint256 feeGrowthInside0X128, uint256 feeGrowthInside1X128)",
]);

export type Token = { token: Address; symbol: string | null; decimals: number };
export type Amount = Token & { amount: number; usd: number | null };
type Price = (token: Address) => Promise<number | null>;
type Cached = (key: string, ttl: number, load: () => Promise<unknown>) => Promise<unknown>;

export type StakedLp = { pool: Address; gauge: Address; amount_raw: bigint; reward: Amount | null };
export type Scan = Awaited<ReturnType<PositionScanner["scan"]>>;

export class PositionScanner {
  constructor(private rpc: (network: WalletNetwork) => PublicClient, private cached: Cached) {}

  async scan(network: WalletNetwork, account: Address, history: History | null, price: Price) {
    const errors: string[] = [];
    const guard = async <T>(label: string, run: () => Promise<T>, fallback: T) => { try { return await run(); } catch { errors.push(`${label} could not be read`); return fallback; } };
    const sentTo = history ? interactedContracts(history) : new Set<string>();
    // With the full history, a protocol the account never touched is skipped:
    // an Aave position always moved an aToken, a Comet position always moved
    // tokens to, from or of the Comet. A partial or missing history checks all.
    const seen = history?.complete ? touchedAddresses(history) : null;
    const [aave, compound, liquidity, staked] = await Promise.all([
      guard("Aave v3 position", () => this.aave(network, account, price, seen), null),
      guard("Compound v3 positions", () => this.compound(network, account, sentTo, price, seen), []),
      history ? guard("Liquidity position NFTs", () => this.liquidityNfts(network, account, history, price), []) : Promise.resolve([]),
      history ? guard("Gauge-staked LP", () => this.stakedLp(network, account, sentTo, price), []) : Promise.resolve([]),
    ]);
    const recognised = new Set<string>([MORPHO_BLUE.toLowerCase(), ...COMETS[network].map(a => a.toLowerCase()), ...(aave ? [aave.pool.toLowerCase()] : []), ...staked.map(s => s.gauge.toLowerCase()), ...liquidity.flatMap(l => l.staked_in_gauge ? [l.staked_in_gauge.toLowerCase()] : [])]);
    const unrecognized = history ? await guard("Other interactions", () => this.unrecognized(network, history, recognised), []) : [];
    // Tokens the wallet holds whose value is defined by these protocols: an
    // aToken or a Comet balance is worth its underlying 1:1; a debt token is
    // a liability, never an asset.
    const tokenUnderlying = new Map<string, Address>(), debtTokens = new Set<string>();
    for (const r of aave?.reserves ?? []) { tokenUnderlying.set(r.a_token.toLowerCase(), r.asset.token); for (const d of r.debt_tokens) debtTokens.add(d.toLowerCase()); }
    for (const c of compound) tokenUnderlying.set(c.comet.toLowerCase(), c.base_asset.token);
    return { aave: roundUsd(aave), compound: roundUsd(compound), liquidity: roundUsd(liquidity), staked, unrecognized, tokenUnderlying, debtTokens, errors, history_complete: history?.complete ?? false };
  }

  // Morpho Blue positions from the account's own SupplyCollateral and Supply
  // events, read on-chain: the fallback when the Morpho API is unavailable.
  async morphoOnchain(network: WalletNetwork, account: Address, price: Price) {
    const rpc = this.rpc(network);
    const logs = await Promise.all(morphoEvents.map(event => rpc.getLogs({ address: MORPHO_BLUE, event, args: { onBehalf: account }, fromBlock: 0n, toBlock: "latest" })));
    const ids = [...new Set(logs.flat().map(l => (l as { args: { id?: Hex } }).args.id).filter((id): id is Hex => typeof id === "string"))].slice(0, 50);
    const rows = await Promise.all(ids.map(async id => {
      const [[supplyShares, borrowShares, collateral], m, params] = await Promise.all([
        rpc.readContract({ address: MORPHO_BLUE, abi: morphoAbi, functionName: "position", args: [id, account] }),
        rpc.readContract({ address: MORPHO_BLUE, abi: morphoAbi, functionName: "market", args: [id] }),
        rpc.readContract({ address: MORPHO_BLUE, abi: morphoAbi, functionName: "idToMarketParams", args: [id] }),
      ]);
      if (supplyShares === 0n && borrowShares === 0n && collateral === 0n) return null;
      const [loan, coll] = await Promise.all([this.token(network, params[0]), this.token(network, params[1])]);
      // SharesMathLib: virtual 1 asset and 1e6 shares; borrow rounds up.
      const supplyRaw = supplyShares * (m[0] + 1n) / (m[1] + 1_000_000n);
      const borrowRaw = (borrowShares * (m[2] + 1n) + m[3] + 1_000_000n - 1n) / (m[3] + 1_000_000n);
      const [lp, cp] = await Promise.all([price(loan.token), price(coll.token)]);
      const supply = units(supplyRaw, loan.decimals), borrow = units(borrowRaw, loan.decimals), coll_ = units(collateral, coll.decimals);
      const collateralUsd = cp === null ? null : coll_ * cp, borrowUsd = lp === null ? null : borrow * lp;
      return { market_id: id, protocol: "morpho", loan_asset: loan, collateral_asset: coll, supply, supply_usd: lp === null ? null : supply * lp, collateral: coll_, collateral_usd: collateralUsd, borrow, borrow_usd: borrowUsd, borrow_apy_percent: null, liquidation_ltv_percent: Number(params[4]) / 1e16, ltv_percent: collateralUsd && borrowUsd !== null ? borrowUsd / collateralUsd * 100 : null, source: "onchain_events" };
    }));
    return roundUsd(rows.filter(r => r !== null));
  }

  private async aave(network: WalletNetwork, account: Address, price: Price, seen: Set<string> | null) {
    const rpc = this.rpc(network);
    const { pool, data } = await this.cached(`aave:${network}`, 3600_000, async () => {
      const [pool, data] = await Promise.all([rpc.readContract({ address: AAVE_PROVIDER[network], abi: aaveProviderAbi, functionName: "getPool" }), rpc.readContract({ address: AAVE_PROVIDER[network], abi: aaveProviderAbi, functionName: "getPoolDataProvider" })]);
      return { pool: getAddress(pool), data: getAddress(data) };
    }) as { pool: Address; data: Address };
    if (seen) {
      const aTokens = await this.cached(`aave-atokens:${network}`, 3600_000, async () => (await rpc.readContract({ address: data, abi: aaveDataAbi, functionName: "getAllATokens" })).map(t => t.tokenAddress.toLowerCase())) as string[];
      if (!aTokens.some(t => seen.has(t))) return null;
    }
    const [collateralBase, debtBase, availableBase, liqThreshold, ltv, health] = await rpc.readContract({ address: pool, abi: aavePoolAbi, functionName: "getUserAccountData", args: [account] });
    if (collateralBase === 0n && debtBase === 0n) return null;
    const reserves = await this.cached(`aave-reserves:${network}`, 3600_000, async () => (await rpc.readContract({ address: data, abi: aaveDataAbi, functionName: "getAllReservesTokens" })).map(r => getAddress(r.tokenAddress))) as Address[];
    const user = await rpc.multicall({ contracts: reserves.map(asset => ({ address: data, abi: aaveDataAbi, functionName: "getUserReserveData", args: [asset, account] }) as const), allowFailure: true });
    const held = reserves.flatMap((asset, i) => { const r = user[i]; if (r?.status !== "success") return []; const [a, sd, vd, , , , liquidityRate, , useAsCollateral] = r.result as readonly [bigint, bigint, bigint, bigint, bigint, bigint, bigint, number, boolean]; return a > 0n || sd > 0n || vd > 0n ? [{ asset, a, debt: sd + vd, liquidityRate, useAsCollateral }] : []; });
    const rows = await Promise.all(held.map(async h => {
      const [token, addrs, reserve, p] = await Promise.all([
        this.token(network, h.asset),
        this.cached(`aave-tokens:${network}:${h.asset}`, 3600_000, () => rpc.readContract({ address: data, abi: aaveDataAbi, functionName: "getReserveTokensAddresses", args: [h.asset] })) as Promise<readonly [Address, Address, Address]>,
        rpc.readContract({ address: data, abi: aaveDataAbi, functionName: "getReserveData", args: [h.asset] }),
        price(h.asset),
      ]);
      const supplied = units(h.a, token.decimals), borrowed = units(h.debt, token.decimals);
      return { asset: token, a_token: getAddress(addrs[0]), debt_tokens: [addrs[1], addrs[2]].filter(a => a !== ZERO).map(a => getAddress(a)), supplied, supplied_usd: p === null ? null : supplied * p, borrowed, borrowed_usd: p === null ? null : borrowed * p, used_as_collateral: h.useAsCollateral, supply_apr_percent: rayPercent(h.liquidityRate), borrow_apr_percent: h.debt > 0n ? rayPercent(reserve[6]) : null };
    }));
    return {
      protocol: "aave-v3", pool,
      collateral_usd: Number(collateralBase) / 1e8, debt_usd: Number(debtBase) / 1e8, available_to_borrow_usd: Number(availableBase) / 1e8,
      health_factor: debtBase === 0n ? null : Number(health) / 1e18, liquidation_threshold_percent: Number(liqThreshold) / 100, max_ltv_percent: Number(ltv) / 100,
      health_note: "Liquidation is possible when the health factor falls below 1.",
      reserves: rows,
    };
  }

  private async compound(network: WalletNetwork, account: Address, sentTo: Set<string>, price: Price, seen: Set<string> | null) {
    const rpc = this.rpc(network), comets = COMETS[network].filter(c => !seen || seen.has(c.toLowerCase()));
    if (comets.length === 0) return [];
    const balances = await rpc.multicall({ contracts: comets.flatMap(c => [{ address: c, abi: cometAbi, functionName: "balanceOf", args: [account] }, { address: c, abi: cometAbi, functionName: "borrowBalanceOf", args: [account] }] as const), allowFailure: true });
    const out = await Promise.all(comets.map(async (comet, i) => {
      const supplyRaw = balances[2 * i]?.status === "success" ? balances[2 * i]!.result as bigint : 0n, borrowRaw = balances[2 * i + 1]?.status === "success" ? balances[2 * i + 1]!.result as bigint : 0n;
      // Collateral alone is not a balance: look for it where the account
      // borrowed or ever sent tokens.
      if (supplyRaw === 0n && borrowRaw === 0n && !sentTo.has(comet.toLowerCase())) return null;
      const baseAsset = await this.cached(`comet-base:${comet}`, 86_400_000, async () => getAddress(await rpc.readContract({ address: comet, abi: cometAbi, functionName: "baseToken" }))) as Address;
      const assets = await this.cached(`comet-assets:${comet}`, 3600_000, async () => {
        const n = Number(await rpc.readContract({ address: comet, abi: cometAbi, functionName: "numAssets" }));
        const info = await rpc.multicall({ contracts: Array.from({ length: Math.min(n, 30) }, (_, k) => ({ address: comet, abi: cometAbi, functionName: "getAssetInfo", args: [k] }) as const), allowFailure: false });
        return info.map(a => ({ asset: getAddress(a.asset), liquidate: Number(a.liquidateCollateralFactor) / 1e18 }));
      }) as { asset: Address; liquidate: number }[];
      const coll = await rpc.multicall({ contracts: assets.map(a => ({ address: comet, abi: cometAbi, functionName: "userCollateral", args: [account, a.asset] }) as const), allowFailure: true });
      const collateral = (await Promise.all(assets.map(async (a, k) => {
        const r = coll[k]; const bal = r?.status === "success" ? (r.result as readonly [bigint, bigint])[0] : 0n;
        if (bal === 0n) return null;
        const t = await this.token(network, a.asset), p = await price(a.asset), amount = units(bal, t.decimals);
        return { ...t, amount, usd: p === null ? null : amount * p, liquidation_factor: a.liquidate };
      }))).filter(x => x !== null);
      if (supplyRaw === 0n && borrowRaw === 0n && collateral.length === 0) return null;
      const base = await this.token(network, baseAsset), bp = await price(baseAsset);
      const supply = units(supplyRaw, base.decimals), borrow = units(borrowRaw, base.decimals);
      const collateralUsd = collateral.some(c => c.usd === null) ? null : collateral.reduce((s, c) => s + c.usd!, 0);
      const limit = collateral.some(c => c.usd === null) ? null : collateral.reduce((s, c) => s + c.usd! * c.liquidation_factor, 0);
      const borrowUsd = bp === null ? null : borrow * bp;
      return { protocol: "compound-v3", comet, base_asset: base, supply, supply_usd: bp === null ? null : supply * bp, supply_note: "the Comet token in the wallet is this supply", borrow, borrow_usd: borrowUsd, collateral, collateral_usd: collateralUsd, liquidation_risk_percent: borrowUsd !== null && limit ? borrowUsd / limit * 100 : null };
    }));
    return out.filter(x => x !== null);
  }

  // Aerodrome v2 LP the account moved into a gauge: the gauge holds it, so
  // it is not in the wallet balance.
  private async stakedLp(network: WalletNetwork, account: Address, sentTo: Set<string>, price: Price): Promise<StakedLp[]> {
    const voter = AERODROME_VOTER[network];
    if (!voter) return [];
    const rpc = this.rpc(network), candidates = [...sentTo].slice(0, MAX_CANDIDATES).map(a => getAddress(a));
    const isGauge = await rpc.multicall({ contracts: candidates.map(c => ({ address: voter, abi: voterAbi, functionName: "isGauge", args: [c] }) as const), allowFailure: true });
    const gauges = candidates.filter((_, i) => isGauge[i]?.status === "success" && isGauge[i]!.result === true);
    const out = await Promise.all(gauges.map(async gauge => {
      const [lp, bal] = await Promise.all([rpc.readContract({ address: gauge, abi: gaugeAbi, functionName: "stakingToken" }).catch(() => null), rpc.readContract({ address: gauge, abi: gaugeAbi, functionName: "balanceOf", args: [account] }).catch(() => 0n)]);
      if (!lp || bal === 0n) return null;
      return { pool: getAddress(lp), gauge, amount_raw: bal, reward: await this.reward(network, gauge, () => rpc.readContract({ address: gauge, abi: gaugeAbi, functionName: "earned", args: [account] }), price) };
    }));
    return out.filter(x => x !== null);
  }

  // Concentrated-liquidity position NFTs the account received: Uniswap v3
  // style managers (any that answer positions()), and Uniswap v4.
  private async liquidityNfts(network: WalletNetwork, account: Address, history: History, price: Price) {
    const me = account.toLowerCase(), seen = new Set<string>(), nfts: { contract: Address; id: bigint }[] = [];
    for (const t of history.transfers) {
      if (t.category !== "erc721" || t.to !== me || t.token_id === null || !/^\d{1,78}$/.test(t.token_id)) continue;
      const key = `${t.token}:${t.token_id}`;
      if (seen.has(key)) continue;
      seen.add(key); nfts.push({ contract: getAddress(t.token), id: BigInt(t.token_id) });
      if (nfts.length >= MAX_NFTS) break;
    }
    const v4 = v4PositionManagers[network].toLowerCase();
    const rows = await Promise.all(nfts.map(n => (n.contract.toLowerCase() === v4 ? this.v4Position(network, account, n.contract, n.id, price) : this.v3Position(network, account, n.contract, n.id, price)).catch(() => null)));
    return rows.filter(r => r !== null);
  }

  private async holder(network: WalletNetwork, account: Address, nft: Address, id: bigint) {
    const rpc = this.rpc(network), owner = getAddress(await rpc.readContract({ address: nft, abi: npmAbi, functionName: "ownerOf", args: [id] }));
    if (owner === account) return { owner, gauge: null };
    const voter = AERODROME_VOTER[network];
    if (!voter || !await rpc.readContract({ address: voter, abi: voterAbi, functionName: "isGauge", args: [owner] }).catch(() => false)) return null;
    return await rpc.readContract({ address: owner, abi: gaugeAbi, functionName: "stakedContains", args: [account, id] }).catch(() => false) ? { owner, gauge: owner } : null;
  }

  private async v3Position(network: WalletNetwork, account: Address, npm: Address, id: bigint, price: Price) {
    const rpc = this.rpc(network);
    const p = await rpc.readContract({ address: npm, abi: npmAbi, functionName: "positions", args: [id] });
    const [, , t0, t1, feeOrSpacing, tickLower, tickUpper, liquidity, , , owed0, owed1] = p;
    if (liquidity === 0n && owed0 === 0n && owed1 === 0n) return null;
    const holder = await this.holder(network, account, npm, id);
    if (!holder) return null;
    const pool = await this.cached(`clpool:${npm}:${t0}:${t1}:${feeOrSpacing}`, 86_400_000, async () => {
      const factory = getAddress(await rpc.readContract({ address: npm, abi: npmAbi, functionName: "factory" }));
      const v3 = await rpc.readContract({ address: factory, abi: v3FactoryAbi, functionName: "getPool", args: [t0, t1, feeOrSpacing] }).catch(() => ZERO as Address);
      if (v3 !== ZERO) return getAddress(v3);
      const cl = await rpc.readContract({ address: factory, abi: clFactoryAbi, functionName: "getPool", args: [t0, t1, feeOrSpacing] });
      if (cl === ZERO) throw new Error("pool not found");
      return getAddress(cl);
    }) as Address;
    const [sqrtPriceX96, tick] = await rpc.readContract({ address: pool, abi: slot0Abi, functionName: "slot0" });
    // Fees owed to an unstaked position: what collect would return now (the
    // manager updates fees first), simulated as the owner.
    let fees: readonly [bigint, bigint] | null = null;
    if (!holder.gauge) fees = (await rpc.simulateContract({ address: npm, abi: npmAbi, functionName: "collect", args: [{ tokenId: id, recipient: account, amount0Max: U128, amount1Max: U128 }], account }).catch(() => null))?.result ?? [owed0, owed1];
    const reward = holder.gauge ? await this.reward(network, holder.gauge, () => rpc.readContract({ address: holder.gauge!, abi: gaugeAbi, functionName: "earned", args: [account, id] }), price) : null;
    return this.clRow(network, { protocol: NPM_LABELS[network][npm.toLowerCase()] ?? "uniswap-v3-style", npm, id, pool, t0, t1, sqrtPriceX96, tick, tickLower, tickUpper, liquidity, fees, gauge: holder.gauge, reward, feeTier: NPM_LABELS[network][npm.toLowerCase()] === "aerodrome-slipstream" ? { tick_spacing: feeOrSpacing } : { fee_percent: feeOrSpacing / 10_000 } }, price);
  }

  private async v4Position(network: WalletNetwork, account: Address, pm: Address, id: bigint, price: Price) {
    const rpc = this.rpc(network), view = STATE_VIEW[network];
    const [owner, [key, info], liquidity] = await Promise.all([
      rpc.readContract({ address: pm, abi: v4PmAbi, functionName: "ownerOf", args: [id] }),
      rpc.readContract({ address: pm, abi: v4PmAbi, functionName: "getPoolAndPositionInfo", args: [id] }),
      rpc.readContract({ address: pm, abi: v4PmAbi, functionName: "getPositionLiquidity", args: [id] }),
    ]);
    if (getAddress(owner) !== account || liquidity === 0n) return null;
    // PositionInfo: 200-bit pool id | int24 tickUpper | int24 tickLower | uint8 hasSubscriber.
    const int24 = (v: bigint) => { const x = Number(v & 0xffffffn); return x >= 0x800000 ? x - 0x1000000 : x; };
    const tickLower = int24(info >> 8n), tickUpper = int24(info >> 32n);
    const poolId = keccak256(encodeAbiParameters(parseAbiParameters("address,address,uint24,int24,address"), [key.currency0, key.currency1, key.fee, key.tickSpacing, key.hooks]));
    const salt = pad(toHex(id), { size: 32 });
    const [[sqrtPriceX96, tick], [, last0, last1], [now0, now1]] = await Promise.all([
      rpc.readContract({ address: view, abi: stateViewAbi, functionName: "getSlot0", args: [poolId] }),
      rpc.readContract({ address: view, abi: stateViewAbi, functionName: "getPositionInfo", args: [poolId, pm, tickLower, tickUpper, salt] }),
      rpc.readContract({ address: view, abi: stateViewAbi, functionName: "getFeeGrowthInside", args: [poolId, tickLower, tickUpper] }),
    ]);
    const fee = (now: bigint, last: bigint) => ((now - last) & U256) * liquidity / Q128;
    return this.clRow(network, { protocol: "uniswap-v4", npm: pm, id, pool: poolId, t0: key.currency0, t1: key.currency1, sqrtPriceX96, tick, tickLower, tickUpper, liquidity, fees: [fee(now0, last0), fee(now1, last1)], gauge: null, reward: null, feeTier: { fee_percent: key.fee / 10_000, hooks: key.hooks === ZERO ? null : getAddress(key.hooks) } }, price);
  }

  private async clRow(network: WalletNetwork, p: { protocol: string; npm: Address; id: bigint; pool: Address | Hex; t0: Address; t1: Address; sqrtPriceX96: bigint; tick: number; tickLower: number; tickUpper: number; liquidity: bigint; fees: readonly [bigint, bigint] | null; gauge: Address | null; reward: Amount | null; feeTier: Record<string, unknown> }, price: Price) {
    const [a, b] = await Promise.all([this.token(network, p.t0), this.token(network, p.t1)]);
    const [raw0, raw1] = clAmounts(p.liquidity, p.sqrtPriceX96, p.tickLower, p.tickUpper);
    let [p0, p1] = await Promise.all([price(a.token), price(b.token)]);
    // One side unpriced: value it at this pool's own exchange rate.
    const rate = (Number(p.sqrtPriceX96) / 2 ** 96) ** 2 * 10 ** (a.decimals - b.decimals); // token1 per token0
    let priceSource: string | null = null;
    if (p0 === null && p1 !== null && rate > 0) { p0 = rate * p1; priceSource = `${a.symbol ?? "token0"} valued at the pool's rate`; }
    else if (p1 === null && p0 !== null && rate > 0) { p1 = p0 / rate; priceSource = `${b.symbol ?? "token1"} valued at the pool's rate`; }
    const amt = (t: Token, raw: number, pr: number | null): Amount => { const amount = raw / 10 ** t.decimals; return { ...t, amount, usd: pr === null ? null : amount * pr }; };
    const amounts = [amt(a, raw0, p0), amt(b, raw1, p1)];
    const fees = p.fees ? [amt(a, Number(p.fees[0]), p0), amt(b, Number(p.fees[1]), p1)] : [];
    const sum = (xs: Amount[]) => xs.some(x => x.usd === null) ? null : xs.reduce((s, x) => s + x.usd!, 0);
    return {
      protocol: p.protocol, kind: "concentrated_liquidity", position_manager: p.npm, token_id: p.id.toString(), pool: p.pool, ...p.feeTier,
      in_range: p.tick >= p.tickLower && p.tick < p.tickUpper, tick_lower: p.tickLower, tick_upper: p.tickUpper, current_tick: p.tick,
      amounts, value_usd: sum(amounts), uncollected_fees: fees, fees_usd: p.fees ? sum(fees) : null,
      ...(p.gauge ? { staked_in_gauge: p.gauge, pending_reward: p.reward, fee_note: "a staked position earns gauge rewards instead of trading fees" } : {}),
      ...(priceSource ? { price_source: priceSource, price_note: "derived from this pool's price; a thin pool can be far from the market" } : {}),
    };
  }

  private async reward(network: WalletNetwork, gauge: Address, earned: () => Promise<bigint>, price: Price): Promise<Amount | null> {
    const rpc = this.rpc(network);
    const [token, raw] = await Promise.all([this.cached(`gauge-reward:${gauge}`, 86_400_000, async () => getAddress(await rpc.readContract({ address: gauge, abi: gaugeAbi, functionName: "rewardToken" }))) as Promise<Address>, earned()]).catch(() => [null, 0n] as const);
    if (!token) return null;
    const t = await this.token(network, token), p = await price(token), amount = units(raw, t.decimals);
    return { ...t, amount, usd: p === null ? null : amount * p };
  }

  // Contracts the account sent tokens to and got nothing back from in the same
  // transaction (a deposit shape), that no scanner above recognised.
  private async unrecognized(network: WalletNetwork, history: History, recognised: Set<string>) {
    const me = history.address, received = new Set(history.transfers.filter(t => t.to === me).map(t => t.hash));
    const latest = new Map<string, { to: string; token: string; symbol: string | null; time: string | null; hash: string }>();
    for (const t of history.transfers) {
      if (t.from !== me || t.to === me || t.to === ZERO || ENTRYPOINTS.has(t.to) || recognised.has(t.to) || received.has(t.hash) || t.category === "internal") continue;
      if (!latest.has(t.to)) latest.set(t.to, { to: t.to, token: t.token, symbol: t.symbol, time: t.time, hash: t.hash });
    }
    const rpc = this.rpc(network), rows = [...latest.values()].slice(0, MAX_CANDIDATES);
    const codes = await Promise.all(rows.map(r => this.cached(`code:${network}:${r.to}`, 86_400_000, async () => { const c = await rpc.getCode({ address: getAddress(r.to) }); return !!c && c !== "0x"; }).catch(() => false)));
    return rows.filter((_, i) => codes[i]).slice(0, MAX_UNRECOGNIZED).map(r => ({ contract: getAddress(r.to), last_sent: r.token === "native" ? "ETH" : r.symbol, last_sent_at: r.time, transaction_hash: r.hash }));
  }

  async token(network: WalletNetwork, address: Address): Promise<Token> {
    if (address === ZERO) return { token: ZERO as Address, symbol: "ETH", decimals: 18 };
    return await this.cached(`token:${network}:${address.toLowerCase()}`, 86_400_000, async () => {
      const rpc = this.rpc(network);
      const [symbol, decimals] = await Promise.all([rpc.readContract({ address, abi: erc20, functionName: "symbol" }).catch(() => null), rpc.readContract({ address, abi: erc20, functionName: "decimals" })]);
      const d = Number(decimals);
      if (!Number.isInteger(d) || d < 0 || d > 36) throw new Error("bad decimals");
      return { token: getAddress(address), symbol: typeof symbol === "string" ? symbol.replace(/[^\x20-\x7e]/g, "?").slice(0, 30) : null, decimals: d };
    }) as Token;
  }
}

// Addresses the account sent ERC-20 tokens to: candidates for gauges, Comets
// and other contracts that hold its funds.
export function interactedContracts(history: History) {
  return new Set(history.transfers.filter(t => t.from === history.address && t.category === "erc20" && t.to !== ZERO && isAddress(t.to) && !ENTRYPOINTS.has(t.to)).map(t => t.to));
}

// Every address in the account's history: tokens moved and both ends.
export function touchedAddresses(history: History) {
  return new Set(history.transfers.flatMap(t => [t.token, t.from, t.to]));
}

// Token amounts of concentrated liquidity L between two ticks at the current
// price (Uniswap v3 whitepaper 6.29/6.30), in raw units, as floats.
export function clAmounts(liquidity: bigint, sqrtPriceX96: bigint, tickLower: number, tickUpper: number): [number, number] {
  const L = Number(liquidity), s = Number(sqrtPriceX96) / 2 ** 96, a = 1.0001 ** (tickLower / 2), b = 1.0001 ** (tickUpper / 2);
  if (s <= a) return [L * (b - a) / (a * b), 0];
  if (s >= b) return [0, L * (b - a)];
  return [L * (b - s) / (s * b), L * (s - a)];
}

function units(raw: bigint, decimals: number) { return Number(raw) / 10 ** decimals; }
// Dollar values to 4 decimals (positions here are often dust; cents would
// show them as zero). Token amounts keep full precision.
function roundUsd<T>(v: T): T {
  if (Array.isArray(v)) return v.map(roundUsd) as T;
  if (!v || typeof v !== "object") return v;
  return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, typeof x === "number" && (k === "usd" || k.endsWith("_usd")) ? Math.round(x * 1e4) / 1e4 : roundUsd(x)])) as T;
}
function rayPercent(ray: bigint) { return Math.round(Number(ray) / 1e27 * 100 * 100) / 100; }
