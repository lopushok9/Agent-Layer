import assert from "node:assert/strict";
import test from "node:test";
import { encodeAbiParameters, getAddress, keccak256, parseAbiParameters } from "viem";
import { clAmounts, PositionScanner } from "../src/positions.js";

const me = getAddress("0xD09d6F783A9840E5Ca35E134912765dc11C895A1"), meLc = me.toLowerCase();
const weth = getAddress("0x4200000000000000000000000000000000000006"), usdc = getAddress("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913");
const npm = getAddress("0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1"), v4pm = getAddress("0x7c5f5a4bbd8fd63184577525326123b519429bdc");
const voter = getAddress("0x16613524e02ad97eDfeF371bC883F2F5d6C480A5"), aaveProvider = getAddress("0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D");
const cometUsdc = getAddress("0xb125E6687d4313864e53df431d5425969c15Eb2F"), morpho = getAddress("0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb");
const factory = getAddress("0x33128a8fC17869897dcE68Ed026d694621f6FDfD"), pool = getAddress("0x00000000000000000000000000000000000000a1");
const gauge = getAddress("0x00000000000000000000000000000000000000b1"), lp = getAddress("0x00000000000000000000000000000000000000c1");
const aavePool = getAddress("0x00000000000000000000000000000000000000d1"), aaveData = getAddress("0x00000000000000000000000000000000000000d2");
const aToken = getAddress("0x00000000000000000000000000000000000000e1"), vDebt = getAddress("0x00000000000000000000000000000000000000e2"), sDebt = getAddress("0x00000000000000000000000000000000000000e3");
const stranger = getAddress("0x00000000000000000000000000000000000000f1"), friend = getAddress("0x00000000000000000000000000000000000000f2");
const Q96 = 2n ** 96n;

type Handler = (args: readonly any[]) => unknown;
function mockRpc(table: Record<string, Handler | unknown>, extra: Record<string, unknown> = {}) {
  const readContract = async ({ address, functionName, args = [] }: any) => {
    const key = `${getAddress(address)}:${functionName}`;
    if (!(key in table)) throw new Error(`reverted ${key}`);
    const v = table[key];
    return typeof v === "function" ? (v as Handler)(args) : v;
  };
  return {
    readContract,
    multicall: async ({ contracts, allowFailure = true }: any) => allowFailure ? Promise.all(contracts.map((c: any) => readContract(c).then(result => ({ status: "success", result }), error => ({ status: "failure", error })))) : Promise.all(contracts.map(readContract)),
    getCode: async ({ address }: any) => [stranger, cometUsdc].includes(getAddress(address)) ? "0x60" : "0x",
    getLogs: async () => [],
    simulateContract: async () => { throw new Error("reverted"); },
    ...extra,
  };
}
const scanner = (rpc: any) => { const cache = new Map<string, unknown>(); return new PositionScanner(() => rpc, async (k, _ttl, load) => { if (!cache.has(k)) cache.set(k, await load()); return cache.get(k); }); };
const price = async (t: string) => ({ [weth.toLowerCase()]: 2000, [usdc.toLowerCase()]: 1 } as Record<string, number>)[t.toLowerCase()] ?? null;
const tokenMeta = { [`${weth}:symbol`]: "WETH", [`${weth}:decimals`]: 18, [`${usdc}:symbol`]: "USDC", [`${usdc}:decimals`]: 6 };
const aaveIdle = { [`${aaveProvider}:getPool`]: aavePool, [`${aaveProvider}:getPoolDataProvider`]: aaveData, [`${aavePool}:getUserAccountData`]: [0n, 0n, 0n, 0n, 0n, 0n], [`${aaveData}:getAllATokens`]: [{ symbol: "aWETH", tokenAddress: aToken }] };
const transfer = (hash: string, from: string, to: string, token: string, category = "erc20", token_id: string | null = null) => ({ id: `${hash}:${from}:${to}:${token_id}`, hash, block: 1, time: "2026-11-01T00:00:00.000Z", category, token: token.toLowerCase(), symbol: "T", decimals: 18, amount_raw: "1", token_id, from: from.toLowerCase(), to: to.toLowerCase() });
const history = (transfers: any[]) => ({ address: meLc, transfers, complete: true }) as any;

test("concentrated liquidity amounts follow the v3 formulas", () => {
  const L = 10n ** 18n;
  const [a0, a1] = clAmounts(L, Q96, -600, 600);
  assert.ok(Math.abs(a0 - a1) / a1 < 1e-9, "symmetric range at price 1 holds equal amounts");
  assert.ok(Math.abs(a1 - 1e18 * (1 - 1.0001 ** -300)) / a1 < 1e-9);
  assert.equal(clAmounts(L, Q96, 600, 1200)[1], 0, "below the range: all token0");
  assert.equal(clAmounts(L, Q96, -1200, -600)[0], 0, "above the range: all token1");
});

test("a Uniswap v3 NFT the account holds is valued with its uncollected fees", async () => {
  // Price 2000 USDC per WETH: sqrt(2000e6/1e18) x 2^96.
  const sqrtP = BigInt(Math.round(Math.sqrt(2000e6 / 1e18) * 2 ** 96));
  const rpc = mockRpc({
    ...aaveIdle, ...tokenMeta,
    [`${npm}:positions`]: [0n, me, weth, usdc, 500, -201000, -199000, 10n ** 15n, 0n, 0n, 0n, 0n],
    [`${npm}:ownerOf`]: me, [`${npm}:factory`]: factory, [`${factory}:getPool`]: pool, [`${pool}:slot0`]: [sqrtP, -200311],
  }, { simulateContract: async ({ functionName, account }: any) => { assert.equal(functionName, "collect"); assert.equal(account, me); return { result: [10n ** 15n, 2_000_000n] }; } });
  const s = await scanner(rpc).scan("base", me, history([transfer("0x01", "0x0000000000000000000000000000000000000000", me, npm, "erc721", "42")]), price);
  assert.deepEqual(s.errors, []);
  const [pos] = s.liquidity as any[];
  assert.deepEqual([pos.protocol, pos.token_id, pos.pool, pos.fee_percent, pos.in_range], ["uniswap-v3", "42", pool, 0.05, true]);
  const [weth_, usdc_] = pos.amounts;
  assert.ok(weth_.amount > 0 && usdc_.amount > 0, "in range: both tokens");
  assert.ok(Math.abs(pos.value_usd - (weth_.amount * 2000 + usdc_.amount)) < 1e-4, "value is the sum of both sides, to 4 decimals");
  assert.deepEqual(pos.uncollected_fees.map((f: any) => f.amount), [0.001, 2]);
  assert.equal(pos.fees_usd, 4);
});

test("an NFT the account sent away, or a closed position, is not reported", async () => {
  const rpc = mockRpc({ ...aaveIdle, ...tokenMeta, [`${npm}:positions`]: (a: readonly any[]) => a[0] === 1n ? [0n, me, weth, usdc, 500, -10, 10, 5n, 0n, 0n, 0n, 0n] : [0n, me, weth, usdc, 500, -10, 10, 0n, 0n, 0n, 0n, 0n], [`${npm}:ownerOf`]: friend, [`${voter}:isGauge`]: false });
  const s = await scanner(rpc).scan("base", me, history([transfer("0x01", friend, me, npm, "erc721", "1"), transfer("0x02", friend, me, npm, "erc721", "2")]), price);
  assert.deepEqual(s.liquidity, []);
});

test("a Uniswap v4 position decodes its ticks and fee growth", async () => {
  const key = { currency0: "0x0000000000000000000000000000000000000000", currency1: usdc, fee: 3000, tickSpacing: 60, hooks: "0x0000000000000000000000000000000000000000" };
  const enc = (t: number) => BigInt(t < 0 ? t + 0x1000000 : t);
  const info = (enc(-600) << 8n) | (enc(600) << 32n) | (123n << 56n);
  const poolId = keccak256(encodeAbiParameters(parseAbiParameters("address,address,uint24,int24,address"), [key.currency0 as `0x${string}`, key.currency1, key.fee, key.tickSpacing, key.hooks as `0x${string}`]));
  const stateView = getAddress("0xa3c0c9b65bad0b08107aa264b0f3db444b867a71");
  const seen: any[] = [];
  const rpc = mockRpc({
    ...aaveIdle, ...tokenMeta,
    [`${v4pm}:ownerOf`]: me, [`${v4pm}:getPoolAndPositionInfo`]: [key, info], [`${v4pm}:getPositionLiquidity`]: 10n ** 12n,
    [`${stateView}:getSlot0`]: (a: readonly any[]) => { seen.push(["slot0", a[0]]); return [Q96, 0, 0, 3000]; },
    [`${stateView}:getPositionInfo`]: (a: readonly any[]) => { seen.push(["info", ...a]); return [10n ** 12n, 0n, 0n]; },
    [`${stateView}:getFeeGrowthInside`]: [2n ** 128n * 5n, 2n ** 128n * 7n],
  });
  const s = await scanner(rpc).scan("base", me, history([transfer("0x03", "0x0000000000000000000000000000000000000000", me, v4pm, "erc721", "7")]), price);
  const [pos] = s.liquidity as any[];
  assert.deepEqual([pos.protocol, pos.tick_lower, pos.tick_upper, pos.in_range, pos.pool], ["uniswap-v4", -600, 600, true, poolId]);
  assert.deepEqual(seen.find(x => x[0] === "info").slice(2, 5), [v4pm, -600, 600], "the position is read under the manager with its ticks");
  assert.equal(seen.find(x => x[0] === "info")[5], `0x${"0".repeat(63)}7`, "salt is the token id");
  assert.deepEqual(pos.uncollected_fees.map((f: any) => f.amount), [5e12 / 1e18, 7e12 / 1e6]);
  assert.equal(pos.amounts[0].symbol, "ETH", "native currency");
});

test("Aave v3 debt is a liability; aTokens map to their asset", async () => {
  const rpc = mockRpc({
    ...tokenMeta,
    [`${aaveProvider}:getPool`]: aavePool, [`${aaveProvider}:getPoolDataProvider`]: aaveData,
    [`${aavePool}:getUserAccountData`]: [500n * 10n ** 8n, 200n * 10n ** 8n, 175n * 10n ** 8n, 8250n, 8000n, 2_062_500_000_000_000_000n],
    [`${aaveData}:getAllReservesTokens`]: [{ symbol: "WETH", tokenAddress: weth }, { symbol: "USDC", tokenAddress: usdc }],
    [`${aaveData}:getUserReserveData`]: (a: readonly any[]) => a[0] === weth ? [25n * 10n ** 16n, 0n, 0n, 0n, 0n, 0n, 2n * 10n ** 25n, 0, true] : [0n, 0n, 200n * 10n ** 6n, 0n, 0n, 0n, 0n, 0, false],
    [`${aaveData}:getReserveTokensAddresses`]: [aToken, sDebt, vDebt],
    [`${aaveData}:getReserveData`]: [0n, 0n, 0n, 0n, 0n, 0n, 5n * 10n ** 25n, 0n, 0n, 0n, 0n, 0],
  });
  const s = await scanner(rpc).scan("base", me, null, price);
  const a = s.aave!;
  assert.deepEqual([a.collateral_usd, a.debt_usd, a.health_factor, a.liquidation_threshold_percent], [500, 200, 2.0625, 82.5]);
  const [w, u] = a.reserves;
  assert.deepEqual([w!.supplied, w!.supplied_usd, w!.supply_apr_percent, w!.used_as_collateral], [0.25, 500, 2, true]);
  assert.deepEqual([u!.borrowed, u!.borrow_apr_percent], [200, 5]);
  assert.ok(s.debtTokens.has(vDebt.toLowerCase()) && s.debtTokens.has(sDebt.toLowerCase()));
  assert.equal(s.tokenUnderlying.get(aToken.toLowerCase()), usdc);
});

test("Compound v3 collateral is found where the account sent tokens, with its borrow", async () => {
  const rpc = mockRpc({
    ...aaveIdle, ...tokenMeta,
    [`${cometUsdc}:balanceOf`]: 0n, [`${cometUsdc}:borrowBalanceOf`]: 1_000n * 10n ** 6n, [`${cometUsdc}:baseToken`]: usdc, [`${cometUsdc}:numAssets`]: 1,
    [`${cometUsdc}:getAssetInfo`]: { offset: 0, asset: weth, priceFeed: weth, scale: 10n ** 18n, borrowCollateralFactor: 8n * 10n ** 17n, liquidateCollateralFactor: 85n * 10n ** 16n, liquidationFactor: 0n, supplyCap: 0n },
    [`${cometUsdc}:userCollateral`]: [10n ** 18n, 0n],
  });
  const s = await scanner(rpc).scan("base", me, history([transfer("0x04", me, cometUsdc, weth)]), price);
  assert.deepEqual(s.errors, []);
  const [c] = s.compound as any[];
  assert.deepEqual([c.borrow, c.borrow_usd, c.collateral[0].amount, c.collateral_usd], [1000, 1000, 1, 2000]);
  assert.equal(Math.round(c.liquidation_risk_percent * 100) / 100, 58.82, "1000 / (2000 x 0.85)");
  assert.deepEqual(s.unrecognized, [], "a recognised Comet is not listed as unknown");
});

test("LP staked in an Aerodrome gauge is reported with its reward", async () => {
  const aero = getAddress("0x940181a94A35A4569E4529A3CDfB74e38FD98631");
  const rpc = mockRpc({ ...aaveIdle, ...tokenMeta, [`${voter}:isGauge`]: (a: readonly any[]) => getAddress(a[0]) === gauge, [`${gauge}:stakingToken`]: lp, [`${gauge}:balanceOf`]: 5n * 10n ** 17n, [`${gauge}:rewardToken`]: aero, [`${gauge}:earned`]: 3n * 10n ** 18n, [`${aero}:symbol`]: "AERO", [`${aero}:decimals`]: 18 });
  const s = await scanner(rpc).scan("base", me, history([transfer("0x05", me, gauge, lp)]), price);
  assert.deepEqual(s.staked.map(x => [x.pool, x.gauge, x.amount_raw, x.reward?.amount, x.reward?.symbol]), [[lp, gauge, 5n * 10n ** 17n, 3, "AERO"]]);
  assert.deepEqual(s.unrecognized, []);
});

test("a deposit into an unknown contract is listed; swaps, payments to people and recognised contracts are not", async () => {
  const rpc = mockRpc({ ...aaveIdle, [`${voter}:isGauge`]: false });
  const s = await scanner(rpc).scan("base", me, history([
    transfer("0x06", me, stranger, usdc),
    transfer("0x07", me, getAddress("0x00000000000000000000000000000000000000f3"), usdc), transfer("0x07", getAddress("0x00000000000000000000000000000000000000f3"), me, weth),
    transfer("0x08", me, friend, usdc),
    transfer("0x09", me, morpho, usdc),
  ]), price);
  assert.deepEqual(s.unrecognized.map(u => u.contract), [stranger]);
});

test("Morpho positions are rebuilt from the account's events when the API is down", async () => {
  const id = `0x${"3b".repeat(32)}` as const;
  const rpc = mockRpc({
    ...tokenMeta,
    [`${morpho}:position`]: [0n, 30_438_774_552_661_768_333n, 101_314n],
    [`${morpho}:market`]: [16_271_334_674_266_714_356n, 15_709_328_996_855_364_414_929_457n, 2_340_714_869_260_418_192n, 2_247_044_823_296_541_596_906_528n, 0n, 0n],
    [`${morpho}:idToMarketParams`]: [weth, usdc, weth, weth, 860_000_000_000_000_000n],
  }, { getLogs: async ({ args }: any) => { assert.equal(args.onBehalf, me); return [{ args: { id } }]; } });
  const [m] = await scanner(rpc).morphoOnchain("base", me, price) as any[];
  assert.equal(m.market_id, id);
  assert.equal(m.collateral, 0.101314);
  assert.ok(Math.abs(m.borrow - 0.0000317076) < 1e-9, "borrow shares x total borrow assets / total borrow shares");
  assert.deepEqual([m.liquidation_ltv_percent, m.source], [86, "onchain_events"]);
});

test("with the full history, Aave and Comets the account never touched are not read", async () => {
  const calls: string[] = [];
  const rpc = mockRpc({ ...aaveIdle, [`${voter}:isGauge`]: false, [`${cometUsdc}:balanceOf`]: 0n, [`${cometUsdc}:borrowBalanceOf`]: 0n });
  const spy = { ...rpc, readContract: async (c: any) => { calls.push(`${getAddress(c.address)}:${c.functionName}`); return rpc.readContract(c); }, multicall: async (m: any) => { for (const c of m.contracts) calls.push(`${getAddress(c.address)}:${c.functionName}`); return rpc.multicall(m); } };
  const s = await scanner(spy).scan("base", me, history([transfer("0x06", friend, me, usdc)]), price);
  assert.deepEqual(s.errors, []);
  assert.ok(!calls.includes(`${aavePool}:getUserAccountData`) && !calls.some(c => c.startsWith(cometUsdc)), "no account reads");
  calls.length = 0;
  await scanner(spy).scan("base", me, history([transfer("0x07", "0x0000000000000000000000000000000000000000", me, aToken), transfer("0x08", me, cometUsdc, usdc)]), price);
  assert.ok(calls.includes(`${aavePool}:getUserAccountData`) && calls.includes(`${cometUsdc}:balanceOf`), "an aToken mint and a Comet deposit are read");
  calls.length = 0;
  await scanner(spy).scan("base", me, { ...history([]), complete: false }, price);
  assert.ok(calls.includes(`${aavePool}:getUserAccountData`) && calls.includes(`${cometUsdc}:balanceOf`), "a partial history checks everything");
});
