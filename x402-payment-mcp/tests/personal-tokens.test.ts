import assert from "node:assert/strict";
import test from "node:test";
import express from "express";
import { exportJWK, generateKeyPair } from "jose";
import type { AddressInfo } from "node:net";
import { createTokenVerifier } from "../src/auth.js";
import type { Config } from "../src/config.js";
import { oauthRouter } from "../src/oauth.js";
import { isTokenManagerState, sha256, TokenService } from "../src/security.js";
import type { PersonalToken, Store } from "../src/store.js";
import { tokenManagerRouter } from "../src/token-manager.js";

async function config(overrides: Partial<Config> = {}): Promise<Config> {
  const { privateKey } = await generateKeyPair("ES256", { extractable: true });
  const privateJwk = await exportJWK(privateKey);
  return { issuer: "https://pay.example", resource: "https://pay.example/mcp", privateJwk, GITHUB_CLIENT_ID: "github-id", GITHUB_CLIENT_SECRET: "github-secret", ACCESS_TOKEN_TTL_SECONDS: 900, PERSONAL_TOKEN_TTL_DAYS: 90, PERSONAL_TOKEN_MAX_ACTIVE: 10, ...overrides } as Config;
}

// In-memory stand-in for the Postgres store, keyed by token hashes exactly as
// the real one is, so plaintext tokens are never kept.
function memoryStore() {
  const loginStates = new Set<string>(); const sessions = new Map<string, string>();
  const pats = new Map<string, PersonalToken & { userId: string; hash: string; revoked: boolean; scope: string }>();
  let n = 0;
  const store = {
    consumeRateLimit: async () => true,
    upsertIdentity: async () => "user-1",
    createTokenLoginState: async () => { const id = `ls-${++n}`; loginStates.add(id); return id; },
    hasTokenLoginState: async (id: string) => loginStates.has(id),
    consumeTokenLoginState: async (id: string) => loginStates.delete(id),
    createTokenManagerSession: async (userId: string) => { const t = `session-${++n}`; sessions.set(sha256(t), userId); return t; },
    getTokenManagerSession: async (t: string) => sessions.get(sha256(t)) ?? null,
    listPersonalTokens: async (userId: string) => [...pats.values()].filter((p) => p.userId === userId && !p.revoked),
    createPersonalToken: async (userId: string, token: string, label: string, scope: string, ttlDays: number, maxActive: number) => {
      if ([...pats.values()].filter((p) => p.userId === userId && !p.revoked).length >= maxActive) return null;
      const record = { id: `pat-${++n}`, userId, hash: sha256(token), label, hint: token.slice(-4), scope, revoked: false, createdAt: new Date(), expiresAt: new Date(Date.now() + ttlDays * 86400000), lastUsedAt: null };
      pats.set(record.id, record); return record;
    },
    revokePersonalToken: async (userId: string, id: string) => { const p = pats.get(id); if (!p || p.userId !== userId || p.revoked) return false; p.revoked = true; return true; },
    verifyPersonalToken: async (token: string) => { const p = [...pats.values()].find((x) => x.hash === sha256(token) && !x.revoked && x.expiresAt > new Date()); return p ? { id: p.id, userId: p.userId, scope: p.scope, expiresAt: p.expiresAt } : null; },
  };
  return { store: store as unknown as Store, pats };
}

async function serve(cfg: Config, store: Store, tokens: TokenService) {
  const app = express(); app.use(oauthRouter(cfg, store, tokens)); app.use(tokenManagerRouter(cfg, store, tokens));
  const server = app.listen(0, "127.0.0.1"); await new Promise<void>((resolve) => server.once("listening", resolve));
  return { base: `http://127.0.0.1:${(server.address() as AddressInfo).port}`, close: () => new Promise<void>((resolve, reject) => server.close((e) => (e ? reject(e) : resolve()))) };
}

function hidden(page: string, name: string) { const m = page.match(new RegExp(`name="${name}" value="([^"]+)"`)); assert.ok(m, `missing ${name}`); return m[1]!; }

test("Muse token manager: sign in, create a token shown once, and revoke it", async () => {
  const cfg = await config(); const tokens = await TokenService.create(cfg); const { store, pats } = memoryStore();
  const { base, close } = await serve(cfg, store, tokens); const realFetch = globalThis.fetch;
  try {
    const landing = await realFetch(`${base}/muse`); const landingPage = await landing.text();
    assert.equal(landing.status, 200); assert.match(landing.headers.get("content-security-policy") ?? "", /form-action 'self'/); assert.equal(landing.headers.get("cache-control"), "no-store");
    const startPath = landingPage.match(/href="(\/tokens\/auth\/github\/start\?login_state=[^"]+)"/)?.[1]; assert.ok(startPath);
    const start = await realFetch(`${base}${startPath}`, { redirect: "manual" }); assert.equal(start.status, 302);
    const state = new URL(start.headers.get("location")!).searchParams.get("state")!; assert.ok(isTokenManagerState(state));
    await assert.rejects(tokens.verifyProviderState(state, "github"), "a token-manager state must not pass as an MCP client login state");

    globalThis.fetch = async (input, init) => String(input) === "https://github.com/login/oauth/access_token" ? Response.json({ access_token: "provider-token" }) : String(input) === "https://api.github.com/user" ? Response.json({ id: 1, login: "u" }) : realFetch(input, init);
    const callback = await realFetch(`${base}/auth/github/callback?state=${encodeURIComponent(state)}&code=c`); const manager = await callback.text();
    assert.equal(callback.status, 200); assert.match(manager, /Personal access tokens/); assert.match(manager, /No active tokens/);
    const replay = await realFetch(`${base}/auth/github/callback?state=${encodeURIComponent(state)}&code=c`); assert.equal(replay.status, 400, "a sign-in state is single use");

    const session = hidden(manager, "manage_token");
    const forged = await realFetch(`${base}/tokens/create`, { method: "POST", body: new URLSearchParams({ manage_token: "forged", label: "x" }) }); assert.equal(forged.status, 401);
    const create = await realFetch(`${base}/tokens/create`, { method: "POST", body: new URLSearchParams({ manage_token: session, label: "My Muse" }) }); const createdPage = await create.text();
    assert.equal(create.status, 200); assert.equal(create.headers.get("cache-control"), "no-store");
    const token = createdPage.match(/<code id="token">(alx402_[A-Za-z0-9_-]{43})<\/code>/)?.[1]; assert.ok(token, "the new token is shown once");
    assert.match(createdPage, /shown only once/); assert.match(createdPage, /https:\/\/pay\.example\/mcp/); assert.match(createdPage, /secure credential prompt/);
    const record = [...pats.values()][0]!; assert.equal(record.hash, sha256(token)); assert.equal(record.label, "My Muse"); assert.equal(record.scope, "x402:pay");
    assert.doesNotMatch(await (await realFetch(`${base}/tokens/revoke`, { method: "POST", body: new URLSearchParams({ manage_token: session, token_id: "nope" }) })).text(), new RegExp(token), "the token is never shown again");

    const verifier = createTokenVerifier(cfg, tokens, store);
    const info = await verifier.verifyAccessToken(token); assert.equal(info.extra?.userId, "user-1"); assert.deepEqual(info.scopes, ["x402:pay"]); assert.equal(info.clientId, `pat:${record.id}`);
    await assert.rejects(verifier.verifyAccessToken("alx402_notarealtokenvalueatall"));

    const revoke = await realFetch(`${base}/tokens/revoke`, { method: "POST", body: new URLSearchParams({ manage_token: session, token_id: record.id }) });
    assert.equal(revoke.status, 200); assert.match(await revoke.text(), /Token revoked/);
    await assert.rejects(verifier.verifyAccessToken(token), "a revoked token is rejected immediately");
  } finally { globalThis.fetch = realFetch; await close(); }
});

test("Personal tokens respect the active-token cap", async () => {
  const cfg = await config({ PERSONAL_TOKEN_MAX_ACTIVE: 1 }); const tokens = await TokenService.create(cfg); const { store } = memoryStore();
  const session = await store.createTokenManagerSession("user-1", 900);
  const { base, close } = await serve(cfg, store, tokens);
  try {
    const first = await fetch(`${base}/tokens/create`, { method: "POST", body: new URLSearchParams({ manage_token: session }) }); assert.equal(first.status, 200);
    const second = await fetch(`${base}/tokens/create`, { method: "POST", body: new URLSearchParams({ manage_token: session }) });
    assert.equal(second.status, 400); const page = await second.text(); assert.match(page, /already have 1 active tokens/); assert.doesNotMatch(page, /<code id="token">/);
  } finally { await close(); }
});

test("OAuth access tokens keep working and are not confused with personal tokens", async () => {
  const cfg = await config(); const tokens = await TokenService.create(cfg); const { store } = memoryStore();
  const verifier = createTokenVerifier(cfg, tokens, store);
  const jwt = await tokens.accessToken("user-9", "mcp_client", ["x402:pay"]);
  const info = await verifier.verifyAccessToken(jwt); assert.equal(info.extra?.userId, "user-9"); assert.equal(info.clientId, "mcp_client");
  await assert.rejects(verifier.verifyAccessToken("not-a-token"));
  const oauthState = await tokens.providerState("login-state", "github");
  assert.equal(isTokenManagerState(oauthState), false);
  await assert.rejects(tokens.verifyTokenManagerState(oauthState, "github"), "an MCP client login state must not open the token manager");
});
