import assert from "node:assert/strict";
import test from "node:test";
import { randomBytes, randomUUID } from "node:crypto";
import { Store } from "../src/store.js";

// Runs the real SQL against Postgres when TEST_DATABASE_URL is set; skipped otherwise.
const url = process.env.TEST_DATABASE_URL;

test("passkey SQL round-trips against Postgres", { skip: !url }, async () => {
  const store = new Store(url!);
  try {
    await store.migrate(); await store.migrate();
    const passkey = (id: string) => ({ id, publicKey: new Uint8Array(randomBytes(77)), counter: 0, transports: ["internal", "hybrid"], deviceType: "multiDevice" as const, backedUp: true });

    const id = randomBytes(16).toString("base64url");
    const newUser = await store.savePasskey(passkey(id));
    const stored = await store.passkeyCredential(id);
    assert.equal(stored!.userId, newUser);
    assert.equal(stored!.publicKey.length, 77);
    assert.deepEqual(stored!.transports, ["internal", "hybrid"]);
    const identity = await store.pool.query(`SELECT user_id FROM oauth_identities WHERE provider='passkey' AND provider_subject=$1`, [id]);
    assert.equal(identity.rows[0].user_id, newUser, "a passkey is an identity of its user");
    await assert.rejects(store.savePasskey(passkey(id)), "a credential id belongs to one user");
    assert.equal((await store.pool.query(`SELECT count(*)::int AS n FROM users WHERE id=$1`, [newUser])).rows[0].n, 1);

    const googleUser = await store.upsertIdentity("google", `passkey-test-${Date.now()}`, "Yuri", "yuri@example.com");
    const second = randomBytes(16).toString("base64url");
    assert.equal(await store.savePasskey(passkey(second), googleUser), googleUser);
    assert.deepEqual((await store.passkeyIds(googleUser)).map(c => c.id), [second]);
    await store.markPasskeyUsed(second, 5, false);
    assert.equal((await store.passkeyCredential(second))!.counter, 5);

    const client = await store.registerClient("test", ["https://client.example/cb"]);
    const state = { clientId: client.clientId, redirectUri: "https://client.example/cb", state: "s", codeChallenge: "c".repeat(43), resource: "https://pay.example/mcp", scope: "x402:pay" };
    const loginState = await store.createLoginState(state);
    const challengeId = await store.createPasskeyChallenge({ purpose: "login", challenge: "abc", loginState });
    assert.equal(await store.consumePasskeyChallenge(challengeId, "register"), null, "purpose must match");
    assert.deepEqual(await store.consumePasskeyChallenge(challengeId, "login"), { challenge: "abc", loginState, consentTokenHash: null });
    assert.equal(await store.consumePasskeyChallenge(challengeId, "login"), null, "single use");
    assert.equal(await store.consumePasskeyChallenge("not-a-uuid", "login"), null);

    const consent = await store.createPendingConsent({ ...state, id: randomUUID() }, googleUser, 300);
    assert.deepEqual(await store.pendingConsentUser(consent), { userId: googleUser, name: "yuri@example.com" });
    await store.approvePendingConsent(consent);
    assert.equal(await store.pendingConsentUser(consent), null, "an approved consent no longer proves a fresh sign-in");
  } finally { await store.pool.end(); }
});
