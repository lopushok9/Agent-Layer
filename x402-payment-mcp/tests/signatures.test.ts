import assert from "node:assert/strict";
import test from "node:test";
import { maxUint256, type Address } from "viem";
import { createSiweMessage } from "viem/siwe";
import { describeSignature, payload, signatureDigest, SignatureService } from "../src/signatures.js";
import { WalletStore, type WalletSignature } from "../src/wallet-store.js";
import { Store } from "../src/store.js";

const account = "0x1111111111111111111111111111111111111111" as Address;
const owner = "0x2222222222222222222222222222222222222222" as Address;
const spender = "0x3333333333333333333333333333333333333333";
const token = "0x4444444444444444444444444444444444444444";
const permitTypes = { EIP712Domain: [{ name: "name", type: "string" }, { name: "chainId", type: "uint256" }, { name: "verifyingContract", type: "address" }], Permit: [{ name: "owner", type: "address" }, { name: "spender", type: "address" }, { name: "value", type: "uint256" }, { name: "nonce", type: "uint256" }, { name: "deadline", type: "uint256" }] };
const permit = (chainId: number | string = 8453, verifyingContract: string = token) => ({ domain: { name: "USD Coin", chainId, verifyingContract }, types: permitTypes, primaryType: "Permit", message: { owner: account, spender, value: maxUint256.toString(), nonce: "0", deadline: "0" } });
const describe = (input: Parameters<typeof payload>[0]) => { const p = payload(input); return describeSignature(p.network, account, owner, p.payload, null); };

test("an ERC-2612 permit is shown as a token authorization; another chain or this wallet's own domain is refused", async () => {
  const d = await describe({ network: "base", typed_data: permit() });
  assert.deepEqual(d.authorizations, [`Allows ${spender} to spend an unlimited amount of token 0x4444444444444444444444444444444444444444 with no expiry.`]);
  assert.ok(d.warnings.some(w => w.includes("no transaction preview will follow")));
  assert.equal((await describe({ network: "base", typed_data: permit("0x2105") })).authorizations.length, 1, "hex chain IDs from eth_signTypedData_v4 are accepted");
  await assert.rejects(describe({ network: "base", typed_data: permit(1) }), /typed data is for chain 1, not base/);
  await assert.rejects(describe({ network: "base", typed_data: permit(8453, account) }), /addressed to this wallet/);
  await assert.rejects(describe({ network: "base", typed_data: permit(8453, owner) }), /addressed to this wallet/);
  await assert.rejects(describe({ network: "base", typed_data: { domain: { name: "Coinbase Smart Wallet", chainId: 8453 }, types: { CoinbaseSmartWalletMessage: [{ name: "hash", type: "bytes32" }] }, primaryType: "CoinbaseSmartWalletMessage", message: { hash: `0x${"0".repeat(64)}` } } }), /addressed to this wallet/);
  await assert.rejects(describe({ network: "base", typed_data: { ...permit(), primaryType: "Missing" } }), /invalid EIP-712 typed data/);
});

test("Permit2 allowances name the spender, token, amount and expiry", async () => {
  const typed = { domain: { name: "Permit2", chainId: 8453, verifyingContract: "0x000000000022D473030F116dDEE9F6B43aC78BA3" }, primaryType: "PermitSingle", types: { PermitSingle: [{ name: "details", type: "PermitDetails" }, { name: "spender", type: "address" }, { name: "sigDeadline", type: "uint256" }], PermitDetails: [{ name: "token", type: "address" }, { name: "amount", type: "uint160" }, { name: "expiration", type: "uint48" }, { name: "nonce", type: "uint48" }] }, message: { details: { token, amount: "5000000", expiration: "1900000000", nonce: "0" }, spender, sigDeadline: "1900000000" } };
  const d = await describe({ network: "base", typed_data: typed });
  assert.equal(d.authorizations[0], `Permit2 lets ${spender} take 5000000 of token ${token} until 2030-03-17T17:46:40.000Z.`);
});

test("Sign-In with Ethereum is checked for address, chain, expiry and, with an origin, the requesting domain", async () => {
  const siwe = (address: Address, chainId = 8453) => createSiweMessage({ address, chainId, domain: "app.example.com", uri: "https://app.example.com/login", nonce: "abcdefgh12", version: "1", statement: "Sign in" });
  const ok = await describe({ network: "base", message: siwe(account) });
  assert.equal(ok.summary, "Sign-In with Ethereum to app.example.com");
  await assert.rejects(describe({ network: "base", message: siwe(spender as Address) }), /different address/);
  await assert.rejects(describe({ network: "base", message: siwe(account, 1) }), /for chain 1, not base/);
  const raw = await describe({ network: "base", message_hex: `0x${"ab".repeat(32)}` });
  assert.ok(raw.warnings.some(w => w.includes("look like a hash")));
  const { service } = harness();
  await assert.rejects(service.prepare("alice", { network: "base", message: siwe(account) }, "https://evil.example.net"), /does not match the requesting app evil\.example\.net/);
  assert.ok((await service.prepare("alice", { network: "base", message: siwe(account) }, "https://app.example.com")).signature_id);
});

function harness() {
  const rows = new Map<string, WalletSignature>(); const signed: unknown[] = []; let fail = false;
  const store = {
    createSignature: async (p: any) => { const s = { ...p, id: `s${rows.size}`, expiresAt: new Date(Date.now() + 60_000), status: "prepared", error: null }; rows.set(s.id, s); return s; },
    signature: async (_u: string, id: string) => rows.get(id) ?? null,
    reserveSignature: async (_u: string, id: string) => { const s = rows.get(id)!; if (s.status !== "prepared") throw new Error("signature preview already used; prepare a new one"); s.status = "signing"; return s; },
    finishSignature: async (id: string, status: any) => { rows.get(id)!.status = status; },
  };
  const wallets = {
    account: async () => ({ address: account, owners: [{ address: owner }] }),
    signTypedData: async (_u: string, _n: string, t: unknown) => { if (fail) throw new Error("smart account signature failed ERC-1271/ERC-6492 verification; nothing was returned"); signed.push(t); return `0x${"11".repeat(65)}`; },
    signMessage: async (_u: string, _n: string, m: unknown) => { signed.push(m); return `0x${"22".repeat(65)}`; },
  };
  return { rows, signed, service: new SignatureService(wallets as any, store as any, 600), fail: () => { fail = true; } };
}

test("a signature preview signs once, only the bound digest, and a failed verification returns nothing", async () => {
  const h = harness();
  const p = await h.service.prepare("alice", { network: "base", typed_data: permit() });
  const r = await h.service.execute("alice", p.signature_id, "approve app");
  assert.equal(r.signer, account); assert.equal(r.format, "erc1271_smart_account"); assert.equal(h.signed.length, 1);
  await assert.rejects(h.service.execute("alice", p.signature_id, "again"), /already used/);
  const q = await h.service.prepare("alice", { network: "base", message: "hello" });
  h.rows.get(q.signature_id)!.payload = { kind: "message", message: "something else" };
  await assert.rejects(h.service.execute("alice", q.signature_id, "tampered"), /no longer matches/);
  assert.equal(h.rows.get(q.signature_id)!.status, "failed");
  const f = await h.service.prepare("alice", { network: "base", typed_data: permit() });
  h.fail();
  await assert.rejects(h.service.execute("alice", f.signature_id, "x"), /verification/);
  assert.equal(h.rows.get(f.signature_id)!.status, "failed");
  assert.equal(h.signed.length, 1, "nothing else was signed");
});

test("digests are the EIP-712 and EIP-191 hashes isValidSignature receives", () => {
  assert.equal(signatureDigest({ kind: "message", message: "hello" }), "0x50b2c43fd39106bafbba0da34fc430e1f91e3c96ea2acee2bc34119f92b37750");
  assert.equal(signatureDigest({ kind: "message", raw: "0x68656c6c6f" }), "0x50b2c43fd39106bafbba0da34fc430e1f91e3c96ea2acee2bc34119f92b37750");
});

test("Postgres: a signature preview is consumed by exactly one of concurrent executions", { skip: !process.env.TEST_DATABASE_URL }, async () => {
  const db = new Store(process.env.TEST_DATABASE_URL!);
  try {
    await db.migrate();
    const userId = await db.upsertIdentity("github", `sig-${Date.now()}`, "Signer", null);
    const store = new WalletStore(db.pool);
    const p = payload({ network: "base", message: "hello" });
    const s = await store.createSignature({ userId, network: "base", address: account, payload: p.payload, digest: signatureDigest(p.payload), description: { summary: "x", authorizations: [], warnings: [] } }, 600);
    const results = await Promise.allSettled(Array.from({ length: 5 }, () => store.reserveSignature(userId, s.id, "race")));
    assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
    await assert.rejects(store.reserveSignature(userId, s.id, "late"), /already used/);
    const expired = await store.createSignature({ userId, network: "base", address: account, payload: p.payload, digest: signatureDigest(p.payload), description: { summary: "x", authorizations: [], warnings: [] } }, -1);
    await assert.rejects(store.reserveSignature(userId, expired.id, "late"), /expired/);
    await assert.rejects(store.reserveSignature(await db.upsertIdentity("github", `sig2-${Date.now()}`, "Other", null), s.id, "steal"), /not found/);
  } finally { await db.close(); }
});
