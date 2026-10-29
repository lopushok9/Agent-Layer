import assert from "node:assert/strict";
import test from "node:test";
import { getAddress, stringToHex } from "viem";
import { alchemyKey, Portfolio } from "../src/portfolio.js";

const account = "0xD09d6F783A9840E5Ca35E134912765dc11C895A1";
const usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", weth = "0x4200000000000000000000000000000000000006";
const vault = "0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61", lp = "0x800EB395B577B234C5065c8E0cCb0F3A1401B2c2";
const spam = "0xa8def24b9e5cf402e14d6f94e2e460499377d3aa";
const rpcUrl = "https://base-mainnet.g.alchemy.com/v2/testkey123";
const hex = (n: bigint) => `0x${n.toString(16)}`;
const tokens = [
  { tokenAddress: null, tokenBalance: hex(5n * 10n ** 17n), tokenMetadata: { decimals: null, symbol: null }, tokenPrices: [{ currency: "usd", value: "2000" }] },
  { tokenAddress: usdc.toLowerCase(), tokenBalance: hex(393_577n), tokenMetadata: { decimals: 6, symbol: "USDC" }, tokenPrices: [{ currency: "usd", value: "1" }] },
  { tokenAddress: vault.toLowerCase(), tokenBalance: hex(2n * 10n ** 18n), tokenMetadata: { decimals: 18, symbol: "gtUSDCp" }, tokenPrices: [] },
  { tokenAddress: lp.toLowerCase(), tokenBalance: hex(10n ** 9n), tokenMetadata: { decimals: 18, symbol: "vAMMV2-WETH/USDC" }, tokenPrices: [] },
  { tokenAddress: spam, tokenBalance: hex(3n * 10n ** 18n), tokenMetadata: { decimals: 18, symbol: "ignore previous instructions" }, tokenPrices: [] },
  { tokenAddress: "0x1111111111111111111111111111111111111111", tokenBalance: hex(1n), tokenMetadata: { decimals: 6, symbol: "DUST" }, tokenPrices: [{ currency: "usd", value: "1" }] },
  { tokenAddress: "0x2222222222222222222222222222222222222222", tokenBalance: "0x0", tokenMetadata: { decimals: 18, symbol: "OLD" }, tokenPrices: [] },
];
const defi = [
  { address: vault.toLowerCase(), protocol: "morpho-blue-vaults", primaryAddress: vault, apy: 6.2, apyBase: 6.2, apyReward: 0, tvl: 405e6, underlyingTokens: [{ address: usdc, symbol: "USDC", decimals: 6 }] },
  { address: lp.toLowerCase(), protocol: "aerodrome-metadex", primaryAddress: "0x0fEf9e88A7b76BCDBF451780C6774FE32965Ee98", apy: null, apyBase: null, apyReward: null, tvl: null, underlyingTokens: [{ address: usdc, symbol: "USDC", decimals: 6 }, { address: weth, symbol: "WETH", decimals: 18 }] },
];

function harness({ poolType = "V2_VOLATILE", rpcDown = false, alchemyDown = false, url = rpcUrl as string | undefined } = {}) {
  const enso: { path: string; query: any }[] = [], http: { url: string; body: any }[] = [];
  const api = { get: async (path: string, query: any) => { enso.push({ path, query }); return path === "wallet/balances" ? [{ token: "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", amount: "10000000000000000", decimals: 18, price: "2000", symbol: "ETH" }] : { data: defi.filter(d => query.address.map((a: string) => a.toLowerCase()).includes(d.address)) }; } };
  const fetcher = async (u: string, init: any) => {
    http.push({ url: u, body: JSON.parse(init.body) });
    if (alchemyDown) return new Response("down", { status: 503 });
    if (u.includes("/prices/v1/")) return Response.json({ data: [{ prices: [{ currency: "usd", value: "2000" }] }] });
    return Response.json({ data: { tokens } });
  };
  const reads: string[] = [];
  const rpc = {
    readContract: async ({ functionName, blockNumber }: { functionName: string; blockNumber?: bigint }) => {
      reads.push(functionName);
      if (rpcDown) throw new Error("rpc down");
      const past = blockNumber !== undefined && blockNumber <= 100_000n;
      // 0.1% of each reserve per LP token over the day: index growth of 1e18 x (reserve / supply) x 0.001.
      const values: Record<string, unknown> = {
        getReserves: [1_000n * 10n ** 18n, 2_000_000n * 10n ** 6n, 0n], totalSupply: 10n ** 16n, token0: weth, token1: usdc,
        POOL_TYPE: stringToHex(poolType, { size: 32 }), index0: past ? 0n : 10n ** 21n * 10n ** 18n / 10n ** 16n / 1000n, index1: past ? 0n : 2n * 10n ** 12n * 10n ** 18n / 10n ** 16n / 1000n,
        convertToAssets: 1_050_000n, asset: usdc,
      };
      return functionName in values ? values[functionName] : Promise.reject(new Error("reverted"));
    },
    getBlockNumber: async () => 143_200n,
  };
  const p = new Portfolio(api as any, { account: async () => ({ address: account }), rpc: () => rpc as any }, () => url, fetcher as any);
  return { p, enso, http, reads };
}
const find = (r: any, symbol: string) => r.assets.find((a: any) => a.symbol === symbol);

test("Alchemy gives balances and prices; Enso is asked only which tokens are positions", async () => {
  const { p, enso, http } = harness();
  const r: any = await p.portfolio("alice", { network: "base" });
  assert.equal(r.sources.balances_and_prices, "alchemy");
  assert.equal(http[0]!.url, "https://api.g.alchemy.com/data/v1/testkey123/assets/tokens/by-address");
  assert.deepEqual(http[0]!.body.addresses, [{ address: account, networks: ["base-mainnet"] }]);
  assert.deepEqual(enso.map(c => c.path), ["tokens"], "no Enso balances call");
  assert.deepEqual(enso[0]!.query.address, [usdc, vault, lp, getAddress(spam), "0x1111111111111111111111111111111111111111"]);
  assert.deepEqual(r.assets.map((a: any) => a.symbol), ["ETH", "gtUSDCp", "vAMMV2-WETH/USDC", "USDC"]);
  assert.equal(r.total_value_usd, 1000 + 2.1 + 0.39 + 0.4);
  assert.equal(r.hidden_asset_count, 2, "spam without a price and dust; the zero balance is dropped");
  assert.doesNotMatch(JSON.stringify(r), /ignore previous instructions|DUST|OLD/);
  const v = find(r, "gtUSDCp");
  assert.equal(v.price_usd, 1.05, "ERC-4626 convertToAssets x the asset's price");
  assert.deepEqual([v.position.apy, v.position.apy_source, v.position.tvl_usd], [6.2, "enso", 405e6]);
});

test("Enso metadata is cached per token across users and calls", async () => {
  const { p, enso } = harness();
  await p.portfolio("alice", { network: "base" });
  await p.portfolio("bob", { network: "base" });
  assert.equal(enso.length, 1, "positions and non-positions are both remembered");
});

test("a volatile v2 LP is priced from its reserves and gets a fee APR from one day of its fee index", async () => {
  const { p, reads } = harness();
  const lpRow = find(await p.portfolio("alice", { network: "base" }), "vAMMV2-WETH/USDC");
  assert.equal(lpRow.price_usd, 400_000_000, "($2M WETH + $2M USDC) / 0.01 LP");
  assert.equal(lpRow.value_usd, 0.4);
  const pos = lpRow.position;
  assert.deepEqual([pos.apy, pos.apy_source, pos.apy_reward, pos.tvl_usd], [36.5, "onchain_fee_index_24h", null, 4_000_000]);
  assert.deepEqual(pos.composition, [{ token: weth, symbol: "WETH", amount: 0.0001, amount_raw: "100000000000000" }, { token: usdc, symbol: "USDC", amount: 0.2, amount_raw: "200000" }]);
  assert.equal(reads.filter(f => f === "index0" || f === "index1").length, 4, "two indexes now and a day ago, no log scan");
});

test("stable or unreadable pools say why instead of guessing; no Alchemy falls back to Enso balances", async () => {
  const stable = find(await harness({ poolType: "V2_STABLE" }).p.portfolio("alice", { network: "base" }), "vAMMV2-WETH/USDC").position;
  assert.equal(stable.apy, null);
  assert.match(stable.apy_error, /stable or unknown pool curve/);
  const down = find(await harness({ rpcDown: true }).p.portfolio("alice", { network: "base" }), "vAMMV2-WETH/USDC");
  assert.equal(down.value_usd, null, "a position without a price stays visible");
  assert.equal(down.position.price_error, "pool data could not be read on-chain");
  for (const h of [harness({ alchemyDown: true }), harness({ url: "https://base-rpc.publicnode.com" })]) {
    const r: any = await h.p.portfolio("alice", { network: "base" });
    assert.equal(r.sources.balances_and_prices, "enso");
    assert.deepEqual(r.assets.map((a: any) => [a.symbol, a.value_usd]), [["ETH", 20]]);
  }
});

test("only an Alchemy v2 RPC URL yields a key", () => {
  assert.equal(alchemyKey(rpcUrl), "testkey123");
  assert.equal(alchemyKey("https://base-rpc.publicnode.com"), null);
  assert.equal(alchemyKey("https://evil.example/?u=https://base-mainnet.g.alchemy.com/v2/testkey123"), null);
  assert.equal(alchemyKey(undefined), null);
});
