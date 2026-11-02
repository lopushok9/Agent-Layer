import assert from "node:assert/strict";
import test from "node:test";
import { depositedShareTokens, WalletHistory } from "../src/history.js";

const account = "0xD09d6F783A9840E5Ca35E134912765dc11C895A1", me = account.toLowerCase();
const zero = "0x0000000000000000000000000000000000000000";
const entryPoint = "0x5ff137d4b0fdcd49dca30c7cf57e578a026d2789", morpho = "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb";
const usdc = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", weth = "0x4200000000000000000000000000000000000006";
const vault = "0x23574154842bc86cf5bbc5f99376cfa1e2f82497", spam = "0x5555555555555555555555555555555555555555";
const funder = "0xdf7ed8b45ae91a0881c83a876747af1ffb48c36e", poisoner = "0xdf7ec7183c506586ecbaf7554e6238d58448c36e";
const rpcUrl = "https://base-mainnet.g.alchemy.com/v2/testkey123";
const hex = (n: bigint) => `0x${n.toString(16)}`;
const h = (c: string) => `0x${c.repeat(64)}`;
let n = 0;
function t(hash: string, block: number, from: string, to: string, token: string, value: bigint, symbol: string | null, decimals = 18, category?: string) {
  return { blockNum: hex(BigInt(block)), uniqueId: `${hash}:log:${n++}`, hash, from, to, asset: symbol, category: category ?? (token === "native" ? "internal" : "erc20"), rawContract: { value: hex(value), address: token === "native" ? null : token, decimal: hex(BigInt(decimals)) }, metadata: { blockTimestamp: `2026-10-${String(block).padStart(2, "0")}T12:00:00.000Z` } };
}
const history = [
  t(h("1"), 27, funder, me, "native", 5n * 10n ** 15n, "ETH", 18, "external"),
  t(h("1"), 27, funder, me, "native", 5n * 10n ** 15n, "ETH", 18, "external"),
  t(h("2"), 28, poisoner, me, "0x6666666666666666666666666666666666666666", 427n * 10n ** 12n, "ⴹ‌Ꭲ‌‍Η"),
  t(h("3"), 28, spam, me, spam, 10n ** 24n, "CLAIM AT evil.example"),
  t(h("4"), 29, me, "0x7d6839415693801e94cdc4a7d732c9a3fdbbd1d7", usdc, 100_000n, "USDC", 6),
  t(h("4"), 29, "0x7d6839415693801e94cdc4a7d732c9a3fdbbd1d7", me, "native", 42n * 10n ** 12n, "ETH"),
  t(h("4"), 29, me, entryPoint, "native", 2n * 10n ** 12n, "ETH"),
  t(h("5"), 30, me, vault, weth, 31_705n * 10n ** 9n, "WETH"),
  t(h("5"), 30, zero, me, vault, 24_934n * 10n ** 9n, "pfWETH-12"),
  t(h("5"), 30, me, entryPoint, "native", 10n ** 12n, "ETH"),
  t(h("6"), 31, me, morpho, usdc, 101_314n, "USDC", 6),
  t(h("6"), 31, morpho, me, weth, 31_705n * 10n ** 9n, "WETH"),
  t(h("7"), 32, me, me, usdc, 1n, "USDC", 6),
] as any[];
// The same funding transfer reported twice (same uniqueId) must count once.
history[1].uniqueId = history[0].uniqueId;

function harness({ transfers = history, url = rpcUrl as string | undefined, pages = 1, down = false } = {}) {
  const calls: any[] = [];
  const fetcher = async (u: string, init: any) => {
    const body = JSON.parse(init.body);
    calls.push({ url: u, body });
    if (u.includes("/prices/v1/")) return Response.json({ data: body.addresses.map((a: any) => ({ address: a.address, prices: a.address === usdc ? [{ currency: "usd", value: "1" }] : [] })) });
    if (down) return new Response("down", { status: 503 });
    const p = body.params[0];
    const rows = transfers.filter(x => p.fromAddress ? x.from === me : x.to === me);
    const page = p.pageKey ? Number(p.pageKey) : 0, size = Math.ceil(rows.length / pages);
    const next = page + 1 < pages ? String(page + 1) : undefined;
    return Response.json({ result: { transfers: rows.slice(page * size, (page + 1) * size), ...(next ? { pageKey: next } : {}) } });
  };
  const hist = new WalletHistory({ account: async () => ({ address: account as `0x${string}` }) }, () => url, fetcher as any);
  return { hist, calls };
}
const byHash = (r: any, c: string) => r.transactions.find((x: any) => x.hash === h(c));

test("history reads both directions of every transfer category, newest first, and counts a transfer once", async () => {
  const { hist, calls } = harness();
  const r: any = await hist.activity("alice", { network: "base", include_unverified: true });
  const rpc = calls.filter(c => c.body.method === "alchemy_getAssetTransfers");
  assert.equal(rpc.length, 2);
  assert.equal(rpc[0].url, rpcUrl);
  for (const c of rpc) {
    assert.deepEqual(c.body.params[0].category, ["external", "internal", "erc20", "erc721", "erc1155"]);
    assert.equal(c.body.params[0].order, "desc");
    assert.equal(c.body.params[0].withMetadata, true);
  }
  assert.deepEqual(r.transactions.map((x: any) => x.block), [32, 31, 30, 29, 28, 28, 27]);
  assert.equal(byHash(r, "1").transfers.length, 1, "duplicate uniqueId dropped");
  assert.equal(byHash(r, "7").kind, "self_transfer", "a self transfer appears in both directions but once");
  assert.equal(byHash(r, "7").transfers.length, 1);
  assert.equal(r.history_complete, true);
});

test("kinds, the EntryPoint gas prefund and labels come from the token movements", async () => {
  const r: any = await harness().hist.activity("alice", { network: "base" });
  const deposit = byHash(r, "5");
  assert.equal(deposit.kind, "deposit");
  assert.equal(deposit.entrypoint_prefund_eth, 1e-6);
  assert.deepEqual(deposit.transfers.map((x: any) => [x.direction, x.symbol, x.amount, x.counterparty_label]), [["out", "WETH", 0.000031705, null], ["in", "pfWETH-12", 0.000024934, "minted"]]);
  assert.equal(deposit.transfers[1].counterparty, null, "the zero address is a mint, not a counterparty");
  assert.equal(byHash(r, "4").kind, "swap");
  assert.equal(byHash(r, "4").entrypoint_prefund_eth, 2e-6);
  const lending = byHash(r, "6");
  assert.equal(lending.kind, "lending");
  assert.ok(lending.transfers.every((x: any) => x.counterparty_label === "Morpho Blue"));
  assert.equal(byHash(r, "1").kind, "receive");
  assert.equal(byHash(r, "1").transfers[0].category, "external");
});

test("unpriced incoming-only tokens are hidden as spam, but address poisoning is always shown with a warning", async () => {
  const { hist } = harness();
  const r: any = await hist.activity("alice", { network: "base" });
  assert.equal(byHash(r, "3"), undefined, "airdropped spam is hidden");
  assert.equal(r.hidden_unverified_count, 1);
  assert.doesNotMatch(JSON.stringify(r), /evil\.example/);
  const poison = byHash(r, "2");
  assert.ok(poison, "a poisoning attempt stays visible even though its token is unpriced");
  assert.match(poison.warnings[0], /possible address poisoning: sender 0xDF7EC7183c506586ecbAf7554e6238d58448C36E imitates 0xdf7ed8B45AE91a0881C83a876747AF1FfB48c36E/i);
  assert.match(poison.transfers[0].symbol, /^\?+$/, "non-ASCII lookalike symbols are masked");
  const all: any = await hist.activity("alice", { network: "base", include_unverified: true });
  assert.ok(byHash(all, "3"));
  assert.equal(all.hidden_unverified_count, 0);
  assert.ok(byHash(all, "3").warnings.length === 0, "a plain airdrop is not called poisoning");
});

test("addresses the account sent to are trusted and never flagged", async () => {
  const twinOfRecipient = "0x7d6800000000000000000000000000000000d1d7";
  const r: any = await harness({ transfers: [...history, t(h("8"), 33, twinOfRecipient, me, usdc, 0n, "USDC", 6)] }).hist.activity("alice", { network: "base" });
  const x = byHash(r, "8");
  assert.ok(x.warnings.some((w: string) => /imitates 0x7d6839415693801e94Cdc4A7d732C9A3FDBBD1d7/i.test(w)));
  assert.ok(x.warnings.some((w: string) => /zero-value incoming transfer/.test(w)));
  assert.ok(byHash(r, "4").warnings.length === 0, "the real counterparty itself has no warning");
});

test("pages are followed, offset pages the merged list, and a capped history says it is incomplete", async () => {
  const { hist, calls } = harness({ pages: 2 });
  const first: any = await hist.activity("alice", { network: "base", limit: 3 });
  assert.equal(calls.filter(c => c.body.method === "alchemy_getAssetTransfers").length, 4, "two pages per direction");
  assert.equal(first.count, 3);
  assert.equal(first.next_offset, 3);
  const rest: any = await hist.activity("alice", { network: "base", limit: 3, offset: 3 });
  assert.deepEqual(rest.transactions.map((x: any) => x.block), [29, 28, 27]);
  assert.equal(rest.next_offset, null);
  assert.equal(calls.filter(c => c.body.method === "alchemy_getAssetTransfers").length, 4, "cached for the second page");
  const capped: any = await harness({ pages: 5 }).hist.activity("alice", { network: "base" });
  assert.equal(capped.history_complete, false);
  assert.match(capped.history_note, /newest 3000 transfers/);
});

test("deposit shares are the mints of transactions in which the account paid; airdrop mints are not", async () => {
  const airdropMint = t(h("9"), 34, zero, me, "0x7777777777777777777777777777777777777777", 10n ** 18n, "VAULT");
  const prefundOnly = [t(h("a"), 35, zero, me, "0x8888888888888888888888888888888888888888", 10n ** 18n, "X"), t(h("a"), 35, me, entryPoint, "native", 1n, "ETH")];
  const loaded = await harness({ transfers: [...history, airdropMint, ...prefundOnly] }).hist.load("base", account);
  assert.deepEqual(depositedShareTokens(loaded), [vault], "a gas prefund alone is not a payment");
});

test("no Alchemy URL or a failing Alchemy is an error, never an empty history", async () => {
  await assert.rejects(harness({ url: "https://base-rpc.publicnode.com" }).hist.activity("alice", { network: "base" }), /needs an Alchemy RPC URL/);
  await assert.rejects(harness({ down: true }).hist.activity("alice", { network: "base" }), /transfer history is unavailable/);
});
