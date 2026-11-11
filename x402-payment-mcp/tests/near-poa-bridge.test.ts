import assert from "node:assert/strict";
import test from "node:test";
import { IntentsDeposits, PoaBridgeClient } from "../src/near/poa-bridge.js";

const SELF = "c1f18b054c4273bc6e13111282f3acdff9b7c9f352ed4f0840f1f792b0d46bf4";
const FROM = "0xF9B83E2b759D9C92461a0fb569C1CC2deEDC15b9";
const DEPOSIT = "0xe88da3be015be00cc4fd26d8a9e6c61739bf2ad2";
const TOKENS = [
  { defuse_asset_identifier: "eth:8453:native", origin_chain_address: "native", near_token_id: "base.omft.near", decimals: 18, asset_name: "ETH", min_deposit_amount: "100000000000", intents_token_id: "nep141:base.omft.near" },
  { defuse_asset_identifier: "eth:8453:0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", origin_chain_address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", decimals: 6, asset_name: "USDC", min_deposit_amount: "150000", intents_token_id: "nep141:base-0x833589fcd6edb6e08f4c7c32d4f71b54bda02913.omft.near" },
  { defuse_asset_identifier: "eth:1:native", origin_chain_address: "native", decimals: 18, asset_name: "ETH", min_deposit_amount: "1", intents_token_id: "nep141:eth.omft.near" },
];

function setup(address: string = DEPOSIT, chainEcho?: string) {
  const calls: any[] = [];
  const bridge = new PoaBridgeClient("https://bridge.example", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body)); calls.push(b);
    const reply = (result: unknown) => new Response(JSON.stringify({ jsonrpc: "2.0", id: 1, result }));
    if (b.method === "deposit_address") return reply({ address, chain: chainEcho ?? b.params[0].chain });
    if (b.method === "supported_tokens") return reply({ tokens: TOKENS });
    throw new Error("unexpected");
  }) as typeof fetch);
  const accounts = { account: async () => ({ accountId: SELF }) } as any;
  const cs = { fromAddress: async () => FROM } as any;
  return { deposits: new IntentsDeposits(accounts, cs, bridge), calls };
}

test("deposit address: asks the bridge for THIS NEAR account on Base and lists only Base tokens with minimums", async () => {
  const { deposits, calls } = setup();
  const r: any = await deposits.depositAddress("u1", { network: "base" });
  assert.deepEqual(calls[0].params[0], { account_id: SELF, chain: "eth:8453" });
  assert.equal(r.deposit_address, "0xE88DA3BE015Be00cC4fD26d8a9E6c61739Bf2AD2");
  assert.equal(r.send_from, FROM);
  assert.equal(r.credited_to, `NEAR Intents balance of ${SELF}`);
  assert.deepEqual(r.tokens.map((t: any) => t.intents_asset_id), ["nep141:base.omft.near", "nep141:base-0x833589fcd6edb6e08f4c7c32d4f71b54bda02913.omft.near"]);
  assert.equal(r.tokens[0].min_deposit_formatted, "0.0000001");
  assert.match(r.tokens[1].send_with, /function_name transfer, args \[0xE88DA3BE015Be00cC4fD26d8a9E6c61739Bf2AD2, amount\]/);
  const usdc: any = await deposits.depositAddress("u1", { network: "base", asset: "usdc" });
  assert.equal(usdc.tokens.length, 1);
});

test("deposit address: refuses a malformed address, a mismatched chain, or this account's own EVM address", async () => {
  await assert.rejects(setup("not-an-address").deposits.depositAddress("u1", { network: "base" }), /unexpected deposit address; do not send/);
  await assert.rejects(setup(DEPOSIT, "eth:1").deposits.depositAddress("u1", { network: "base" }), /unexpected deposit address/);
  await assert.rejects(setup(FROM).deposits.depositAddress("u1", { network: "base" }), /own address/);
});
