import assert from "node:assert/strict";
import test from "node:test";
import { createHash, generateKeyPairSync, randomBytes, randomUUID, sign } from "node:crypto";
import { runInNewContext, Script } from "node:vm";
import express from "express";
import type { AddressInfo } from "node:net";
import type { Config } from "../src/config.js";
import { oauthRouter } from "../src/oauth.js";
import { passkeyBrowserScript } from "../src/passkeys.js";
import { pkceChallenge, sha256, type TokenService } from "../src/security.js";
import type { LoginState, NewPasskey, OAuthClient, Store, StoredPasskey } from "../src/store.js";

const ISSUER = "https://pay.example", RP_ID = "pay.example";
const b64u = (b: Uint8Array) => Buffer.from(b).toString("base64url");

// Minimal CBOR (unsigned/negative ints, byte and text strings, maps): enough
// for a COSE key and a "none" attestation object.
function cbor(v: unknown): Buffer {
  const head = (major: number, n: number) => n < 24 ? Buffer.from([major << 5 | n]) : n < 256 ? Buffer.from([major << 5 | 24, n]) : Buffer.from([major << 5 | 25, n >> 8, n & 255]);
  if (typeof v === "number") return v >= 0 ? head(0, v) : head(1, -1 - v);
  if (typeof v === "string") { const b = Buffer.from(v); return Buffer.concat([head(3, b.length), b]); }
  if (v instanceof Uint8Array) return Buffer.concat([head(2, v.length), Buffer.from(v)]);
  const entries = v instanceof Map ? [...v.entries()] : Object.entries(v as object);
  return Buffer.concat([head(5, entries.length), ...entries.flatMap(([k, x]) => [cbor(k), cbor(x)])]);
}

// A software platform authenticator: a synced passkey (BE and BS set, counter
// always 0, like iCloud Keychain and Google Password Manager).
class Authenticator {
  key = generateKeyPairSync("ec", { namedCurve: "P-256" });
  id = randomBytes(16);
  constructor(private origin = ISSUER, private rpId = RP_ID) {}
  private authData(extra: Buffer, attested: boolean) {
    return Buffer.concat([createHash("sha256").update(this.rpId).digest(), Buffer.from([0x01 | 0x04 | 0x08 | 0x10 | (attested ? 0x40 : 0)]), Buffer.alloc(4), extra]);
  }
  create(options: any) {
    const jwk = this.key.publicKey.export({ format: "jwk" });
    const cose = cbor(new Map<number, unknown>([[1, 2], [3, -7], [-1, 1], [-2, Buffer.from(jwk.x!, "base64url")], [-3, Buffer.from(jwk.y!, "base64url")]]));
    const len = Buffer.alloc(2); len.writeUInt16BE(this.id.length);
    const authData = this.authData(Buffer.concat([Buffer.alloc(16), len, this.id, cose]), true);
    const clientDataJSON = Buffer.from(JSON.stringify({ type: "webauthn.create", challenge: options.challenge, origin: this.origin }));
    return { id: b64u(this.id), rawId: b64u(this.id), type: "public-key", response: { clientDataJSON: b64u(clientDataJSON), attestationObject: b64u(cbor({ fmt: "none", attStmt: new Map(), authData })), transports: ["internal", "hybrid"] }, clientExtensionResults: {} };
  }
  get(options: any, { tamper = false } = {}) {
    const authData = this.authData(Buffer.alloc(0), false);
    const clientDataJSON = Buffer.from(JSON.stringify({ type: "webauthn.get", challenge: options.challenge, origin: this.origin }));
    const signature = sign("sha256", Buffer.concat([authData, createHash("sha256").update(clientDataJSON).digest()]), this.key.privateKey);
    if (tamper) signature.writeUInt8(signature.readUInt8(signature.length - 1) ^ 1, signature.length - 1);
    return { id: b64u(this.id), rawId: b64u(this.id), type: "public-key", response: { authenticatorData: b64u(authData), clientDataJSON: b64u(clientDataJSON), signature: b64u(signature) }, clientExtensionResults: {} };
  }
}

async function harness() {
  const client: OAuthClient = { clientId: "client", clientName: "Claude", redirectUris: ["https://claude.example/callback"] };
  const states = new Map<string, LoginState>(), challenges = new Map<string, any>(), credentials = new Map<string, StoredPasskey & Pick<NewPasskey, "deviceType" | "backedUp">>();
  const consents: { userId: string; token: string }[] = [];
  const pending = new Map([["google-consent-token", { userId: "google-user", name: "yuri@example.com" }]]);
  const store = {
    getClient: async (id: string) => id === client.clientId ? client : null,
    consumeRateLimit: async () => true,
    createLoginState: async (d: Omit<LoginState, "id">) => { const id = randomUUID(); states.set(id, { ...d, id }); return id; },
    hasLoginState: async (id: string) => states.has(id),
    consumeLoginState: async (id: string) => { const s = states.get(id) ?? null; states.delete(id); return s; },
    createPendingConsent: async (_s: LoginState, userId: string) => { const token = `consent-${consents.length}`; consents.push({ userId, token }); return token; },
    createPasskeyChallenge: async (c: any) => { const id = randomUUID(); challenges.set(id, { challenge: c.challenge, purpose: c.purpose, loginState: c.loginState ?? null, consentTokenHash: c.consentToken ? sha256(c.consentToken) : null }); return id; },
    consumePasskeyChallenge: async (id: string, purpose: string) => { const c = challenges.get(id); if (!c || c.purpose !== purpose) return null; challenges.delete(id); return c; },
    passkeyCredential: async (id: string) => credentials.get(id) ?? null,
    passkeyIds: async (userId: string) => [...credentials.values()].filter(c => c.userId === userId).map(c => ({ id: c.id, transports: c.transports })),
    savePasskey: async (p: NewPasskey, userId?: string) => { const owner = userId ?? `passkey-user-${credentials.size}`; credentials.set(p.id, { ...p, userId: owner }); return owner; },
    markPasskeyUsed: async (id: string, counter: number) => { credentials.get(id)!.counter = counter; },
    pendingConsentUser: async (token: string) => pending.get(token) ?? null,
    upsertIdentity: async () => "github-user",
  } as unknown as Store;
  const config = { issuer: ISSUER, resource: `${ISSUER}/mcp`, passkeyRpId: RP_ID, GITHUB_CLIENT_ID: "gh", GITHUB_CLIENT_SECRET: "gh-secret", AUTH_CODE_TTL_SECONDS: 300 } as Config;
  const app = express(); app.use(oauthRouter(config, store, { publicJwk: {}, providerState: async (id: string) => `gh-${id}`, verifyProviderState: async (v: string) => v.slice(3) } as unknown as TokenService));
  app.use((_e: unknown, _q: express.Request, res: express.Response, _n: express.NextFunction) => res.status(400).json({ error: "invalid_request" }));
  const server = app.listen(0, "127.0.0.1"); await new Promise<void>(r => server.once("listening", r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const authorize = async () => {
    const q = new URLSearchParams({ client_id: client.clientId, redirect_uri: client.redirectUris[0]!, state: "s", code_challenge: pkceChallenge("verifier-verifier-verifier-verifier-verifier"), response_type: "code", code_challenge_method: "S256" });
    const r = await fetch(`${base}/oauth/authorize?${q}`); const page = await r.text();
    return { page, csp: r.headers.get("content-security-policy") ?? "", loginState: /login_state:"([0-9a-f-]{36})"/.exec(page)![1]! };
  };
  const options = async (body: object) => { const r = await fetch(`${base}/auth/passkey/options`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return { status: r.status, body: await r.json() as any }; };
  const finish = async (purpose: string, challengeId: string, credential: object) => { const r = await fetch(`${base}/auth/passkey/finish`, { method: "POST", body: new URLSearchParams({ purpose, challenge_id: challengeId, credential: JSON.stringify(credential) }), redirect: "manual" }); return { status: r.status, page: await r.text() }; };
  const add = async (body: object) => { const r = await fetch(`${base}/auth/passkey/add`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); return { status: r.status, body: await r.json() as any }; };
  return { base, states, credentials, consents, authorize, options, finish, add, close: () => new Promise<void>(r => server.close(() => r())) };
}

test("the login page offers passkeys under a CSP that allows only same-origin calls and form posts", async () => {
  const h = await harness();
  try {
    const { page, csp } = await h.authorize();
    assert.match(page, /Sign in with a passkey/);
    assert.match(page, /Create an account with a passkey/);
    assert.match(page, /Continue with GitHub/);
    assert.match(csp, /connect-src 'self'/);
    assert.match(csp, /form-action 'self'/);
    assert.match(csp, /script-src 'nonce-/);
    assert.match(csp, /font-src 'self'/);
    assert.ok(page.indexOf("Sign in with a passkey") < page.indexOf("Continue with GitHub"), "the passkey comes first");
    assert.match(page, /<img src="\/assets\/nofrontend-logo\.png"/);
    for (const [, js] of page.matchAll(/<script nonce="[^"]+">([\s\S]*?)<\/script>/g)) new Script(js!);
  } finally { await h.close(); }
});

test("a new passkey creates an account, then signs in to the same account; neither skips consent", async () => {
  const h = await harness(), device = new Authenticator();
  try {
    const first = await h.authorize();
    const reg = await h.options({ mode: "register", login_state: first.loginState });
    assert.equal(reg.status, 200);
    assert.equal(reg.body.options.rp.id, RP_ID);
    assert.equal(reg.body.options.authenticatorSelection.userVerification, "required");
    const created = await h.finish("register", reg.body.challenge_id, device.create(reg.body.options));
    assert.equal(created.status, 200, created.page);
    assert.match(created.page, /Allow wallet access\?/);
    assert.doesNotMatch(created.page, /Add a passkey/, "a passkey sign-in is not offered another passkey");
    assert.equal(h.consents.at(-1)!.userId, "passkey-user-0");
    const saved = h.credentials.get(b64u(device.id))!;
    assert.deepEqual([saved.deviceType, saved.backedUp], ["multiDevice", true]);
    assert.equal(h.states.has(first.loginState), false, "the login request is used once");

    const second = await h.authorize();
    const login = await h.options({ mode: "login", login_state: second.loginState });
    assert.equal(login.body.options.userVerification, "required");
    const signedIn = await h.finish("login", login.body.challenge_id, device.get(login.body.options));
    assert.equal(signedIn.status, 200, signedIn.page);
    assert.equal(h.consents.at(-1)!.userId, "passkey-user-0", "same account, same wallet");
  } finally { await h.close(); }
});

test("forged, replayed, foreign-origin and unknown passkey responses never reach consent", async () => {
  const h = await harness(), device = new Authenticator();
  try {
    const reg = await h.options({ mode: "register", login_state: (await h.authorize()).loginState });
    await h.finish("register", reg.body.challenge_id, device.create(reg.body.options));
    const consents = h.consents.length;
    const attempt = async (make: (o: any) => object, purpose = "login") => {
      const { loginState } = await h.authorize();
      const o = await h.options({ mode: "login", login_state: loginState });
      const r = await h.finish(purpose, o.body.challenge_id, make(o.body.options));
      return { ...r, loginState, challengeId: o.body.challenge_id, options: o.body.options };
    };
    const tampered = await attempt(o => device.get(o, { tamper: true }));
    assert.equal(tampered.status, 400); assert.match(tampered.page, /could not be verified/);
    assert.ok(h.states.has(tampered.loginState), "a failed passkey leaves the login request for another try");
    const phishing = await attempt(o => Object.assign(new Authenticator("https://pay-example.attacker"), { key: device.key, id: device.id }).get(o));
    assert.equal(phishing.status, 400, "the same passkey used on a look-alike origin is refused"); assert.match(phishing.page, /could not be verified/);
    const stranger = await attempt(o => new Authenticator().get(o));
    assert.match(stranger.page, /not registered with AgentLayer/);
    const ok = await attempt(o => device.get(o));
    assert.equal(ok.status, 200);
    const replay = await h.finish("login", ok.challengeId, device.get(ok.options));
    assert.equal(replay.status, 400, "a challenge is used once"); assert.match(replay.page, /expired/);
    const wrongPurpose = await attempt(o => device.get(o), "register");
    assert.equal(wrongPurpose.status, 400, "a sign-in challenge cannot create an account");
    assert.equal(h.consents.length, consents + 1, "only the genuine sign-in reached consent");
    assert.equal((await h.options({ mode: "login", login_state: randomUUID() })).status, 400, "options need a live login request");
  } finally { await h.close(); }
});

test("a signed-in Google user adds a passkey to the same account from the consent page", async () => {
  const h = await harness(), device = new Authenticator();
  try {
    assert.equal((await h.options({ mode: "add", consent_token: "guessed" })).status, 400);
    const o = await h.options({ mode: "add", consent_token: "google-consent-token" });
    assert.equal(o.body.options.user.name, "yuri@example.com");
    const credential = device.create(o.body.options);
    assert.equal((await h.add({ challenge_id: o.body.challenge_id, consent_token: "other-token", credential })).status, 400, "the challenge is bound to its consent token");
    const o2 = await h.options({ mode: "add", consent_token: "google-consent-token" });
    const added = await h.add({ challenge_id: o2.body.challenge_id, consent_token: "google-consent-token", credential: device.create(o2.body.options) });
    assert.deepEqual([added.status, added.body], [200, { ok: true, backed_up: true }]);
    const again = await h.options({ mode: "add", consent_token: "google-consent-token" });
    assert.deepEqual(again.body.options.excludeCredentials.map((c: any) => c.id), [b64u(device.id)], "the browser is told which passkey already exists");
    const login = await h.options({ mode: "login", login_state: (await h.authorize()).loginState });
    assert.equal((await h.finish("login", login.body.challenge_id, device.get(login.body.options))).status, 200);
    assert.equal(h.consents.at(-1)!.userId, "google-user", "the passkey signs in to the existing account and wallet");
  } finally { await h.close(); }
});

test("the page script converts options and responses correctly for a real browser API shape", async () => {
  const h = await harness(), device = new Authenticator();
  const buf = (s: string) => { const b = Buffer.from(s, "base64url"); return b.buffer.slice(b.byteOffset, b.byteOffset + b.length); };
  const seen: any[] = [];
  const asCredential = (json: any) => ({ id: json.id, rawId: buf(json.rawId), type: json.type, authenticatorAttachment: "platform", getClientExtensionResults: () => ({}),
    response: Object.fromEntries(Object.entries(json.response).map(([k, v]) => k === "transports" ? ["getTransports", () => v] : [k, buf(v as string)])) });
  const navigator = { credentials: {
    create: async ({ publicKey }: any) => { seen.push(publicKey); return asCredential(device.create({ challenge: b64u(new Uint8Array(publicKey.challenge)) })); },
    get: async ({ publicKey }: any) => { seen.push(publicKey); return asCredential(device.get({ challenge: b64u(new Uint8Array(publicKey.challenge)) })); },
  } };
  const context = { window: { PublicKeyCredential: function () {} }, navigator, btoa, atob, fetch: (u: string, i: any) => fetch(h.base + u, i), JSON, Uint8Array, String, Error };
  try {
    const run = (body: object) => runInNewContext(`${passkeyBrowserScript()}; passkey(${JSON.stringify(body)})`, context) as Promise<{ challenge_id: string; credential: string }>;
    const reg = await run({ mode: "register", login_state: (await h.authorize()).loginState });
    assert.ok(seen[0].challenge instanceof ArrayBuffer && seen[0].user.id instanceof ArrayBuffer, "binary fields are ArrayBuffers for the browser");
    assert.equal((await h.finish("register", reg.challenge_id, JSON.parse(reg.credential))).status, 200);
    const login = await run({ mode: "login", login_state: (await h.authorize()).loginState });
    assert.equal((await h.finish("login", login.challenge_id, JSON.parse(login.credential))).status, 200);
    assert.equal(h.consents.at(-1)!.userId, "passkey-user-0");
    assert.equal(runInNewContext(`${passkeyBrowserScript()}; passkeyError({name:"NotAllowedError"})`, context), "Passkey request was cancelled or timed out.");
  } finally { await h.close(); }
});

test("after a GitHub sign-in the consent page offers to add a passkey, with a valid script", async () => {
  const h = await harness(), realFetch = globalThis.fetch;
  try {
    const { loginState } = await h.authorize();
    globalThis.fetch = (async (input: any, init: any) => String(input) === "https://github.com/login/oauth/access_token" ? Response.json({ access_token: "t" }) : String(input) === "https://api.github.com/user" ? Response.json({ id: 1, login: "yuri" }) : realFetch(input, init)) as typeof fetch;
    const r = await realFetch(`${h.base}/auth/github/callback?state=gh-${loginState}&code=c`, { redirect: "manual" });
    const page = await r.text();
    assert.equal(r.status, 200, page);
    assert.match(page, /Add a passkey for next sign-in/);
    assert.match(r.headers.get("content-security-policy") ?? "", /connect-src 'self'/);
    for (const [, js] of page.matchAll(/<script nonce="[^"]+">([\s\S]*?)<\/script>/g)) new Script(js!);
  } finally { globalThis.fetch = realFetch; await h.close(); }
});

test("the page assets are served from this origin with their types, and nothing else is", async () => {
  const h = await harness();
  try {
    const font = await fetch(`${h.base}/assets/geist.woff2`);
    assert.deepEqual([font.status, font.headers.get("content-type"), font.headers.get("x-content-type-options")], [200, "font/woff2", "nosniff"]);
    assert.equal(Buffer.from(await font.arrayBuffer()).subarray(0, 4).toString(), "wOF2");
    const logo = await fetch(`${h.base}/assets/nofrontend-logo.png`);
    assert.deepEqual([logo.status, logo.headers.get("content-type")], [200, "image/png"]);
    for (const path of ["GEIST-LICENSE.txt", "..%2Fpackage.json", "%2E%2E%2Fsrc%2Foauth.ts"]) assert.equal((await fetch(`${h.base}/assets/${path}`)).status, 404, path);
  } finally { await h.close(); }
});
