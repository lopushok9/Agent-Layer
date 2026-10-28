import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import { DappService } from "../src/dapps.js";
import { DappStore, type DappProposal, type DappRequest, type DappSession } from "../src/dapp-store.js";
import { PgKeyValueStorage } from "../src/walletconnect-storage.js";
import { Store } from "../src/store.js";

const account = "0x1111111111111111111111111111111111111111";
const target = "0x2222222222222222222222222222222222222222";
const topic = "a".repeat(64), pairing = "b".repeat(64);
const uri = `wc:${pairing}@2?relay-protocol=irn&symKey=${"c".repeat(64)}&expiryTimestamp=${Math.floor(Date.now() / 1000) + 300}`;
const txHash = `0x${"d".repeat(64)}`;
const tick = () => new Promise(r => setImmediate(r));

function memoryStore() {
  const proposals = new Map<string, DappProposal>(), sessionRows = new Map<string, DappSession>(), requests = new Map<string, DappRequest>();
  return {
    proposals, requests,
    saveProposal: async (p: any) => { proposals.set(p.id, { ...p, status: "pending" }); },
    proposal: async (u: string, id: string) => { const p = proposals.get(id); return p?.userId === u ? p : null; },
    settleProposal: async (u: string, id: string, status: any) => { const p = proposals.get(id); if (p?.userId !== u || p.status !== "pending") return false; p.status = status; return true; },
    saveSession: async (s: any) => { sessionRows.set(s.topic, { ...s, endedAt: null }); },
    session: async (t: string) => sessionRows.get(t) ?? null,
    sessions: async (u: string) => [...sessionRows.values()].filter(s => s.userId === u && !s.endedAt),
    endSession: async (t: string) => { const s = sessionRows.get(t); if (s) s.endedAt = new Date(); },
    saveRequest: async (r: any) => { if ([...requests.values()].some(x => x.topic === r.topic && x.rpcId === r.rpcId)) return null; const x = { ...r, id: `00000000-0000-4000-8000-${String(requests.size).padStart(12, "0")}`, status: "pending", operationId: null, signatureId: null, error: null, createdAt: new Date() }; requests.set(x.id, x); return x; },
    request: async (u: string, id: string) => { const r = requests.get(id); return r?.userId === u ? { ...r } : null; },
    requestByOperation: async (u: string, op: string) => [...requests.values()].find(r => r.userId === u && r.operationId === op) ?? null,
    openRequests: async (u: string) => [...requests.values()].filter(r => r.userId === u && ["pending", "prepared", "submitted"].includes(r.status)),
    attachPreview: async (_u: string, id: string, link: any) => { Object.assign(requests.get(id)!, { status: "prepared", operationId: link.operationId ?? null, signatureId: link.signatureId ?? null }); },
    setRequestStatus: async (id: string, status: any, from: any[], error: string | null = null) => { const r = requests.get(id)!; if (!from.includes(r.status)) return false; r.status = status; r.error = error; return true; },
  };
}

function harness(verify: Record<string, unknown> = { validation: "VALID", origin: "https://app.example.com" }) {
  const events = new EventEmitter(); const responses: any[] = []; const approvals: any[] = []; const rejections: any[] = [];
  const client = {
    on: (e: string, l: (a: any) => unknown) => events.on(e, l),
    pair: async () => { setImmediate(() => events.emit("session_proposal", { id: 1730000000000001, params: { id: 1730000000000001, pairingTopic: pairing, expiryTimestamp: Math.floor(Date.now() / 1000) + 300, requiredNamespaces: {}, optionalNamespaces: { eip155: { chains: ["eip155:8453", "eip155:10"], methods: ["eth_sendTransaction", "personal_sign", "wallet_sendCalls"], events: ["accountsChanged"] } }, relays: [{ protocol: "irn" }], proposer: { publicKey: "00", metadata: { name: "Example", url: "https://app.example.com", description: "d", icons: [] } } }, verifyContext: { verified: verify } })); },
    approveSession: async (p: any) => { approvals.push(p); return { topic, expiry: Math.floor(Date.now() / 1000) + 86400, peer: { metadata: { name: "Example", url: "https://app.example.com" } } }; },
    rejectSession: async (p: any) => { rejections.push(p); },
    respondSessionRequest: async (p: any) => { responses.push(p); },
    disconnectSession: async () => {},
  };
  const store = memoryStore();
  let opStatus = "submitted";
  const calls: any = { prepare: [], execute: [], sign: [] };
  const transactions = {
    prepare: async (_u: string, input: any) => { calls.prepare.push(input); return { operation_id: "11111111-1111-4111-8111-111111111111" }; },
    execute: async (_u: string, id: string) => { calls.execute.push(id); return { operation_id: id, status: "submitted", user_op_hash: `0x${"e".repeat(64)}` }; },
    status: async () => ({ status: opStatus, transaction_hash: opStatus === "confirmed" || opStatus === "failed" ? txHash : null }),
  };
  const signatures = {
    prepare: async (_u: string, input: any, origin?: string) => { calls.sign.push({ input, origin }); return { signature_id: "22222222-2222-4222-8222-222222222222" }; },
    execute: async () => ({ signature: "0xsig" }),
  };
  const wallets = { account: async () => ({ address: account }), rpc: () => ({ getTransactionReceipt: async () => ({ logs: [{ address: target, data: "0x", topics: [] }], blockHash: `0x${"f".repeat(64)}`, blockNumber: 10n, gasUsed: 21000n, transactionHash: txHash }) }) };
  const service = new DappService(client as any, store as unknown as DappStore, wallets as any, transactions as any, signatures as any, async () => { opStatus = "confirmed"; });
  const request = async (id: number, method: string, params: unknown, chainId = "eip155:8453", t = topic) => { events.emit("session_request", { id, topic: t, params: { chainId, request: { method, params } }, verifyContext: { verified: verify } }); await tick(); await tick(); return responses.find(r => r.response.id === id)?.response; };
  return { service, store, responses, approvals, rejections, calls, request, setStatus: (s: string) => { opStatus = s; } };
}

async function connected(h: ReturnType<typeof harness>) {
  const p = await h.service.connect("alice", uri) as { proposal_id: string };
  return h.service.respondProposal("alice", p.proposal_id, true);
}

test("connecting shows the app and Verify result, then approves only supported chains and methods for the smart account", async () => {
  const h = harness();
  await assert.rejects(h.service.connect("alice", "https://example.com"), /not a WalletConnect v2 pairing URI/);
  const p = await h.service.connect("alice", uri) as any;
  assert.equal(p.app.name, "Example"); assert.equal(p.verification.validation, "VALID"); assert.equal(p.verification.origin, "https://app.example.com");
  await assert.rejects(h.service.respondProposal("bob", p.proposal_id, true), /not found/);
  const s = await h.service.respondProposal("alice", p.proposal_id, true);
  await assert.rejects(h.service.respondProposal("alice", p.proposal_id, true), /already answered/);
  const ns = h.approvals[0].namespaces.eip155;
  assert.deepEqual(ns.chains, ["eip155:8453"], "only the requested chains this wallet supports");
  assert.deepEqual(ns.accounts, [`eip155:8453:${account}`]);
  assert.ok(!ns.methods.includes("eth_sign"));
  assert.equal(s.session_topic, topic);
});

test("known scams and impersonating origins are refused before any session exists", async () => {
  for (const verify of [{ validation: "VALID", origin: "https://app.example.com", isScam: true }, { validation: "INVALID", origin: "https://evil.example.net" }]) {
    const h = harness(verify);
    await assert.rejects(h.service.connect("alice", uri), /connection refused/);
    assert.equal(h.rejections.length, 1); assert.equal(h.approvals.length, 0); assert.equal(h.store.proposals.size, 0);
  }
});

test("read-only methods are answered, unsafe or malformed requests are refused, and nothing reaches the user queue", async () => {
  const h = harness(); await connected(h);
  assert.equal((await h.request(1, "eth_chainId", []))?.result, "0x2105");
  assert.deepEqual((await h.request(2, "eth_accounts", []))?.result, [account]);
  assert.deepEqual((await h.request(3, "wallet_getCapabilities", [account, ["0x2105"]]))?.result, { "0x2105": { atomic: { status: "supported" } } });
  assert.equal((await h.request(4, "eth_sign", [account, "0x" + "00".repeat(32)]))?.error.code, 4200);
  assert.equal((await h.request(5, "eth_sendTransaction", [{ from: target, to: target }]))?.error.code, -32602);
  assert.equal((await h.request(6, "eth_sendTransaction", [{ from: account, data: "0x60" }]))?.error.code, 4200, "contract deployment");
  assert.equal((await h.request(7, "wallet_sendCalls", [{ version: "2.0.0", chainId: "0x2105", from: account, calls: [{ to: target }], capabilities: { paymasterService: { url: "https://pm.example" } } }]))?.error.code, 5700);
  assert.equal((await h.request(8, "eth_chainId", [], "eip155:10"))?.error.code, 4901);
  assert.equal((await h.request(9, "eth_chainId", [], "eip155:8453", "9".repeat(64)))?.error.code, 4100);
  assert.equal((await h.request(10, "wallet_getCallsStatus", ["nope"]))?.error.code, 5730);
  assert.equal(h.store.requests.size, 0);
});

test("eth_sendTransaction becomes a normal preview, executes once, and answers with the transaction hash after inclusion", async () => {
  const h = harness(); await connected(h);
  assert.equal(await h.request(20, "eth_sendTransaction", [{ from: account, to: target, value: "0x0de0b6b3a7640000", data: "0xabcdef01" }]), undefined, "held for the user");
  await h.request(20, "eth_sendTransaction", [{ from: account, to: target, value: "0x1" }]);
  assert.equal(h.store.requests.size, 1, "a redelivered request id is one request");
  const [r] = (await h.service.requests("alice")).requests;
  assert.deepEqual((await h.service.requests("bob")).requests, []);
  await h.service.prepareRequest("alice", r!.request_id);
  assert.deepEqual(h.calls.prepare[0], { network: "base", calls: [{ to: target, value: "1000000000000000000", data: "0xabcdef01" }] });
  const out = await h.service.executeRequest("alice", r!.request_id, "swap in app");
  assert.equal(out.app_response, "sent");
  assert.equal(h.responses.find(x => x.response.id === 20)?.response.result, txHash);
  await assert.rejects(h.service.executeRequest("alice", r!.request_id, "again"), /app request is responded/);
  assert.equal(h.calls.execute.length, 1);
});

test("wallet_sendCalls answers with the operation id and wallet_getCallsStatus reports EIP-5792 status and receipts", async () => {
  const h = harness(); await connected(h);
  await h.request(30, "wallet_sendCalls", [{ version: "2.0.0", chainId: "0x2105", from: account, atomicRequired: true, calls: [{ to: target, data: "0x01" }, { to: target, value: "0x5" }], capabilities: { atomic: { optional: false } } }]);
  const [r] = (await h.service.requests("alice")).requests;
  await h.service.prepareRequest("alice", r!.request_id);
  assert.equal(h.calls.prepare[0].calls.length, 2);
  await h.service.executeRequest("alice", r!.request_id, "batch");
  const id = h.responses.find(x => x.response.id === 30)?.response.result.id;
  assert.equal(id, "11111111-1111-4111-8111-111111111111");
  assert.equal((await h.request(31, "wallet_getCallsStatus", [id]))?.result.status, 100);
  h.setStatus("confirmed");
  const done = (await h.request(32, "wallet_getCallsStatus", [id]))?.result;
  assert.equal(done.status, 200); assert.equal(done.atomic, true); assert.equal(done.receipts[0].transactionHash, txHash); assert.equal(done.receipts[0].status, "0x1");
});

test("signature requests go through signature previews with the verified origin, and rejection answers 4001", async () => {
  const h = harness(); await connected(h);
  await h.request(40, "personal_sign", ["0x68656c6c6f", account]);
  await h.request(41, "eth_signTypedData_v4", [account, JSON.stringify({ domain: { chainId: 8453 }, types: {}, primaryType: "X", message: {} })]);
  const [sign, typed] = (await h.service.requests("alice")).requests;
  await h.service.prepareRequest("alice", sign!.request_id);
  assert.deepEqual(h.calls.sign[0], { input: { network: "base", message_hex: "0x68656c6c6f" }, origin: "https://app.example.com" });
  await h.service.executeRequest("alice", sign!.request_id, "login");
  assert.equal(h.responses.find(x => x.response.id === 40)?.response.result, "0xsig");
  await h.service.rejectRequest("alice", typed!.request_id);
  assert.equal(h.responses.find(x => x.response.id === 41)?.response.error.code, 4001);
});

test("an expired app request cannot be prepared, and a disconnected session cannot be used", async () => {
  const h = harness(); await connected(h);
  await h.request(50, "personal_sign", ["0x68656c6c6f", account]);
  const r = [...h.store.requests.values()][0]!; r.expiresAt = new Date(Date.now() - 1000);
  await assert.rejects(h.service.prepareRequest("alice", r.id), /request expired/);
  assert.equal(r.status, "expired");
  await h.service.disconnect("alice", topic);
  assert.equal((await h.request(51, "eth_chainId", []))?.error.code, 4100);
});

test("Postgres: WalletConnect storage is encrypted at rest and app requests are deduplicated and single-transition", { skip: !process.env.TEST_DATABASE_URL }, async () => {
  const db = new Store(process.env.TEST_DATABASE_URL!);
  try {
    await db.migrate();
    const key = Buffer.alloc(32, 7).toString("base64");
    const kv = new PgKeyValueStorage(db.pool, key);
    const k = `wc@2:test:${Date.now()}`;
    await kv.setItem(k, { symKey: "secret-sym-key" });
    const raw = await db.pool.query("SELECT value FROM walletconnect_storage WHERE key=$1", [k]);
    assert.ok(!raw.rows[0].value.includes("secret-sym-key"));
    assert.deepEqual(await new PgKeyValueStorage(db.pool, key).getItem(k), { symKey: "secret-sym-key" });
    await assert.rejects(new PgKeyValueStorage(db.pool, Buffer.alloc(32, 8).toString("base64")).getItem(k));
    await kv.removeItem(k);
    const userId = await db.upsertIdentity("github", `dapp-${Date.now()}`, "Dapp", null);
    const store = new DappStore(db.pool);
    const t = Date.now().toString(16).padStart(64, "0");
    await store.saveSession({ topic: t, userId, address: account, app: { name: "x", url: "https://x" }, verification: { validation: "UNKNOWN" }, expiresAt: new Date(Date.now() + 60_000) });
    const base = { userId, topic: t, rpcId: "1", method: "personal_sign", network: "base" as const, params: ["0x00", account], expiresAt: new Date(Date.now() + 60_000) };
    assert.ok(await store.saveRequest(base));
    assert.equal(await store.saveRequest(base), null, "redelivery is ignored");
    const r = (await store.openRequests(userId))[0]!;
    const moves = await Promise.all([1, 2, 3].map(() => store.setRequestStatus(r.id, "responded", ["pending"])));
    assert.equal(moves.filter(Boolean).length, 1);
    await store.endSession(t);
    assert.deepEqual(await store.sessions(userId), []);
  } finally { await db.close(); }
});
