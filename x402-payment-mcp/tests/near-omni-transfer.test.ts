import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, erc20Abi } from "viem";
import { OmniTransfer } from "../src/near/omni-transfer.js";

const SELF = "c1f18b054c4273bc6e13111282f3acdff9b7c9f352ed4f0840f1f792b0d46bf4";
const EVM = "0xF9B83E2b759D9C92461a0fb569C1CC2deEDC15b9";
const DEP = "0x1111111111111111111111111111111111111111";
const POA = "0x2222222222222222222222222222222222222222";
const TOKENS = [
  { assetId: "nep141:wrap.near", blockchain: "near", symbol: "wNEAR", decimals: 24, contractAddress: "wrap.near" },
  { assetId: "nep141:usdc.near", blockchain: "near", symbol: "USDC", decimals: 6, contractAddress: "usdc.near" },
  { assetId: "nep141:base.omft.near", blockchain: "base", symbol: "ETH", decimals: 18 },
  { assetId: "nep141:base-usdc.omft.near", blockchain: "base", symbol: "USDC", decimals: 6, contractAddress: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913" },
];

function setup(held: { asset_id: string; symbol: string }[] = []) {
  const calls: [string, any, ...any[]][] = [];
  const rec = (name: string) => async (...a: any[]) => { calls.push([name, a[1], ...a.slice(2)]); return { operation_id: "00000000-0000-4000-8000-000000000001", kind: name }; };
  const asset = async (ref: string) => {
    const r = ref.toUpperCase() === "NEAR" ? "nep141:wrap.near" : ref;
    const at = r.indexOf("@");
    const hit = at > 0 && !r.includes(":") ? TOKENS.filter(t => t.symbol.toUpperCase() === r.slice(0, at).toUpperCase() && t.blockchain === r.slice(at + 1)) : TOKENS.filter(t => t.assetId === r);
    if (hit.length !== 1) throw new Error(`no asset ${ref}`);
    return hit[0]!;
  };
  const intents: any = {
    asset, balances: async () => ({ balances: held }),
    prepareDeposit: rec("prepareDeposit"), prepare: rec("intents.prepare"),
    quoteFromEvm: async (_u: string, p: any) => { calls.push(["quoteFromEvm", p]); return { from: EVM, plan: { deposit_address: DEP }, description: { protocol: "near_intents_1click" } }; },
  };
  const trades: any = { prepareWithdraw: rec("trades.prepareWithdraw"), prepareOneClick: rec("trades.prepareOneClick") };
  const cs: any = { prepare: async (_u: string, input: any, extra: any, planExtra: any) => { calls.push(["cs.prepare", input, extra, planExtra]); return { operation_id: "x", kind: "chain_signature" }; } };
  const deposits: any = { depositAddress: async () => ({ deposit_address: POA, credited_to: `NEAR Intents balance of ${SELF}`, tokens: [{ intents_asset_id: "nep141:base-usdc.omft.near", min_deposit: "1000", min_deposit_formatted: "0.001" }] }) };
  return { t: new OmniTransfer({} as any, {} as any, {} as any, intents, trades, cs, deposits), calls };
}

test("omni_transfer routes: wallet <-> intents use the direct deposit / gasless withdraw; other pairs go through 1Click", async () => {
  const { t, calls } = setup([{ asset_id: "nep141:wrap.near", symbol: "wNEAR" }]);
  const a: any = await t.prepare("u1", { from: "near", to: "intents", asset: "USDC", amount: "0.5" });
  assert.equal(a.omni_transfer.route, "wallet_to_intents");
  assert.deepEqual(calls.at(-1)![1], { asset: "nep141:usdc.near", amount: "500000" });
  const b: any = await t.prepare("u1", { from: "intents", to: "near", asset: "NEAR", amount: "0.1" });
  assert.equal(b.omni_transfer.route, "intents_to_wallet");
  assert.deepEqual(calls.at(-1)![1], { asset: "NEAR", amount: "100000000000000000000000" });
  const c: any = await t.prepare("u1", { from: "near", to: "base", asset: "USDC", amount: "1" });
  assert.equal(c.omni_transfer.route, "oneclick_from_wallet");
  assert.deepEqual(calls.at(-1)![1], { origin_asset: "nep141:usdc.near", destination_asset: "nep141:base-usdc.omft.near", amount: "1000000", pay_from: "wallet", deliver_to: "chain", slippage_bps: 100 });
  const d: any = await t.prepare("u1", { from: "intents", to: "base", asset: "NEAR", amount: "0.2", receive_asset: "ETH" });
  assert.equal(d.omni_transfer.route, "oneclick_from_intents");
  assert.equal(calls.at(-1)![1].destination_asset, "nep141:base.omft.near");
  assert.equal(calls.at(-1)![1].deliver_to, "chain");
  await assert.rejects(t.prepare("u1", { from: "near", to: "near", asset: "USDC", amount: "1" }), /already on near/);
  await assert.rejects(t.prepare("u1", { from: "base", to: "near", asset: "NEAR", amount: "1" }), /NEAR lives on NEAR/);
});

test("omni_transfer from Base: ETH to the NEAR wallet is one native transfer to the 1Click deposit address; USDC into intents uses the PoA bridge with an ERC-20 transfer", async () => {
  const { t, calls } = setup();
  const a: any = await t.prepare("u1", { from: "base", to: "near", asset: "ETH", amount: "0.0001", receive_asset: "NEAR" });
  assert.equal(a.omni_transfer.route, "oneclick_from_evm");
  const q = calls.find(c => c[0] === "quoteFromEvm")![1];
  assert.equal(q.dest.assetId, "nep141:wrap.near"); assert.equal(q.deliver_to, "chain"); assert.equal(q.amount, "100000000000000");
  const send = calls.at(-1)!;
  assert.deepEqual(send[1], { network: "base", to: DEP, value_wei: "100000000000000" });
  assert.deepEqual(send[3], { oneclick: { deposit_address: DEP } });
  const b: any = await t.prepare("u1", { from: "base", to: "intents", asset: "USDC", amount: "0.5" });
  assert.equal(b.omni_transfer.route, "poa_deposit");
  const tx = calls.at(-1)![1];
  assert.equal(tx.to, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913");
  const dec = decodeFunctionData({ abi: erc20Abi, data: tx.data });
  assert.equal(dec.functionName, "transfer"); assert.deepEqual(dec.args, [POA, 500000n]);
  await assert.rejects(t.prepare("u1", { from: "base", to: "intents", asset: "USDC", amount: "0.0001" }), /bridge minimum/);
});

test("omni_transfer from intents: a bare symbol picks what the intents balance holds; several matches need the asset id", async () => {
  const one = setup([{ asset_id: "nep141:base.omft.near", symbol: "ETH" }]);
  const r: any = await one.t.prepare("u1", { from: "intents", to: "base", asset: "ETH", amount: "0.001" });
  assert.equal(r.omni_transfer.route, "oneclick_from_intents");
  assert.equal(one.calls.at(-1)![1].origin_asset, "nep141:base.omft.near");
  const two = setup([{ asset_id: "nep141:usdc.near", symbol: "USDC" }, { asset_id: "nep141:base-usdc.omft.near", symbol: "USDC" }]);
  await assert.rejects(two.t.prepare("u1", { from: "intents", to: "near", asset: "USDC", amount: "1" }), /several USDC/);
});
