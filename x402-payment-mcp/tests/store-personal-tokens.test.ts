import assert from "node:assert/strict";
import test from "node:test";
import { newPersonalToken, sha256 } from "../src/security.js";
import { Store } from "../src/store.js";

// Runs the real SQL against Postgres when TEST_DATABASE_URL is set; skipped otherwise.
const url = process.env.TEST_DATABASE_URL;

test("personal access token SQL round-trips against Postgres", { skip: !url }, async () => {
  const store = new Store(url!);
  try {
    await store.migrate(); await store.migrate(); // idempotent
    const userId = await store.upsertIdentity("github", `pat-test-${Date.now()}`, "Tester", null);

    const loginState = await store.createTokenLoginState();
    assert.equal(await store.hasTokenLoginState(loginState), true);
    assert.equal(await store.consumeTokenLoginState(loginState), true);
    assert.equal(await store.consumeTokenLoginState(loginState), false, "login state is single use");

    const session = await store.createTokenManagerSession(userId, 900);
    assert.equal(await store.getTokenManagerSession(session), userId);
    assert.equal(await store.getTokenManagerSession("forged"), null);

    const token = newPersonalToken();
    const created = await store.createPersonalToken(userId, token, "Muse", "x402:pay", 90, 2);
    assert.ok(created); assert.equal(created.hint, token.slice(-4));
    const stored = await store.pool.query(`SELECT token_hash FROM personal_access_tokens WHERE id=$1`, [created.id]);
    assert.equal(stored.rows[0].token_hash, sha256(token), "only the hash is stored");
    assert.ok(Math.abs(created.expiresAt.getTime() - (Date.now() + 90 * 86400000)) < 60000);

    const verified = await store.verifyPersonalToken(token);
    assert.equal(verified?.userId, userId); assert.equal(verified?.scope, "x402:pay");
    assert.equal((await store.listPersonalTokens(userId)).length, 1);
    assert.equal((await store.listPersonalTokens(userId))[0]!.lastUsedAt !== null, true);

    assert.ok(await store.createPersonalToken(userId, newPersonalToken(), "second", "x402:pay", 90, 2));
    assert.equal(await store.createPersonalToken(userId, newPersonalToken(), "third", "x402:pay", 90, 2), null, "cap on active tokens");

    assert.equal(await store.revokePersonalToken("00000000-0000-0000-0000-000000000000", created.id), false, "another user cannot revoke");
    assert.equal(await store.revokePersonalToken(userId, created.id), true);
    assert.equal(await store.verifyPersonalToken(token), null, "revoked tokens stop verifying");
    assert.equal((await store.listPersonalTokens(userId)).length, 1);

    const expired = newPersonalToken();
    const e = await store.createPersonalToken(userId, expired, "expired", "x402:pay", 1, 5);
    await store.pool.query(`UPDATE personal_access_tokens SET expires_at=now()-interval '1 second' WHERE id=$1`, [e!.id]);
    assert.equal(await store.verifyPersonalToken(expired), null, "expired tokens stop verifying");

    await store.cleanupOAuthArtifacts();
  } finally { await store.close(); }
});
