import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import test from "node:test";
import express from "express";
import { exportJWK, generateKeyPair } from "jose";
import type { AddressInfo } from "node:net";
import { loadConfig, type Config } from "../src/config.js";
import { bindingCookieName, LinkConnectionRequiredError, LinkService, linkRouter, publicSpendRequest, seal, unseal, type LinkClient, type SpendRequest } from "../src/link.js";
import { oauthRouter } from "../src/oauth.js";
import { isLinkConnectState, pkceChallenge, TokenService } from "../src/security.js";
import type { LinkConnection, LinkConnectionInput, Store } from "../src/store.js";

const KEY = randomBytes(32);
const LINK = { clientId: "lwlc_test", clientSecret: "link-client-secret", publishableKey: "pk_test_abc123", encryptionKey: KEY };
const USER = "11111111-1111-4111-8111-111111111111";

async function config(): Promise<Config> {
  const { privateKey } = await generateKeyPair("ES256", { extractable: true });
  return { issuer: "https://pay.example", resource: "https://pay.example/mcp", privateJwk: await exportJWK(privateKey), GITHUB_CLIENT_ID: "github-id", GITHUB_CLIENT_SECRET: "github-secret", link: LINK } as Config;
}

// In-memory stand-in for the Postgres store with the same single-use and
// per-user serialization semantics.
function memoryStore(identityUser = USER) {
  const attempts = new Map<string, { userId: string; expiresAt: number; started: boolean; stateHash?: string; bindingHash?: string; verifierEnc?: string }>();
  const connections = new Map<string, LinkConnection>();
  const recorded: unknown[] = [];
  let lock: Promise<unknown> = Promise.resolve(); let n = 0;
  const store = {
    consumeRateLimit: async () => true,
    upsertIdentity: async () => identityUser,
    createLinkAttempt: async (userId: string, ttl: number) => { const id = `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`; attempts.set(id, { userId, expiresAt: Date.now() + ttl * 1000, started: false }); return { id, expiresAt: new Date(Date.now() + ttl * 1000) }; },
    getLinkAttempt: async (id: string) => { const a = attempts.get(id); return a && !a.started && a.expiresAt > Date.now() ? { userId: a.userId } : null; },
    startLinkAttempt: async (id: string, userId: string, stateHash: string, bindingHash: string, verifierEnc: string) => { const a = attempts.get(id); if (!a || a.started || a.userId !== userId || a.expiresAt <= Date.now()) return false; Object.assign(a, { started: true, stateHash, bindingHash, verifierEnc }); return true; },
    consumeLinkAttempt: async (stateHash: string) => { for (const [id, a] of attempts) if (a.started && a.stateHash === stateHash && a.expiresAt > Date.now()) { attempts.delete(id); return { id, userId: a.userId, bindingHash: a.bindingHash!, verifierEnc: a.verifierEnc! }; } return null; },
    getLinkConnection: async (userId: string) => connections.get(userId) ?? null,
    withLinkConnection: <T>(userId: string, action: (c: LinkConnection | null, tx: { save(x: LinkConnectionInput): Promise<void>; remove(): Promise<void> }) => Promise<T>) => {
      const run = lock.then(() => action(connections.get(userId) ?? null, {
        save: async (x) => { connections.set(userId, { ...x, userId, createdAt: connections.get(userId)?.createdAt ?? new Date() }); },
        remove: async () => { connections.delete(userId); },
      }));
      lock = run.catch(() => undefined); return run;
    },
    recordLinkSpendRequest: async (x: unknown) => { recorded.push(x); },
  };
  return { store: store as unknown as Store, attempts, connections, recorded };
}

// Fake login.link.com / api.link.com. Records every call; never reaches the network.
function fakeLink(opts: { tokenStatus?: number; tokenBody?: Record<string, unknown>; refreshStatus?: number; refreshBody?: Record<string, unknown>; revokeStatus?: number; linkUserId?: string } = {}) {
  const calls: { url: string; auth: string | null; body: URLSearchParams | null }[] = []; let issued = 0;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); const auth = new Headers(init?.headers).get("authorization");
    const body = typeof init?.body === "string" || init?.body instanceof URLSearchParams ? new URLSearchParams(String(init.body)) : null;
    calls.push({ url, auth, body });
    if (url === "https://login.link.com/auth/token") {
      if (body?.get("grant_type") === "refresh_token") return Response.json(opts.refreshBody ?? { access_token: `liwltoken_${++issued}`, refresh_token: `liwlrefresh_${issued}`, expires_in: 3600, scope: "payment_methods.agentic userinfo:read" }, { status: opts.refreshStatus ?? 200 });
      return Response.json(opts.tokenBody ?? { access_token: `liwltoken_${++issued}`, refresh_token: `liwlrefresh_${issued}`, expires_in: 3600, scope: "payment_methods.agentic userinfo:read" }, { status: opts.tokenStatus ?? 200 });
    }
    if (url === "https://login.link.com/auth/revoke") return new Response(null, { status: opts.revokeStatus ?? 200 });
    if (url === "https://api.link.com/userinfo") return Response.json({ id: opts.linkUserId ?? "lnkusr_1", email: "jenny@example.com" });
    return new Response("not found", { status: 404 });
  }) as typeof globalThis.fetch;
  return { fetchImpl, calls };
}

async function serve(cfg: Config, store: Store, tokens: TokenService, service: LinkService) {
  const app = express(); app.use(oauthRouter(cfg, store, tokens, service)); app.use(linkRouter(service, cfg, store, tokens));
  const server = app.listen(0, "127.0.0.1"); await new Promise<void>((resolve) => server.once("listening", resolve));
  return { base: `http://127.0.0.1:${(server.address() as AddressInfo).port}`, close: () => new Promise<void>((resolve, reject) => server.close((e) => (e ? reject(e) : resolve()))) };
}

// Walks the browser through: connect page -> GitHub -> Link authorize URL.
async function startConnect(base: string, connectUrl: string) {
  const realFetch = globalThis.fetch;
  const attempt = new URL(connectUrl).searchParams.get("attempt")!;
  const page = await realFetch(`${base}/link/connect?attempt=${attempt}`); const html = await page.text();
  assert.equal(page.status, 200); assert.equal(page.headers.get("cache-control"), "no-store");
  const startPath = html.match(/href="(\/link\/auth\/github\/start\?attempt=[^"]+)"/)?.[1]; assert.ok(startPath, "the page asks the user to confirm their identity");
  const start = await realFetch(`${base}${startPath}`, { redirect: "manual" }); assert.equal(start.status, 302);
  const state = new URL(start.headers.get("location")!).searchParams.get("state")!; assert.ok(isLinkConnectState(state));
  globalThis.fetch = async (input, init) => String(input) === "https://github.com/login/oauth/access_token" ? Response.json({ access_token: "provider-token" }) : String(input) === "https://api.github.com/user" ? Response.json({ id: 1, login: "u" }) : realFetch(input, init);
  try { return await realFetch(`${base}/auth/github/callback?state=${encodeURIComponent(state)}&code=c`, { redirect: "manual" }); }
  finally { globalThis.fetch = realFetch; }
}
const cookieFrom = (res: Response) => res.headers.get("set-cookie")!.split(";")[0]!;

test("stored Link secrets are sealed with AES-GCM bound to their purpose", () => {
  const sealed = seal(KEY, "liwlrefresh_secret", "link-refresh:u1");
  assert.doesNotMatch(sealed, /liwlrefresh_secret/);
  assert.equal(unseal(KEY, sealed, "link-refresh:u1"), "liwlrefresh_secret");
  assert.throws(() => unseal(KEY, sealed, "link-refresh:u2"), "a ciphertext moved to another user does not decrypt");
  assert.throws(() => unseal(KEY, sealed, "link-access:u1"), "a refresh token cannot be read as an access token");
  assert.throws(() => unseal(randomBytes(32), sealed, "link-refresh:u1"), "a different key does not decrypt");
  const parts = sealed.split("."); parts[3] = Buffer.from("tampered").toString("base64url");
  assert.throws(() => unseal(KEY, parts.join("."), "link-refresh:u1"), "tampering is detected");
});

test("Link configuration is all-or-nothing and never accepts a secret API key", async () => {
  const { privateKey } = await generateKeyPair("ES256", { extractable: true });
  const base = { PUBLIC_BASE_URL: "https://pay.example", DATABASE_URL: "postgres://x", OAUTH_SIGNING_PRIVATE_JWK: JSON.stringify(await exportJWK(privateKey)), GITHUB_CLIENT_ID: "g", GITHUB_CLIENT_SECRET: "g", CDP_API_KEY_ID: "a", CDP_API_KEY_SECRET: "b", CDP_WALLET_SECRET: "c", ARC_RPC_URL: "https://arc.example" };
  const full = { LINK_CLIENT_ID: "id", LINK_CLIENT_SECRET: "secret", STRIPE_PUBLISHABLE_KEY: "pk_live_abc", LINK_TOKEN_ENCRYPTION_KEY: randomBytes(32).toString("base64") };
  assert.equal(loadConfig(base).link, null, "Link stays off when unset");
  const on = loadConfig({ ...base, ...full }).link; assert.ok(on); assert.equal(on.encryptionKey.length, 32);
  assert.throws(() => loadConfig({ ...base, LINK_CLIENT_ID: "id", LINK_CLIENT_SECRET: "secret" }), /together/);
  assert.throws(() => loadConfig({ ...base, ...full, STRIPE_PUBLISHABLE_KEY: "sk_live_abc" }), /publishable key/);
  assert.throws(() => loadConfig({ ...base, ...full, LINK_TOKEN_ENCRYPTION_KEY: "short" }), /32 random bytes/);
});

test("connecting Link: identity re-confirmed, PKCE and state sent, tokens exchanged and stored encrypted", async () => {
  const cfg = await config(); const tokens = await TokenService.create(cfg); const { store, connections, attempts } = memoryStore(); const link = fakeLink();
  const service = new LinkService(cfg.issuer, LINK, store, link.fetchImpl); const { base, close } = await serve(cfg, store, tokens, service);
  try {
    const started = await service.connect(USER, false); assert.equal(started.connected, false); assert.ok(started.connect_url);
    const toLink = await startConnect(base, started.connect_url.replace(cfg.issuer, base));
    assert.equal(toLink.status, 303);
    const authorize = new URL(toLink.headers.get("location")!);
    assert.equal(authorize.origin + authorize.pathname, "https://login.link.com/auth");
    const q = authorize.searchParams;
    assert.equal(q.get("key"), "pk_test_abc123"); assert.equal(q.get("client_id"), "lwlc_test"); assert.equal(q.get("response_type"), "code");
    assert.equal(q.get("redirect_uri"), "https://pay.example/auth/link/callback", "exactly the registered redirect URI");
    assert.equal(q.get("scope"), "payment_methods.agentic userinfo:read"); assert.equal(q.get("code_challenge_method"), "S256");
    assert.ok((q.get("state") ?? "").length >= 43); assert.ok((q.get("code_challenge") ?? "").length >= 43);
    assert.equal(q.get("client_secret"), null, "the client secret never goes to the browser");
    const setCookie = toLink.headers.get("set-cookie")!; assert.match(setCookie, /HttpOnly/i); assert.match(setCookie, /SameSite=Lax/i); assert.match(setCookie, /Secure/i);
    assert.ok(setCookie.startsWith(`${bindingCookieName(cfg.issuer)}=`));
    const stored = [...attempts.values()][0]!; assert.match(stored.verifierEnc!, /^v1\./, "the PKCE verifier is stored sealed");

    const callback = await fetch(`${base}/auth/link/callback?code=auth_code&state=${encodeURIComponent(q.get("state")!)}`, { headers: { cookie: cookieFrom(toLink) } });
    const page = await callback.text();
    assert.equal(callback.status, 200, page); assert.match(page, /Your Link wallet is connected/); assert.match(page, /jenny@example\.com/);
    const exchange = link.calls.find((c) => c.body?.get("grant_type") === "authorization_code")!;
    assert.equal(exchange.auth, "Bearer pk_test_abc123", "Link authenticates the app by its publishable key");
    assert.equal(exchange.body!.get("client_secret"), "link-client-secret"); assert.equal(exchange.body!.get("code"), "auth_code");
    assert.equal(exchange.body!.get("redirect_uri"), "https://pay.example/auth/link/callback");
    assert.equal(pkceChallenge(exchange.body!.get("code_verifier")!), q.get("code_challenge"), "the verifier matches the challenge sent to Link");

    const connection = connections.get(USER)!; assert.ok(connection);
    assert.equal(connection.linkUserId, "lnkusr_1"); assert.equal(connection.email, "jenny@example.com"); assert.equal(connection.scope, "payment_methods.agentic userinfo:read");
    assert.doesNotMatch(JSON.stringify(connection), /liwltoken_|liwlrefresh_/, "tokens are never stored in plaintext");
    assert.equal(await service.accessToken(USER), "liwltoken_1");

    const replay = await fetch(`${base}/auth/link/callback?code=auth_code&state=${encodeURIComponent(q.get("state")!)}`, { headers: { cookie: cookieFrom(toLink) } });
    assert.equal(replay.status, 400, "a Link callback is single use");
    assert.equal((await service.connect(USER, false)).connected, true);
  } finally { await close(); }
});

test("a connect link cannot bind a wallet to an account the signer does not own", async () => {
  const cfg = await config(); const tokens = await TokenService.create(cfg); const { store, connections } = memoryStore("22222222-2222-4222-8222-222222222222"); const link = fakeLink();
  const service = new LinkService(cfg.issuer, LINK, store, link.fetchImpl); const { base, close } = await serve(cfg, store, tokens, service);
  try {
    const started = await service.connect(USER, false);
    const res = await startConnect(base, started.connect_url!.replace(cfg.issuer, base));
    assert.equal(res.status, 400); assert.equal(res.headers.get("location"), null, "Link is never opened");
    assert.match(await res.text(), /different account/);
    assert.equal(connections.size, 0); assert.equal(link.calls.length, 0);
  } finally { await close(); }
});

test("Link's callback requires the browser that started the connection", async () => {
  const cfg = await config(); const tokens = await TokenService.create(cfg); const { store, connections } = memoryStore(); const link = fakeLink();
  const service = new LinkService(cfg.issuer, LINK, store, link.fetchImpl); const { base, close } = await serve(cfg, store, tokens, service);
  try {
    const toLink = await startConnect(base, (await service.connect(USER, false)).connect_url!.replace(cfg.issuer, base));
    const state = new URL(toLink.headers.get("location")!).searchParams.get("state")!;
    // A captured Link URL finished in another browser (no binding cookie).
    const res = await fetch(`${base}/auth/link/callback?code=auth_code&state=${encodeURIComponent(state)}`);
    assert.equal(res.status, 400); assert.match(await res.text(), /different browser/);
    assert.equal(link.calls.length, 0, "no code is exchanged"); assert.equal(connections.size, 0);
    const forged = await fetch(`${base}/auth/link/callback?code=x&state=forged`, { headers: { cookie: cookieFrom(toLink) } });
    assert.equal(forged.status, 400);
  } finally { await close(); }
});

test("declining, or granting without the payment scope, connects nothing", async () => {
  for (const scenario of ["declined", "no_payment_scope"] as const) {
    const cfg = await config(); const tokens = await TokenService.create(cfg); const { store, connections } = memoryStore();
    const link = fakeLink(scenario === "no_payment_scope" ? { tokenBody: { access_token: "liwltoken_x", refresh_token: "liwlrefresh_x", expires_in: 3600, scope: "userinfo:read" } } : {});
    const service = new LinkService(cfg.issuer, LINK, store, link.fetchImpl); const { base, close } = await serve(cfg, store, tokens, service);
    try {
      const toLink = await startConnect(base, (await service.connect(USER, false)).connect_url!.replace(cfg.issuer, base));
      const state = encodeURIComponent(new URL(toLink.headers.get("location")!).searchParams.get("state")!);
      const query = scenario === "declined" ? `error=access_denied&state=${state}` : `code=c&state=${state}`;
      const res = await fetch(`${base}/auth/link/callback?${query}`, { headers: { cookie: cookieFrom(toLink) } });
      assert.equal(res.status, 400); assert.equal(connections.size, 0);
      if (scenario === "no_payment_scope") assert.ok(link.calls.some((c) => c.url.endsWith("/auth/revoke") && c.body?.get("token") === "liwlrefresh_x"), "the partial grant is revoked");
    } finally { await close(); }
  }
});

function connectedService(opts: Parameters<typeof fakeLink>[0] = {}, accessExpiresInMs = 3_600_000) {
  const { store, connections } = memoryStore(); const link = fakeLink(opts);
  connections.set(USER, { userId: USER, linkUserId: "lnkusr_1", email: "jenny@example.com", scope: "payment_methods.agentic userinfo:read", accessTokenEnc: seal(KEY, "liwltoken_old", `link-access:${USER}`), accessExpiresAt: new Date(Date.now() + accessExpiresInMs), refreshTokenEnc: seal(KEY, "liwlrefresh_old", `link-refresh:${USER}`), createdAt: new Date() });
  return { store, connections, link };
}

test("expiring access tokens refresh once under the lock and the rotated refresh token is saved", async () => {
  const { store, connections, link } = connectedService({}, 30_000);
  const service = new LinkService("https://pay.example", LINK, store, link.fetchImpl);
  const [a, b] = await Promise.all([service.accessToken(USER), service.accessToken(USER)]);
  assert.equal(a, "liwltoken_1"); assert.equal(b, "liwltoken_1", "the second caller reuses the refreshed token");
  const refreshes = link.calls.filter((c) => c.body?.get("grant_type") === "refresh_token");
  assert.equal(refreshes.length, 1, "concurrent callers never spend the same refresh token twice");
  assert.equal(refreshes[0]!.body!.get("refresh_token"), "liwlrefresh_old"); assert.equal(refreshes[0]!.auth, "Bearer pk_test_abc123");
  assert.equal(unseal(KEY, connections.get(USER)!.refreshTokenEnc, `link-refresh:${USER}`), "liwlrefresh_1");
  assert.equal(await service.accessToken(USER, true), "liwltoken_2", "a forced refresh after a 401 rotates again");
});

test("only invalid_grant drops a connection; transient failures keep it", async () => {
  const revoked = connectedService({ refreshStatus: 400, refreshBody: { error: "invalid_grant" } }, 0);
  await assert.rejects(new LinkService("https://pay.example", LINK, revoked.store, revoked.link.fetchImpl).accessToken(USER), LinkConnectionRequiredError);
  assert.equal(revoked.connections.size, 0);
  const flaky = connectedService({ refreshStatus: 503, refreshBody: { error: "server_error" } }, 0);
  await assert.rejects(new LinkService("https://pay.example", LINK, flaky.store, flaky.link.fetchImpl).accessToken(USER), /temporarily unavailable/);
  assert.equal(flaky.connections.size, 1);
  const rotatedKey = connectedService({}, 0);
  await assert.rejects(new LinkService("https://pay.example", { ...LINK, encryptionKey: randomBytes(32) }, rotatedKey.store, rotatedKey.link.fetchImpl).accessToken(USER), LinkConnectionRequiredError);
  assert.equal(rotatedKey.connections.size, 0, "an undecryptable grant is discarded");
});

test("disconnect revokes at Link before forgetting the grant", async () => {
  const failing = connectedService({ revokeStatus: 500 });
  await assert.rejects(new LinkService("https://pay.example", LINK, failing.store, failing.link.fetchImpl).disconnect(USER), /still connected/);
  assert.equal(failing.connections.size, 1, "a failed revocation keeps the connection");
  const ok = connectedService();
  const result = await new LinkService("https://pay.example", LINK, ok.store, ok.link.fetchImpl).disconnect(USER);
  assert.equal(result.disconnected, true); assert.equal(ok.connections.size, 0);
  const revoke = ok.link.calls.find((c) => c.url === "https://login.link.com/auth/revoke")!;
  assert.equal(revoke.body!.get("token"), "liwlrefresh_old"); assert.equal(revoke.body!.get("token_type_hint"), "refresh_token"); assert.equal(revoke.body!.get("client_secret"), "link-client-secret");
});

const CARD_REQUEST: SpendRequest & { card: unknown } = { id: "lsrq_1", status: "approved", credential_type: "card", amount: 3500, currency: "usd", merchant_name: "Stripe Press", merchant_url: "https://press.stripe.com", approval_url: "https://app.link.com/activity/approve/lsrq_1", card_brand: "visa", card_last4: "4242", card: { number: "4242424242424242", cvc: "100", exp_month: 6, exp_year: 2029 } };

function fakeClient(overrides: Partial<LinkClient["spendRequests"]> = {}) {
  const created: Record<string, unknown>[] = []; const retrieved: { id: string; include?: string[] | undefined }[] = [];
  const client: LinkClient = {
    userInfo: { retrieve: async () => ({ id: "lnkusr_1", email: "jenny@example.com" }) },
    paymentMethods: { list: async () => [] },
    shippingAddresses: { list: async () => [] },
    spendRequests: {
      create: async (p) => { created.push(p); return { ...CARD_REQUEST, status: "pending_approval" }; },
      retrieve: async (id, opts) => { retrieved.push({ id, include: opts?.include }); return CARD_REQUEST; },
      update: async () => CARD_REQUEST, requestApproval: async (id) => ({ id, approval_url: "https://app.link.com/x" }), cancel: async () => ({ ...CARD_REQUEST, status: "canceled" }),
      ...overrides,
    },
  };
  return { client, created, retrieved };
}

test("spend requests always ask the user for approval and never expose card numbers", async () => {
  const { store, link } = connectedService();
  const fake = fakeClient(); const service = new LinkService("https://pay.example", LINK, store, link.fetchImpl, () => fake.client);
  const created = await service.createSpendRequest(USER, { credential_type: "card", amount: 3500, currency: "usd", context: "x".repeat(100), idempotency_key: "purchase-1", merchant_name: "Stripe Press", merchant_url: "https://press.stripe.com" });
  assert.equal(fake.created[0]!.request_approval, true); assert.equal(fake.created[0]!.idempotency_key, "purchase-1");
  assert.equal(created.approval_url, "https://app.link.com/activity/approve/lsrq_1");
  const status = await service.getSpendRequest(USER, "lsrq_1");
  assert.equal(fake.retrieved[0]!.include, undefined, "status checks never ask Link for credentials");
  assert.doesNotMatch(JSON.stringify(status), /4242424242424242|"cvc"/); assert.deepEqual(status.payment_method, { brand: "visa", last4: "4242" });
  assert.doesNotMatch(JSON.stringify(publicSpendRequest(CARD_REQUEST)), /4242424242424242/);
  await assert.rejects(service.payToken(USER, "lsrq_1"), /Card credentials are never returned/);
});

test("a Link Pay Token is released only for an approved pay-token request", async () => {
  const { store, link } = connectedService();
  const pending = fakeClient({ retrieve: async () => ({ id: "lsrq_2", status: "pending_approval", credential_type: "link_pay_token" }) });
  await assert.rejects(new LinkService("https://pay.example", LINK, store, link.fetchImpl, () => pending.client).payToken(USER, "lsrq_2"), /not approved/);
  let include: string[] | undefined;
  const approved = fakeClient({ retrieve: async (_id, opts) => { include = opts?.include; return { id: "lsrq_2", status: "approved", credential_type: "link_pay_token", amount: 3500, currency: "usd", link_pay_token: "lpt_abc" }; } });
  const result = await new LinkService("https://pay.example", LINK, store, link.fetchImpl, () => approved.client).payToken(USER, "lsrq_2");
  assert.equal(result.link_pay_token, "lpt_abc"); assert.deepEqual(include, ["link_pay_token"], "only the pay token is requested, never card");
});

test("Link calls without a connection ask the agent to connect", async () => {
  const { store } = memoryStore();
  const service = new LinkService("https://pay.example", LINK, store, fakeLink().fetchImpl);
  assert.deepEqual((await service.status(USER)).connected, false);
  await assert.rejects(service.accessToken(USER), LinkConnectionRequiredError);
});

test("the standing /link page connects the wallet of whoever signs in, without an agent", async () => {
  const cfg = await config(); const tokens = await TokenService.create(cfg); const { store, connections } = memoryStore(); const link = fakeLink();
  const service = new LinkService(cfg.issuer, LINK, store, link.fetchImpl); const { base, close } = await serve(cfg, store, tokens, service);
  const realFetch = globalThis.fetch;
  try {
    const page = await realFetch(`${base}/link`); const html = await page.text();
    assert.equal(page.status, 200); assert.match(html, /href="\/link\/auth\/github\/start"/);
    const start = await realFetch(`${base}/link/auth/github/start`, { redirect: "manual" }); assert.equal(start.status, 302);
    const state = new URL(start.headers.get("location")!).searchParams.get("state")!;
    assert.equal(await tokens.verifyLinkConnectState(state, "github"), null);
    globalThis.fetch = async (input, init) => String(input) === "https://github.com/login/oauth/access_token" ? Response.json({ access_token: "p" }) : String(input) === "https://api.github.com/user" ? Response.json({ id: 1, login: "u" }) : realFetch(input, init);
    const toLink = await realFetch(`${base}/auth/github/callback?state=${encodeURIComponent(state)}&code=c`, { redirect: "manual" });
    globalThis.fetch = realFetch;
    assert.equal(toLink.status, 303); assert.ok(toLink.headers.get("location")!.startsWith("https://login.link.com/auth?"));
    const linkState = new URL(toLink.headers.get("location")!).searchParams.get("state")!;
    const done = await realFetch(`${base}/auth/link/callback?code=c&state=${encodeURIComponent(linkState)}`, { headers: { cookie: cookieFrom(toLink) } });
    assert.equal(done.status, 200); assert.ok(connections.get(USER), "the wallet is connected to the signed-in user");
    const bad = await realFetch(`${base}/link/auth/github/start?attempt=not-a-uuid`, { redirect: "manual" }); assert.equal(bad.status, 400, "a malformed attempt is not treated as the standing page");
  } finally { globalThis.fetch = realFetch; await close(); }
});
