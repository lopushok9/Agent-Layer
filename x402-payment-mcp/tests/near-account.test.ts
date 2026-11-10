import assert from "node:assert/strict";
import { generateKeyPairSync, randomBytes, randomUUID, sign as edSign } from "node:crypto";
import test from "node:test";
import { baseEncode } from "@near-js/utils";
import { NearAccountService } from "../src/near/account.js";
import { loadNearConfig, type NearConfig } from "../src/near/config.js";
import { implicitAccountId, verifyEd25519, type CdpSolanaApi } from "../src/near/keys.js";
import { NearRpc } from "../src/near/rpc.js";
import { NearStore, type NearAccountRecord } from "../src/near/store.js";
import { Store } from "../src/store.js";

const KEY = randomBytes(32).toString("base64");
const config = (signer: NearConfig["signer"] = "sealed_key"): NearConfig => loadNearConfig({ NEAR_RPC_URL: "https://rpc.example", NEAR_SIGNER: signer, NEAR_KEY_ENCRYPTION_KEY: KEY })!;

function memoryStore() {
  const rows = new Map<string, NearAccountRecord>();
  return {
    rows,
    async account(userId: string, network: string) { return rows.get(`${userId}:${network}`) ?? null; },
    async saveAccount(a: NearAccountRecord) { const k = `${a.userId}:${a.network}`; if (!rows.has(k)) rows.set(k, a); return rows.get(k)!; },
  };
}

function rpc(view: unknown, keys: unknown[] = []) {
  return new NearRpc("https://rpc.example", "mainnet", (async (_u: string, init: RequestInit) => {
    const b = JSON.parse(String(init.body));
    const result = b.method === "status" ? { chain_id: "mainnet" } : b.params.request_type === "view_account" ? view : { keys };
    return new Response(JSON.stringify(result === null ? { error: { cause: { name: "UNKNOWN_ACCOUNT" } } } : { result }));
  }) as typeof fetch);
}

test("config: NEAR stays disabled without an RPC and requires a sealing key for sealed_key", () => {
  assert.equal(loadNearConfig({}), null);
  assert.throws(() => loadNearConfig({ NEAR_RPC_URL: "https://rpc.example" }), /NEAR_KEY_ENCRYPTION_KEY/);
  assert.throws(() => loadNearConfig({ NEAR_RPC_URL: "http://rpc.example", NEAR_KEY_ENCRYPTION_KEY: KEY }), /HTTPS/);
  const c = config();
  assert.equal(c.network, "mainnet");
  assert.equal(c.mpcContract, "v1.signer");
  assert.equal(loadNearConfig({ NEAR_RPC_URL: "https://r.example", NEAR_NETWORK: "testnet", NEAR_SIGNER: "cdp_solana" })!.mpcContract, "v1.signer-prod.testnet");
});

test("account: created once per user, stable, isolated between users, and signs for its own key", async () => {
  const store = memoryStore();
  const service = new NearAccountService(config(), store, rpc(null));
  const a = await service.account("user-a");
  assert.deepEqual(await service.account("user-a"), a);
  const b = await service.account("user-b");
  assert.notEqual(a.accountId, b.accountId);
  assert.match(a.accountId, /^[0-9a-f]{64}$/);
  const signer = await service.signer(a);
  assert.equal(implicitAccountId(signer.publicKey), a.accountId);
  const msg = randomBytes(32);
  assert.ok(verifyEd25519(signer.publicKey, msg, await signer.sign(msg)));
  await assert.rejects(service.signer({ ...a, sealedKey: b.sealedKey }), "another user's sealed key never opens for this account");
  await assert.rejects(service.signer({ ...a, accountId: b.accountId }), /registry mismatch/);
});

test("account: CDP ed25519 key becomes the implicit account and the record keeps its signer kind", async () => {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const address = baseEncode(Buffer.from(publicKey.export({ format: "jwk" }).x!, "base64url"));
  const names: string[] = [];
  const cdp: CdpSolanaApi = { async getOrCreateAccount({ name }) { names.push(name); return { address }; }, async signMessage({ message }) { return { signature: baseEncode(edSign(null, Buffer.from(message, "base64"), privateKey)) }; } };
  const store = memoryStore();
  const record = await new NearAccountService(config("cdp_solana"), store, rpc(null), cdp).account("user-c");
  assert.equal(record.signerKind, "cdp_solana");
  assert.equal(record.sealedKey, null);
  assert.match(names[0]!, /^near-v1-/);
  // A later default change does not move an existing account to another key.
  const later = new NearAccountService(config("sealed_key"), store, rpc(null), cdp);
  assert.equal((await later.account("user-c")).accountId, record.accountId);
  assert.equal((await later.signer(record)).kind, "cdp_solana");
});

test("status: inactive implicit account explains first funding; active account reports spendable balance", async () => {
  const store = memoryStore();
  const inactive = await new NearAccountService(config(), store, rpc(null)).status("user-d");
  assert.equal(inactive.exists_on_chain, false);
  assert.match(inactive.receive, /not active yet/);
  const rec = (await store.account("user-d", "mainnet"))!;
  const active = await new NearAccountService(config(), store, rpc({ amount: "2000000000000000000000000", locked: "0", storage_usage: 182, code_hash: "11111111111111111111111111111111", block_height: 1, block_hash: "x" }, [{ public_key: rec.publicKey, access_key: { nonce: 1, permission: "FullAccess" } }, { public_key: "ed25519:other", access_key: { nonce: 1, permission: "FullAccess" } }])).status("user-d");
  assert.equal(active.exists_on_chain, true);
  assert.equal(active.balance.storage_locked_yocto, "1820000000000000000000");
  assert.equal(active.balance.available_yocto, "1998180000000000000000000");
  assert.equal(active.service_key_active, true);
  assert.ok(active.warning);
});

test("Postgres: one NEAR account per user under concurrent creation; preview single-use and per-account serialization", { skip: !process.env.TEST_DATABASE_URL }, async () => {
  const db = new Store(process.env.TEST_DATABASE_URL!);
  try {
    await db.migrate();
    const store = new NearStore(db.pool);
    const user = await db.upsertIdentity("github", `near-${randomUUID()}`, null, null);
    const service = new NearAccountService(config(), store, rpc(null));
    const created = await Promise.all([service.account(user), service.account(user), service.account(user)]);
    assert.equal(new Set(created.map(c => c.accountId)).size, 1);
    const acct = created[0]!;
    const base = { userId: user, network: "mainnet" as const, accountId: acct.accountId, publicKey: acct.publicKey, kind: "near_tx" as const, receiverId: "bob.near", actions: [{ type: "transfer" as const, amount: "1" }], descriptions: [], plan: null, fingerprint: "f" };
    const one = await store.createOperation(base, 600);
    const two = await store.createOperation(base, 600);
    const results = await Promise.allSettled([store.reserve(user, one.id, "near_tx", "test"), store.reserve(user, one.id, "near_tx", "test")]);
    assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
    await assert.rejects(store.reserve(user, two.id, "near_tx", "test"), /unresolved NEAR operation/);
    await assert.rejects(store.reserve(user, two.id, "chain_signature", "test"), /type does not match/);
    const stranger = await db.upsertIdentity("github", `near-${randomUUID()}`, null, null);
    await assert.rejects(store.reserve(stranger, two.id, "near_tx", "test"), /not found/);
    await store.markSigning(user, one.id, "5", "hash", "signed");
    await assert.rejects(store.markSigning(user, one.id, "6", "hash2", "signed2"), /no longer available/);
    await store.update(user, one.id, { status: "confirmed", outcome: { ok: true } });
    assert.equal((await store.reserve(user, two.id, "near_tx", "test")).status, "reserved");
    const expired = await store.createOperation(base, 30);
    await db.pool.query("UPDATE near_operations SET expires_at=now()-interval '1 second' WHERE id=$1", [expired.id]);
    await store.update(user, two.id, { status: "failed", error: "x" });
    await assert.rejects(store.reserve(user, expired.id, "near_tx", "test"), /expired/);
  } finally { await db.close(); }
});
