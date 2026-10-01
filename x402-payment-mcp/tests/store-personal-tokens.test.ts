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

test("Arc transfer previews are single use and the daily cap holds", { skip: !url }, async () => {
  const store = new Store(url!);
  try {
    await store.migrate();
    const userId = await store.upsertIdentity("github", `arc-test-${Date.now()}`, "Tester", null);
    const to = "0x2222222222222222222222222222222222222222";
    const first = await store.createArcPreview({ userId, to, amount: 150_000_000n, fee: 1200n }, 120);
    const reserved = await store.reserveArcTransfer(userId, first.id, "first", 200_000_000n);
    assert.equal(reserved?.amount, 150_000_000n); assert.equal(reserved?.to, to);
    assert.equal(await store.reserveArcTransfer(userId, first.id, "replay", 200_000_000n), null, "a preview sends once");
    assert.equal(await store.arcTransferredToday(userId), 150_000_000n);

    const second = await store.createArcPreview({ userId, to, amount: 60_000_000n, fee: 1200n }, 120);
    await assert.rejects(store.reserveArcTransfer(userId, second.id, "over cap", 200_000_000n), /daily Arc transfer limit/);
    const stillUnused = await store.pool.query(`SELECT used_at FROM arc_transfer_previews WHERE id=$1`, [second.id]);
    assert.equal(stillUnused.rows[0].used_at, null, "a rejected reservation does not burn the preview");

    await store.finishArcTransfer(reserved!.transferId, "failed", null, "signing failed");
    assert.equal(await store.arcTransferredToday(userId), 0n, "failed transfers do not count toward the cap");
    assert.equal((await store.reserveArcTransfer(userId, second.id, "now fits", 200_000_000n))?.amount, 60_000_000n);
    await store.finishArcTransfer(reserved!.transferId, "unknown", "0xabc", "rpc timeout");
    assert.equal(await store.arcTransferredToday(userId), 210_000_000n, "unknown outcomes stay charged");

    const other = await store.upsertIdentity("github", `arc-other-${Date.now()}`, "Other", null);
    const foreign = await store.createArcPreview({ userId, to, amount: 1n, fee: 1n }, 120);
    assert.equal(await store.reserveArcTransfer(other, foreign.id, "steal", 200_000_000n), null, "another user cannot use a preview");
  } finally { await store.close(); }
});
