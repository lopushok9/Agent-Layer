import assert from "node:assert/strict";
import test from "node:test";
import { YieldSearch, rheaSupplyApy } from "../src/near/yields.js";

const USDC_NEAR = "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1";
const BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const BASE_WETH = "0x4200000000000000000000000000000000000006";
const AAVE_BASE = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5";
const VAULT = "0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61";

const RATE = { target_utilization: 8000, target_utilization_rate: "1000000000001847694955734069", max_utilization_rate: "1000000000012857214234867166", reserve_ratio: 2500 };
const LLAMA = [
  { chain: "Near", project: "rhea-lend", symbol: "USDC", pool: "p-rhea", underlyingTokens: [USDC_NEAR], apy: 10.1, apyBase: 10.1, tvlUsd: 1_900_000, stablecoin: true, ilRisk: "no", exposure: "single" },
  { chain: "Near", project: "rhea-lst", symbol: "RNEAR", pool: "p-lst", underlyingTokens: ["wrap.near"], apy: 4.4, apyBase: 4.4, tvlUsd: 66_000_000, stablecoin: false, ilRisk: "no", exposure: "single" },
  { chain: "Base", project: "aave-v3", symbol: "USDC", pool: "p-aave", underlyingTokens: [BASE_USDC], apy: 4.79, apyBase: 4.79, tvlUsd: 17_000_000, stablecoin: true, ilRisk: "no", exposure: "single" },
  { chain: "Base", project: "morpho-blue", symbol: "USDC", pool: "p-morpho", apy: 9, apyBase: 9, tvlUsd: 5_000_000, stablecoin: true, ilRisk: "no", exposure: "single" },
  { chain: "Base", project: "aerodrome-v1", symbol: "WETH-USDC", pool: "p-aero", underlyingTokens: [BASE_WETH, BASE_USDC], apy: 80, apyBase: null, apyReward: 80, apyMean30d: 20, tvlUsd: 4_000_000, stablecoin: false, ilRisk: "yes", exposure: "multi", rewardTokens: ["0x940181a94A35A4569E4529A3CDfB74e38FD98631"] },
  { chain: "Base", project: "uniswap-v3", symbol: "WETH-USDC", poolMeta: "0.3%", pool: "p-uni", apy: 900, apyBase: 900, tvlUsd: 9_000_000, ilRisk: "yes", exposure: "multi", outlier: true },
  { chain: "Base", project: "ember", symbol: "USDC", poolMeta: "Enigma‮", pool: "p-ember", apy: 60, apyBase: 60, tvlUsd: 1_500_000, stablecoin: true, ilRisk: "no", exposure: "single" },
  { chain: "Arbitrum", project: "aave-v3", symbol: "USDC", pool: "p-arb", apy: 50, apyBase: 50, tvlUsd: 9e9, exposure: "single" },
  { chain: "Base", project: "tiny", symbol: "USDC", pool: "p-tiny", apy: 40, apyBase: 40, tvlUsd: 1000, exposure: "single" },
];
const MORPHO = [{ address: VAULT, name: "Gauntlet USDC Prime", chain: { id: 8453 }, asset: { address: BASE_USDC, symbol: "USDC" }, state: { totalAssetsUsd: 399_000_000, apy: 0.045, netApy: 0.05, netApyExcludingRewards: 0.04, fee: 0.1 } }];

function setup(o: { llamaDown?: boolean } = {}) {
  let llamaCalls = 0;
  const fetcher = (async (url: string) => {
    if (url.startsWith("https://yields.llama.fi")) { llamaCalls++; if (o.llamaDown) return new Response("down", { status: 503 }); return new Response(JSON.stringify({ data: LLAMA })); }
    if (url === "https://api.morpho.org/graphql") return new Response(JSON.stringify({ data: { vaults: { items: MORPHO } } }));
    throw new Error(`unexpected ${url}`);
  }) as typeof fetch;
  const rpc = { callFunction: async (c: string, m: string, a: any) => {
    assert.equal(c, "contract.main.burrow.near"); assert.equal(m, "get_assets_paged"); assert.equal(a.from_index, 0);
    return { result: [
      [USDC_NEAR, { supplied: { balance: "1000000000000000000000000" }, reserved: "0", borrowed: { balance: "850000000000000000000000" }, config: { ...RATE, extra_decimals: 12, can_deposit: true } }],
      ["closed.near", { supplied: { balance: "1" }, reserved: "0", borrowed: { balance: "0" }, config: { ...RATE, can_deposit: false } }],
    ] };
  } };
  const catalog = [{ assetId: `nep141:${USDC_NEAR}`, blockchain: "near", symbol: "USDC", decimals: 6, price: 1, contractAddress: USDC_NEAR }];
  const cs = { rpcFor: () => ({ multicall: async ({ contracts }: any) => contracts.map((c: any) => {
    assert.equal(c.address, AAVE_BASE); assert.equal(c.functionName, "getReserveData");
    return { status: "success", result: { currentLiquidityRate: 46260427258804820000000000n } };
  }) }) };
  const y = new YieldSearch({ rpc } as any, { catalog: async () => catalog } as any, cs as any, fetcher);
  return { y, llamaCalls: () => llamaCalls };
}

test("rhea rate model: per-ms compounding, supply = borrow x utilization x (1 - reserve)", () => {
  const r = rheaSupplyApy(191327181105296297768572n + 57109914086417666143248n, 191941800483515633710546n, RATE)!;
  assert.ok(Math.abs(r.utilization - 0.7726) < 0.001);
  assert.ok(Math.abs(r.borrow - 5.79) < 0.02, String(r.borrow));
  assert.ok(Math.abs(r.supply - 3.35) < 0.02, String(r.supply));
  assert.deepEqual(rheaSupplyApy(0n, 0n, RATE), { supply: 0, borrow: 0, utilization: 0 });
  assert.equal(rheaSupplyApy(1n, 0n, { ...RATE, target_utilization: 0 }), null);
});

test("yield_search: index rows replaced by on-chain Rhea and Morpho API, Aave re-checked on-chain, outliers and other chains dropped", async () => {
  const { y } = setup();
  const r: any = await y.search({ token: "USDC", stable_only: true, min_tvl_usd: 100_000 });
  const by = (p: string) => r.results.find((x: any) => x.protocol === p);
  assert.equal(r.results.filter((x: any) => x.protocol === "rhea-lend").length, 1);
  const rhea = by("rhea-lend");
  assert.equal(rhea.source, "rhea_onchain"); assert.equal(rhea.verified, "onchain"); assert.equal(rhea.contract, "contract.main.burrow.near");
  assert.equal(rhea.check.defillama_apy, 10.1);
  assert.equal(rhea.tvl_usd, 150000); assert.equal(rhea.check.total_supplied_usd, 1000000);
  assert.ok(!r.results.some((x: any) => x.protocol === "morpho-blue"));
  const m = by("morpho");
  assert.deepEqual([m.contract, m.apy, m.apy_base, m.apy_reward, m.verified], [VAULT, 5, 4, 1, "protocol_api"]);
  const aave = by("aave-v3");
  assert.equal(aave.verified, "onchain"); assert.equal(aave.contract, AAVE_BASE);
  assert.ok(Math.abs(aave.apy_base - 4.7347) < 0.001); assert.equal(aave.check.defillama_apy_base, 4.79);
  const ember = by("ember");
  assert.equal(ember.name, "USDC (Enigma?)");
  assert.ok(ember.warnings.some((w: string) => /not classified/.test(w)) && ember.warnings.some((w: string) => /above 20%/.test(w)));
  assert.ok(!r.results.some((x: any) => ["uniswap-v3", "tiny"].includes(x.protocol) || x.network === "arbitrum"));
  assert.deepEqual(r.results.map((x: any) => x.apy), [...r.results.map((x: any) => x.apy)].sort((a, b) => b - a));
});

test("yield_search: WETH matches ETH, no_il / exclude_rewards filter LPs, warnings explain reward-only yield", async () => {
  const { y, llamaCalls } = setup();
  const lp: any = await y.search({ networks: ["base"], token: "ETH" });
  assert.equal(lp.results[0].protocol, "aerodrome-v1");
  assert.ok(lp.results[0].warnings.some((w: string) => /only reward-token/.test(w)) && lp.results[0].warnings.some((w: string) => /impermanent/.test(w)) && lp.results[0].warnings.some((w: string) => /30-day mean/.test(w)));
  assert.equal((await y.search({ networks: ["base"], token: "ETH", no_il: true })).results.length, 0);
  assert.equal((await y.search({ networks: ["base"], token: "ETH", exclude_rewards: true })).results.length, 0);
  assert.equal((await y.search({ networks: ["base"], token: "ETH", include_outliers: true })).results[0]!.protocol, "uniswap-v3");
  assert.equal(llamaCalls(), 1); // cached index
});

test("yield_search: a failed source is reported while the others still answer", async () => {
  const { y } = setup({ llamaDown: true });
  const r: any = await y.search({});
  assert.equal(r.partial, true);
  assert.equal(r.sources.defillama, "failed");
  assert.match(r.errors[0], /defillama: HTTP 503/);
  assert.deepEqual(r.results.map((x: any) => x.protocol).sort(), ["morpho"]); // rhea TVL 150k < 250k default
  assert.equal((await y.search({ networks: ["near"], min_tvl_usd: 0 })).results[0]!.protocol, "rhea-lend");
});
