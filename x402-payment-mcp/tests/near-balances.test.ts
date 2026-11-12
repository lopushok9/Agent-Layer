import assert from "node:assert/strict";
import test from "node:test";
import { OmniBalances } from "../src/near/balances.js";

const SELF = "c1f18b054c4273bc6e13111282f3acdff9b7c9f352ed4f0840f1f792b0d46bf4";
const EVM = "0xF9B83E2b759D9C92461a0fb569C1CC2deEDC15b9";
const USDC = "17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1";
const BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const CATALOG = [
  { assetId: "nep141:wrap.near", blockchain: "near", symbol: "wNEAR", decimals: 24, price: 3.5, contractAddress: "wrap.near" },
  { assetId: `nep141:${USDC}`, blockchain: "near", symbol: "USDC", decimals: 6, price: 1, contractAddress: USDC },
  { assetId: "nep141:base.omft.near", blockchain: "base", symbol: "ETH", decimals: 18, price: 2000 },
  { assetId: "nep141:base-usdc.omft.near", blockchain: "base", symbol: "USDC", decimals: 6, price: 1, contractAddress: BASE_USDC },
  { assetId: "nep141:eth.omft.near", blockchain: "eth", symbol: "ETH", decimals: 18, price: 2000 },
];

function setup(o: { indexer?: "ok" | "down"; catalogDown?: boolean; baseDown?: boolean; ftBalances?: Record<string, string> } = {}) {
  const ftCalls: string[] = [];
  const ft: Record<string, string> = o.ftBalances ?? { [USDC]: "1495326", "wrap.near": "0", "meme.near": "5000" };
  const accounts = {
    account: async () => ({ accountId: SELF }),
    rpc: {
      viewAccount: async () => ({ amount: "203148027309880990790553", locked: "0", storage_usage: 182 }),
      callFunction: async (c: string, m: string) => {
        if (m === "ft_balance_of") { ftCalls.push(c); return { result: ft[c] ?? "0" }; }
        if (m === "ft_metadata" && c === "meme.near") return { result: { symbol: "MEME‮", decimals: 2 } };
        if (m === "ft_metadata" && c === USDC) return { result: { symbol: "USDC", decimals: 6 } };
        throw new Error("no such method");
      },
    },
  } as any;
  const intents = {
    catalog: async () => { if (o.catalogDown) throw new Error("1Click down"); return CATALOG; },
    balances: async () => ({ balances: [{ asset_id: "nep141:wrap.near", amount: "452308675779598509518540", symbol: "wNEAR", decimals: 24, formatted: "0.45230867577959850951854", value_usd: 1.58 }] }),
  } as any;
  const cs = {
    address: async () => EVM,
    rpcFor: (network: string) => ({
      getBalance: async () => { if (network === "base" && o.baseDown) throw new Error("rpc"); return network === "base" ? 587306596117340n : 0n; },
      multicall: async ({ contracts }: any) => contracts.map((c: any) => c.address.toLowerCase() === BASE_USDC ? { status: "success", result: 2500000n } : { status: "success", result: 0n }),
    }),
  } as any;
  const fetcher = (async (url: string) => {
    if (o.indexer === "down") throw new Error("offline");
    assert.equal(url, `https://api.fastnear.com/v1/account/${SELF}/ft`);
    return new Response(JSON.stringify({ tokens: [{ contract_id: USDC }, { contract_id: "meme.near" }, { contract_id: "Bad Id!" }] }));
  }) as typeof fetch;
  let t = 1000;
  return { b: new OmniBalances(accounts, intents, cs, fetcher, undefined, () => (t += 40)), ftCalls };
}

test("omni_balances: wallet, intents and EVM in one read with USD totals", async () => {
  const { b, ftCalls } = setup();
  const r: any = await b.all("u1");
  assert.equal(r.account_id, SELF);
  assert.deepEqual(r.near_wallet.assets.map((a: any) => [a.symbol, a.formatted, a.value_usd]), [["NEAR", "0.203148027309880990790553", 0.71], ["USDC", "1.495326", 1.5], ["MEME?", "50", null]]);
  assert.equal(r.near_wallet.assets[2].unlisted, true);
  assert.equal(r.near_wallet.available_near, "0.201328027309880990790553");
  assert.equal(r.intents.total_value_usd, 1.58);
  assert.equal(r.evm.address, EVM);
  const base = r.evm.networks.find((n: any) => n.network === "base");
  assert.deepEqual(base.assets.map((a: any) => [a.symbol, a.formatted, a.value_usd]), [["ETH", "0.00058730659611734", 1.17], ["USDC", "2.5", 2.5]]);
  assert.deepEqual(r.evm.networks.find((n: any) => n.network === "ethereum").assets, []);
  assert.equal(r.total_value_usd, 0.71 + 1.5 + 1.58 + 1.17 + 2.5);
  assert.equal(r.partial, undefined);
  // indexer is only a hint; invalid ids dropped, common tokens always checked on RPC
  assert.ok(!ftCalls.includes("Bad Id!"));
  assert.ok(ftCalls.includes("wrap.near") && ftCalls.includes(USDC) && ftCalls.includes("meme.near"));
});

test("omni_balances: indexer down falls back to 1Click NEAR tokens; failed sources are reported, others still shown", async () => {
  const { b, ftCalls } = setup({ indexer: "down", baseDown: true });
  const r: any = await b.all("u1");
  assert.ok(ftCalls.includes(USDC) && !ftCalls.includes("meme.near"));
  assert.equal(r.near_wallet.assets.length, 2);
  assert.equal(r.evm.networks.find((n: any) => n.network === "base").error, "balance unavailable");
  assert.equal(r.intents.assets.length, 1);
});

test("omni_balances: without the 1Click list, amounts still show and USD is null with a note", async () => {
  const { b } = setup({ catalogDown: true });
  const r: any = await b.all("u1");
  assert.equal(r.near_wallet.assets[0].value_usd, null);
  const usdc = r.near_wallet.assets.find((a: any) => a.asset === `nep141:${USDC}`);
  assert.deepEqual([usdc.symbol, usdc.formatted, usdc.value_usd], ["USDC", "1.495326", null]);
  assert.equal(r.partial, true);
  assert.match(r.errors.join(" "), /token list is unavailable/);
});

test("omni_balances: Rhea Lend positions under defi, borrowed subtracts from the total; a failed reader is reported", async () => {
  const { b } = setup();
  b.lend = { positions: async () => [
    { side: "supplied", symbol: "USDC", token_id: USDC, amount: "500000", formatted: "0.5", decimals: 6, apr_percent: 8.99 },
    { side: "borrowed", symbol: "wNEAR", token_id: "wrap.near", amount: "100000000000000000000000", formatted: "0.1", decimals: 24, apr_percent: 2.5 },
  ] } as any;
  const r: any = await b.all("u1");
  assert.deepEqual(r.defi.rhea_lend.positions.map((p: any) => [p.side, p.symbol, p.value_usd]), [["supplied", "USDC", 0.5], ["borrowed", "wNEAR", 0.35]]);
  assert.equal(r.defi.rhea_lend.net_value_usd, 0.15);
  assert.equal(r.total_value_usd, Math.round((0.71 + 1.5 + 1.58 + 1.17 + 2.5 + 0.15) * 100) / 100);
  b.lend = { positions: async () => { throw new Error("rpc down"); } } as any;
  const f: any = await b.all("u1");
  assert.equal(f.defi.rhea_lend.error, "unavailable");
  assert.equal(f.partial, true);
});
