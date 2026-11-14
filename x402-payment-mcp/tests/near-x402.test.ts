import assert from "node:assert/strict";
import test from "node:test";
import { hashTypedData, recoverTypedDataAddress } from "viem";
import { InMemoryTransport } from "@modelcontextprotocol/server";
import { authorizationTypedData, paymentBinding } from "../src/near/x402.js";
import { createNearMcp } from "../src/near/mcp.js";
import { NEAR_SCOPE, NEAR_X402_SCOPE } from "../src/security.js";
import { paymentWorld } from "./near-x402-fakes.js";

const request = { url: "https://api.example.com/data", body: { question: "BTC" }, headers: { authorization: "Bearer PRIVATE-API-KEY" } };
const preview = (w: ReturnType<typeof paymentWorld>) => w.service.preview("u", request);

test("NEAR x402: preview estimates NEAR gas but never signs; exact request, derived payer and USDC are shown", async () => {
  const w = paymentWorld(), p = await preview(w);
  assert.equal(p.payer_address, w.mpc.address);
  assert.equal(p.payment.amount_atomic, "1000");
  assert.equal(p.payment.authorization_window_seconds, 120);
  assert.equal(p.request.method, "POST");
  assert.deepEqual(p.request.header_names, ["authorization"]);
  assert.equal(w.state.signs.length, 0); assert.equal(w.state.sends.length, 0);
  assert.equal(w.rows.get(p.preview_id)!.plan.authorization, undefined);
  assert.doesNotMatch(JSON.stringify(p), /PRIVATE-API-KEY/);
});

test("NEAR x402: full NEAR transaction/MPC roundtrip signs EIP-712, pays once, verifies USDC receipt and returns API data", async () => {
  const w = paymentWorld(), p = await preview(w);
  w.advance(180); // User approval time must not consume the authorization window.
  const paid = await w.service.pay("u", p.preview_id, "buy API data");
  assert.equal(paid.status, "settled"); assert.equal(paid.resource_received, true);
  assert.equal((paid.result as any).data, "paid API result");
  assert.equal(w.state.signs.length, 1); assert.equal(w.state.sends.length, 1);
  const { plan } = w.rows.get(p.preview_id)!;
  assert.equal(BigInt(plan.authorization!.validBefore), BigInt(Math.floor(w.now() / 1000) + 120));
  const signed = w.state.signs[0];
  assert.equal(signed.predecessor, p.near_account_id);
  assert.equal(signed.args.request.path, "agentlayer-evm-1");
  assert.equal(`0x${signed.args.request.payload_v2.Ecdsa}`, hashTypedData(authorizationTypedData(plan.authorization!)));
  assert.equal((await recoverTypedDataAddress({ ...authorizationTypedData(plan.authorization!), signature: plan.signature! })), w.mpc.address);
  assert.equal(plan.signature!.length, 132);
  const sent = w.state.sends[0]!;
  assert.equal(sent.payload.accepted.network, "eip155:8453");
  assert.equal(sent.payload.payload.authorization.nonce, plan.authorization!.nonce);
  assert.equal(new Headers(sent.init.headers).get("authorization"), "Bearer PRIVATE-API-KEY");
  assert.equal(sent.init.body, JSON.stringify(request.body));
  assert.equal(plan.request, null, "credentials scrubbed at dispatch boundary");
  assert.doesNotMatch(JSON.stringify(paid), /PRIVATE-API-KEY|signature|payload_v2/);
  await assert.rejects(w.service.pay("u", p.preview_id, "repeat"), /already consumed/);
  await w.service.status("u", p.preview_id);
  assert.equal(w.state.sends.length, 1);
});

test("NEAR x402: high-S MPC response is normalized with parity inversion; delegated payer uses ERC-1271", async () => {
  const w = paymentWorld(); w.delegate(); w.state.highS = true;
  const p = await preview(w), result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "settled"); assert.equal(w.state.signatureChecks, 1);
  const sig = w.rows.get(p.preview_id)!.plan.signature!;
  assert.ok(BigInt(`0x${sig.slice(66, 130)}`) <= 0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0n);
});

test("NEAR x402: pending MPC resumes after service restart without another nonce, signature request or paid retry", async () => {
  const w = paymentWorld(); w.state.pending = true;
  const p = await preview(w), result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "signing"); assert.equal(w.state.sends.length, 0);
  const nonce = w.rows.get(p.preview_id)!.plan.authorization!.nonce;
  w.state.pending = false;
  const resumed = await w.makeService().status("u", p.preview_id);
  assert.equal(resumed.status, "settled");
  assert.equal(w.rows.get(p.preview_id)!.plan.authorization!.nonce, nonce);
  assert.equal(w.state.signs.length, 1); assert.equal(w.state.sends.length, 1);
});

test("NEAR x402: generic operation status withholds MPC signature and authorization", async () => {
  const w = paymentWorld(); w.state.pending = true;
  const p = await preview(w); await w.service.pay("u", p.preview_id, "API purchase");
  w.state.pending = false; await w.service.status("u", p.preview_id);
  const generic = await w.operations.status("u", p.preview_id);
  assert.match(JSON.stringify(generic), /x402_status/);
  assert.doesNotMatch(JSON.stringify(generic), /return_value|affine_point|scalar|signature|nonce/);
  await assert.rejects(w.operations.execute("u", p.preview_id, "generic bypass"), /type does not match/);
});

test("NEAR x402: timeout after dispatch stays unknown, blocks another payment and never resends", async () => {
  const w = paymentWorld(); w.state.timeout = true; w.state.settle = false;
  const p = await preview(w); assert.equal((await w.service.pay("u", p.preview_id, "API purchase")).status, "unknown");
  const next = await preview(w);
  await assert.rejects(w.service.pay("u", next.preview_id, "second purchase"), /unresolved/);
  await w.makeService().status("u", p.preview_id); await w.service.status("u", p.preview_id);
  assert.equal(w.state.sends.length, 1); assert.equal(w.state.signs.length, 1);
});

test("NEAR x402: lost API response is reconciled from on-chain nonce and Transfer, independently of resource delivery", async () => {
  const w = paymentWorld(); w.state.timeout = true;
  const p = await preview(w), result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "settled"); assert.equal(result.resource_received, undefined);
  assert.equal(w.state.sends.length, 1);
  await w.service.status("u", p.preview_id); assert.equal(w.state.sends.length, 1);
});

test("NEAR x402: untrusted settlement header cannot hide the actual on-chain payment", async () => {
  const w = paymentWorld(); w.state.fakeHeader = true;
  const p = await preview(w), result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "settled"); assert.equal(result.transaction, `0x${"ab".repeat(32)}`);
});

for (const mismatch of ["amount", "token", "no_receipt"] as const) test(`NEAR x402: reported success without matching ${mismatch} proof is unknown`, async () => {
  const w = paymentWorld();
  if (mismatch === "amount") w.state.receiptAmount = 999n;
  if (mismatch === "token") w.state.receiptToken = "0x2222222222222222222222222222222222222222";
  if (mismatch === "no_receipt") w.state.settle = false;
  const p = await preview(w), result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "unknown");
});

test("NEAR x402: a used nonce caused by cancellation is not reported as paid", async () => {
  const w = paymentWorld(); w.state.settle = false;
  const p = await preview(w); await w.service.pay("u", p.preview_id, "API purchase");
  w.state.canceled = true; w.state.finalTimestamp = BigInt(Math.floor(w.now() / 1000));
  assert.equal((await w.service.status("u", p.preview_id)).status, "cancelled");
});

test("NEAR x402: only finalized expiry without consumption releases an unknown payment", async () => {
  const w = paymentWorld(); w.state.settle = false;
  const p = await preview(w); await w.service.pay("u", p.preview_id, "API purchase");
  w.advance(180);
  assert.equal((await w.service.status("u", p.preview_id)).status, "unknown", "wall clock alone cannot release authorization");
  w.state.rpcDown = true;
  assert.equal((await w.service.status("u", p.preview_id)).status, "unknown");
  w.state.rpcDown = false; w.state.finalTimestamp = BigInt(Math.floor(w.now() / 1000));
  assert.equal((await w.service.status("u", p.preview_id)).status, "expired");
});

for (const failure of ["wrongSigner", "malformed", "simulationFails"] as const) test(`NEAR x402: ${failure} prevents paid HTTP dispatch`, async () => {
  const w = paymentWorld(); w.state[failure] = true;
  const p = await preview(w), result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "failed"); assert.equal(w.state.sends.length, 0);
});

test("NEAR x402: authorization expiring during MPC is never dispatched or silently replaced", async () => {
  const w = paymentWorld(); w.state.advanceDuringSign = 115;
  const p = await preview(w), result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "expired"); assert.equal(w.state.signs.length, 1); assert.equal(w.state.sends.length, 0);
});

test("NEAR x402: concurrent pay calls consume a preview once", async () => {
  const w = paymentWorld(), p = await preview(w);
  const results = await Promise.allSettled([w.service.pay("u", p.preview_id, "purchase one"), w.service.pay("u", p.preview_id, "purchase two")]);
  assert.equal(results.filter(r => r.status === "fulfilled").length, 1);
  assert.equal(w.state.signs.length, 1); assert.equal(w.state.sends.length, 1);
});

test("NEAR x402: preview ownership, expiration and changed request/account are rejected before signing", async () => {
  for (const change of ["user", "expired", "body", "headers", "payer", "path", "amount"] as const) {
    const w = paymentWorld(), p = await preview(w), row = w.rows.get(p.preview_id)!;
    if (change === "expired") w.advance(601);
    if (change === "body") row.plan.request!.body = { question: "other" };
    if (change === "headers") row.plan.request!.headers!.authorization = "other";
    if (change === "payer") row.plan.payer = "0x2222222222222222222222222222222222222222";
    if (change === "path") row.plan.path = "other";
    if (change === "amount") row.plan.terms.amount = "2000";
    if (change === "user" || change === "expired") await assert.rejects(w.service.pay(change === "user" ? "stranger" : "u", p.preview_id, "purchase"));
    else assert.equal((await w.service.pay("u", p.preview_id, "purchase")).status, "failed");
    assert.equal(w.state.signs.length, 0, change); assert.equal(w.state.sends.length, 0, change);
  }
});

test("NEAR x402: persisted nonce/digest tampering cannot resume a different authorization", async () => {
  const w = paymentWorld(); w.state.pending = true;
  const p = await preview(w); await w.service.pay("u", p.preview_id, "purchase");
  const row = w.rows.get(p.preview_id)!;
  row.plan.authorization!.nonce = `0x${"99".repeat(32)}`;
  row.plan.digest = hashTypedData(authorizationTypedData(row.plan.authorization!));
  w.state.pending = false;
  await assert.rejects(w.service.status("u", p.preview_id), /stored authorization/);
  assert.equal(w.state.sends.length, 0); assert.equal(w.state.signs.length, 1);
});

test("NEAR x402: insufficient balance, wrong chain and unknown delegate stop before MPC", async () => {
  for (const cause of ["usdc", "near", "chain", "delegate"] as const) {
    const w = paymentWorld();
    if (cause === "usdc") w.state.balance = 0n;
    if (cause === "near") w.state.nearBalance = 1n;
    if (cause === "chain") w.state.chainId = 1;
    if (cause === "delegate") w.state.delegate = "0x2222222222222222222222222222222222222222";
    await assert.rejects(preview(w)); assert.equal(w.state.signs.length, 0);
  }
});

test("NEAR x402: unsupported terms and per-payment limit are rejected at preview", async () => {
  for (const mutate of [
    (r: any) => { r.scheme = "upto"; }, (r: any) => { r.network = "eip155:1"; },
    (r: any) => { r.extra.assetTransferMethod = "permit2"; }, (r: any) => { r.extra.name = "Fake USDC"; },
    (r: any) => { r.extra.version = "1"; }, (r: any) => { r.maxTimeoutSeconds = 5; },
    (r: any) => { r.amount = "1000001"; }, (r: any) => { r.payTo = "0x0000000000000000000000000000000000000000"; },
  ]) {
    const w = paymentWorld(); mutate(w.terms); await assert.rejects(preview(w)); assert.equal(w.rows.size, 0);
  }
});

test("NEAR x402: daily budget keeps settled and unknown payments reserved", async () => {
  const w = paymentWorld(); w.config.MAX_DAILY_USDC_ATOMIC = "1500";
  const p = await preview(w); await w.service.pay("u", p.preview_id, "purchase");
  const next = await preview(w);
  await assert.rejects(w.service.pay("u", next.preview_id, "another purchase"), /daily spend limit/);
  assert.equal(w.state.signs.length, 1);
});

test("NEAR x402: dispatch-boundary crash never repeats HTTP after restart", async () => {
  const w = paymentWorld(), p = await preview(w);
  const update = w.paymentStore.update.bind(w.paymentStore);
  w.paymentStore.update = async (...args) => { const result = await update(...args); if (args[2] === "sending") throw new Error("process crashed after durable dispatch boundary"); return result; };
  await assert.rejects(w.service.pay("u", p.preview_id, "purchase"), /crashed/);
  assert.equal(w.rows.get(p.preview_id)!.status, "sending");
  w.paymentStore.update = update;
  assert.equal((await w.makeService().status("u", p.preview_id)).status, "sending");
  assert.equal(w.state.sends.length, 0, "uncertainty sacrifices delivery instead of duplicating a purchase");
  assert.equal(w.state.signs.length, 1);
});

test("NEAR x402: MCP tools require the separate grant; old grants have no new payment tools", async () => {
  for (const allowed of [false, true]) {
    const w = paymentWorld();
    const [client, server] = InMemoryTransport.createLinkedPair();
    const pending = new Map<number, (v: any) => void>(); let id = 0;
    client.onmessage = (m: any) => { pending.get(m.id)?.(m); pending.delete(m.id); };
    const mcp = createNearMcp("u", { accounts: w.accounts, operations: w.operations, chainSignatures: {} as any, payments: w.service }, allowed ? [NEAR_SCOPE, NEAR_X402_SCOPE] : [NEAR_SCOPE]);
    await mcp.connect(server); await client.start();
    const call = (method: string, params = {}) => new Promise<any>(r => { const n = ++id; pending.set(n, r); void client.send({ jsonrpc: "2.0", id: n, method, params } as any); });
    await call("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } } as any);
    const names = (await call("tools/list")).result.tools.map((t: any) => t.name).filter((n: string) => n.startsWith("x402_"));
    assert.deepEqual(names.sort(), allowed ? ["x402_pay", "x402_preview", "x402_search", "x402_status"] : []);
    const response = await call("tools/call", { name: "x402_preview", arguments: request } as any);
    assert.equal(Boolean(response.result?.structuredContent?.preview_id), allowed);
    await client.close(); await mcp.close();
  }
});


test("NEAR x402: increased NEAR fee needs a new preview and never requests MPC", async () => {
  const w = paymentWorld(), p = await preview(w);
  w.state.gasPrice = "200000000";
  const result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "failed"); assert.match(String(result.failure_reason), /fee increased/);
  assert.equal(w.state.signs.length, 0); assert.equal(w.state.sends.length, 0);
});


test("NEAR x402: provider price changes never trigger a second authorization or paid retry", async () => {
  const w = paymentWorld(), p = await preview(w);
  w.terms.amount = "2000"; w.state.settle = false; w.state.responseStatus = 402;
  const result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "unknown"); assert.equal(result.response_status, 402);
  assert.equal(w.state.sends[0]!.payload.payload.authorization.value, "1000");
  await w.service.status("u", p.preview_id);
  assert.equal(w.state.signs.length, 1); assert.equal(w.state.sends.length, 1);
});

test("NEAR x402: changed Base RPC cannot reconcile an authorization on the wrong chain", async () => {
  const w = paymentWorld(), p = await preview(w);
  w.state.settle = false;
  await w.service.pay("u", p.preview_id, "API purchase");
  w.state.chainId = 1; w.state.finalTimestamp = BigInt(Math.floor(w.now() / 1000) + 300);
  assert.equal((await w.service.status("u", p.preview_id)).status, "unknown");
});


test("NEAR x402: delegated preview warns about facilitator compatibility without claiming failure", async () => {
  const w = paymentWorld(); w.delegate();
  const p = await preview(w);
  assert.equal(p.payer_account.type, "eip7702_delegated");
  assert.match(p.payer_account.warning!, /reject delegated accounts/);
  assert.equal(w.state.signs.length, 0);
});

test("NEAR x402: unknown status exposes deadline and sanitized reconciliation diagnostics", async () => {
  const w = paymentWorld(); w.state.settle = false; w.state.responseStatus = 402;
  const p = await preview(w); const result = await w.service.pay("u", p.preview_id, "API purchase");
  assert.equal(result.status, "unknown");
  assert.equal(result.authorization_valid_before_unix, w.rows.get(p.preview_id)!.plan.authorization!.validBefore);
  assert.deepEqual(result.reconciliation, { state: "awaiting_finalized_proof" });
  w.state.rpcDown = true;
  const pending = await w.service.status("u", p.preview_id);
  assert.equal(pending.status, "unknown");
  assert.deepEqual(pending.reconciliation, { state: "rpc_unavailable_or_incomplete", check: "latest_block_and_authorization_logs" });
  assert.doesNotMatch(JSON.stringify(pending), /RPC down|SECRET|signature|nonce/);
  assert.equal(w.state.sends.length, 1);
});
