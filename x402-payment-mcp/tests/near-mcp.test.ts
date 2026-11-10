import assert from "node:assert/strict";
import test from "node:test";
import express from "express";
import type { AddressInfo } from "node:net";
import { exportJWK, generateKeyPair } from "jose";
import { InMemoryTransport } from "@modelcontextprotocol/server";
import { createTokenVerifier } from "../src/auth.js";
import type { Config } from "../src/config.js";
import { createNearMcp, NEAR_INSTRUCTIONS } from "../src/near/mcp.js";
import { NearPublicError } from "../src/near/operations.js";
import { oauthRouter } from "../src/oauth.js";
import { NEAR_SCOPE, pkceChallenge, TokenService } from "../src/security.js";
import type { LoginState, OAuthClient, Store } from "../src/store.js";

async function config(nearEnabled = true): Promise<Config> {
  const { privateKey } = await generateKeyPair("ES256", { extractable: true });
  return { issuer: "https://pay.example", resource: "https://pay.example/mcp", nearResource: "https://pay.example/near/mcp", nearEnabled, privateJwk: await exportJWK(privateKey), ACCESS_TOKEN_TTL_SECONDS: 900, AUTH_CODE_TTL_SECONDS: 300, GITHUB_CLIENT_ID: "g", GITHUB_CLIENT_SECRET: "g" } as unknown as Config;
}

test("tokens: near:transact tokens are audience-bound to /near/mcp and never accepted by /mcp (and vice versa)", async () => {
  const c = await config();
  const tokens = await TokenService.create(c);
  const near = await tokens.accessToken("u", "client", [NEAR_SCOPE]);
  const x402 = await tokens.accessToken("u", "client", ["x402:pay", "wallet:transact"]);
  const store = { verifyPersonalToken: async () => ({ id: "p", userId: "u", scope: "x402:pay", expiresAt: new Date(Date.now() + 1e6) }) } as any;
  const nearVerifier = createTokenVerifier(c, tokens, store, c.nearResource);
  const mainVerifier = createTokenVerifier(c, tokens, store);
  assert.deepEqual((await nearVerifier.verifyAccessToken(near)).scopes, [NEAR_SCOPE]);
  assert.equal(String((await nearVerifier.verifyAccessToken(near)).resource), c.nearResource);
  await assert.rejects(mainVerifier.verifyAccessToken(near));
  await assert.rejects(nearVerifier.verifyAccessToken(x402));
  await assert.rejects(nearVerifier.verifyAccessToken("alx402_personal"), /personal access tokens/);
  assert.ok(await mainVerifier.verifyAccessToken("alx402_personal"));
});

async function authorize(c: Config, params: Record<string, string>) {
  const client: OAuthClient = { clientId: "c", clientName: "Client", redirectUris: ["https://client.example/cb"] };
  let saved: Omit<LoginState, "id"> | null = null;
  const store = { getClient: async () => client, consumeRateLimit: async () => true, createLoginState: async (d: Omit<LoginState, "id">) => { saved = d; return "s"; } } as unknown as Store;
  const app = express(); app.use(oauthRouter(c, store, { publicJwk: {} } as unknown as TokenService));
  const server = app.listen(0, "127.0.0.1"); await new Promise<void>(r => server.once("listening", r));
  try {
    const q = new URLSearchParams({ client_id: "c", redirect_uri: client.redirectUris[0]!, state: "x", code_challenge: pkceChallenge("verifier-verifier-verifier-verifier-verifier"), response_type: "code", code_challenge_method: "S256", ...params });
    const r = await fetch(`http://127.0.0.1:${(server.address() as AddressInfo).port}/oauth/authorize?${q}`);
    const meta = await fetch(`http://127.0.0.1:${(server.address() as AddressInfo).port}/.well-known/oauth-protected-resource/near/mcp`);
    return { status: r.status, body: await r.text(), saved: saved as Omit<LoginState, "id"> | null, meta: meta.status === 200 ? await meta.json() : null };
  } finally { server.close(); }
}

test("authorize: the NEAR resource grants only near:transact, and the x402 resource never grants it", async () => {
  const c = await config();
  const near = await authorize(c, { resource: c.nearResource });
  assert.equal(near.status, 200);
  assert.equal(near.saved?.scope, NEAR_SCOPE, "scope defaults to near:transact for the NEAR resource");
  assert.deepEqual(near.meta, { resource: c.nearResource, authorization_servers: [c.issuer], scopes_supported: [NEAR_SCOPE], bearer_methods_supported: ["header"] });
  assert.equal((await authorize(c, { resource: c.nearResource, scope: `${NEAR_SCOPE} wallet:transact` })).status, 400);
  assert.equal((await authorize(c, { resource: c.nearResource, scope: "x402:pay" })).status, 400);
  assert.equal((await authorize(c, { resource: c.resource, scope: NEAR_SCOPE })).status, 400);
  assert.equal((await authorize(c, { resource: c.resource })).saved?.scope, "x402:pay", "existing default is unchanged");
  const disabled = await authorize(await config(false), { resource: c.nearResource });
  assert.equal(disabled.status, 400);
  assert.equal(disabled.meta, null);
});

test("NEAR MCP publishes its own tools and instructions and hides provider errors", async () => {
  const services = {
    accounts: { status: async () => ({ account_id: "a".repeat(64) }) },
    operations: { read: async () => { throw new Error("fetch failed https://rpc.example/?apikey=SECRET"); }, prepare: async () => { throw new NearPublicError("insufficient NEAR: needs up to 1 NEAR"); } },
    chainSignatures: {},
  } as any;
  const [client, server] = InMemoryTransport.createLinkedPair();
  const pending = new Map<number, (v: any) => void>(); let id = 0;
  client.onmessage = (m: any) => { pending.get(m.id)?.(m); pending.delete(m.id); };
  await createNearMcp("u", services).connect(server); await client.start();
  const request = (method: string, params: unknown = {}) => new Promise<any>(r => { const n = ++id; pending.set(n, r); void client.send({ jsonrpc: "2.0", id: n, method, params } as any); });
  const init = await request("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "0" } });
  assert.equal(init.result.instructions, NEAR_INSTRUCTIONS);
  const tools = (await request("tools/list")).result.tools as { name: string; inputSchema: any; annotations?: any }[];
  assert.deepEqual(tools.map(t => t.name).sort(), ["evm_address_status", "evm_call_execute", "evm_call_prepare", "near_account_status", "near_activity", "near_contract_read", "near_operation_status", "near_transaction_execute", "near_transaction_prepare"]);
  assert.ok(!tools.some(t => /^(x402|transaction_|smart_wallet)/.test(t.name)), "no Base wallet tools on the NEAR endpoint");
  assert.equal(tools.find(t => t.name === "near_transaction_execute")!.annotations.destructiveHint, true);
  const status = await request("tools/call", { name: "near_account_status", arguments: {} });
  assert.equal(status.result.structuredContent.account_id, "a".repeat(64));
  const read = await request("tools/call", { name: "near_contract_read", arguments: { contract_id: "wrap.near", method_name: "ft_metadata" } });
  assert.equal(read.result.isError, true);
  assert.doesNotMatch(read.result.content[0].text, /SECRET|rpc\.example/);
  const prep = await request("tools/call", { name: "near_transaction_prepare", arguments: { receiver_id: "bob.near", actions: [{ type: "transfer", amount_yocto: "1" }] } });
  assert.match(prep.result.content[0].text, /insufficient NEAR/);
  const bad = await request("tools/call", { name: "near_transaction_prepare", arguments: { receiver_id: "bob.near", actions: [{ type: "add_key", public_key: "x" }] } });
  assert.equal(bad.result.isError, true);
});
