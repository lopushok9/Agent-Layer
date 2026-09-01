import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  transactionIdempotencyKey,
  checkTransactionIdempotency,
  recordTransactionSent,
  updateTransactionConfirmationStatus,
} from "../src/pending_transactions.js";

function tempDataDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "wdk-evm-idempotency-"));
}

test("transactionIdempotencyKey is stable for the same resolved call and differs for a different one", () => {
  const a = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
  const b = transactionIdempotencyKey({ from: "0xf00", to: "0xaaa", data: "0x1", value: "0", chainId: 8453 });
  const c = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x2", value: "0", chainId: 8453 });
  assert.equal(a, b, "case must not matter for addresses/calldata");
  assert.notEqual(a, c);
});

test("transactionIdempotencyKey differs for two accounts sending the same resolved call", () => {
  // Two different senders (two accountIndex values under one wallet, or two
  // seed phrases under wdk_evm_local) broadcasting an otherwise byte-identical
  // transaction within the match window must never collide -- the store is
  // shared across every account that uses this daemon's data directory.
  const senderA = transactionIdempotencyKey({
    from: "0x1111111111111111111111111111111111111111",
    to: "0xAAA",
    data: "0x1",
    value: "0",
    chainId: 8453,
  });
  const senderB = transactionIdempotencyKey({
    from: "0x2222222222222222222222222222222222222222",
    to: "0xAAA",
    data: "0x1",
    value: "0",
    chainId: 8453,
  });
  assert.notEqual(senderA, senderB, "the same call from two different senders must not collide");
});

test("a duplicate warning from one account never fires for an identical send from a different account", async () => {
  const dataDir = tempDataDir();
  try {
    const ACCOUNT_A = "0x1111111111111111111111111111111111111111";
    const ACCOUNT_B = "0x2222222222222222222222222222222222222222";
    const callShape = { to: "0xAAA", data: "0x1", value: "0", chainId: 8453 };

    const keyA = transactionIdempotencyKey({ from: ACCOUNT_A, ...callShape });
    await recordTransactionSent(dataDir, { key: keyA, txHash: "0xfromA", network: "base", operation: "native_transfer" });

    // Account B sends the exact same {to, data, value, chainId} shortly after.
    const keyB = transactionIdempotencyKey({ from: ACCOUNT_B, ...callShape });
    assert.equal(
      await checkTransactionIdempotency(dataDir, keyB),
      null,
      "a different sender's identical call must not be flagged as A's duplicate"
    );

    // Sanity: A's own retry against the same call is still correctly flagged.
    assert.ok(
      await checkTransactionIdempotency(dataDir, keyA),
      "the same sender's own retry must still be flagged"
    );
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("no prior entry means no duplicate", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    assert.equal(await checkTransactionIdempotency(dataDir, key), null);
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("a recent submitted entry is reported as a duplicate", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key, txHash: "0xfirst", network: "base", operation: "morpho_vault_withdraw" });
    const result = await checkTransactionIdempotency(dataDir, key);
    assert.ok(result);
    assert.equal(result.duplicate.tx_hash, "0xfirst");
    assert.equal(result.duplicate.status, "submitted");
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("a confirmed entry is still reported as a duplicate", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, {
      key,
      txHash: "0xfirst",
      network: "base",
      operation: "morpho_vault_withdraw",
      confirmationStatus: "confirmed",
    });
    const result = await checkTransactionIdempotency(dataDir, key);
    assert.equal(result.duplicate.status, "confirmed");
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("a reverted entry is never reported as a duplicate", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, {
      key,
      txHash: "0xfirst",
      network: "base",
      operation: "morpho_vault_withdraw",
      confirmationStatus: "reverted",
    });
    assert.equal(await checkTransactionIdempotency(dataDir, key), null);
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("an entry outside the match window is not reported as a duplicate", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key, txHash: "0xold", network: "base", operation: "morpho_vault_withdraw" });
    // Backdate the recorded entry past the default 30-minute window.
    const storePath = path.join(dataDir, "pending-transactions.json");
    const stored = JSON.parse(fs.readFileSync(storePath, "utf8"));
    stored.entries[0].broadcast_at = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    fs.writeFileSync(storePath, JSON.stringify(stored, null, 2));
    assert.equal(await checkTransactionIdempotency(dataDir, key), null);
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("recordTransactionSent prunes entries older than the match window on every write", async () => {
  const dataDir = tempDataDir();
  try {
    const staleKey = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key: staleKey, txHash: "0xold", network: "base", operation: "x" });
    const storePath = path.join(dataDir, "pending-transactions.json");
    const stored = JSON.parse(fs.readFileSync(storePath, "utf8"));
    stored.entries[0].broadcast_at = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    fs.writeFileSync(storePath, JSON.stringify(stored, null, 2));

    const freshKey = transactionIdempotencyKey({ to: "0xBBB", data: "0x2", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key: freshKey, txHash: "0xnew", network: "base", operation: "y" });

    const afterWrite = JSON.parse(fs.readFileSync(storePath, "utf8"));
    assert.equal(afterWrite.entries.length, 1);
    assert.equal(afterWrite.entries[0].key, freshKey);
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("updateTransactionConfirmationStatus rewrites an existing entry's status", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key, txHash: "0xfirst", network: "base", operation: "morpho withdraw" });
    const storePath = path.join(dataDir, "pending-transactions.json");
    const before = JSON.parse(fs.readFileSync(storePath, "utf8"));
    assert.equal(before.entries[0].confirmation_status, "submitted");

    assert.equal(await updateTransactionConfirmationStatus(dataDir, "0xfirst", "confirmed"), true);

    const after = JSON.parse(fs.readFileSync(storePath, "utf8"));
    assert.equal(after.entries.length, 1, "updating must not add an entry");
    assert.equal(after.entries[0].confirmation_status, "confirmed");
    assert.equal(after.entries[0].key, key, "the entry's identity must be preserved");
    assert.ok(
      after.entries[0].last_checked_at >= before.entries[0].last_checked_at,
      "last_checked_at must be refreshed"
    );
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("updateTransactionConfirmationStatus is a safe no-op for an unknown tx_hash", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key, txHash: "0xfirst", network: "base", operation: "native_transfer" });

    assert.equal(await updateTransactionConfirmationStatus(dataDir, "0xnothere", "reverted"), false);

    const storePath = path.join(dataDir, "pending-transactions.json");
    const stored = JSON.parse(fs.readFileSync(storePath, "utf8"));
    assert.equal(stored.entries.length, 1, "an unknown hash must not add a spurious entry");
    assert.equal(stored.entries[0].tx_hash, "0xfirst");
    assert.equal(stored.entries[0].confirmation_status, "submitted", "the untouched entry keeps its status");
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("updateTransactionConfirmationStatus against an empty store does not throw or create entries", async () => {
  const dataDir = tempDataDir();
  try {
    assert.equal(await updateTransactionConfirmationStatus(dataDir, "0xghost", "reverted"), false);
    assert.equal(fs.existsSync(path.join(dataDir, "pending-transactions.json")), false);
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("a send confirmed as reverted stops being reported as a duplicate", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key, txHash: "0xfirst", network: "base", operation: "morpho withdraw" });
    assert.ok(
      await checkTransactionIdempotency(dataDir, key),
      "a freshly submitted entry is a duplicate candidate"
    );

    // What confirmTransaction now does when the receipt reports status 0x0.
    await updateTransactionConfirmationStatus(dataDir, "0xfirst", "reverted");

    assert.equal(
      await checkTransactionIdempotency(dataDir, key),
      null,
      "retrying a genuinely reverted operation must not be flagged as a duplicate"
    );
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("32 concurrent recordTransactionSent calls all persist, none lost to a write race", async () => {
  const dataDir = tempDataDir();
  try {
    const CONCURRENCY = 32;
    await Promise.all(
      Array.from({ length: CONCURRENCY }, (_, i) =>
        recordTransactionSent(dataDir, {
          key: `key-${i}`,
          txHash: `0xhash${i}`,
          network: "base",
          operation: "native_transfer",
        })
      )
    );
    const storePath = path.join(dataDir, "pending-transactions.json");
    const stored = JSON.parse(fs.readFileSync(storePath, "utf8"));
    assert.equal(
      stored.entries.length,
      CONCURRENCY,
      `expected all ${CONCURRENCY} concurrent writes to persist, found ${stored.entries.length}`
    );
    const hashes = new Set(stored.entries.map((entry) => entry.tx_hash));
    assert.equal(hashes.size, CONCURRENCY, "every entry must be distinct, none overwritten by another");
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("a concurrent recordTransactionSent and updateTransactionConfirmationStatus do not race each other", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key, txHash: "0xfirst", network: "base", operation: "native_transfer" });

    // Fire a status update on the existing entry and a brand-new record at
    // the same time -- both are read-modify-write cycles against the same
    // file, and must not clobber each other.
    await Promise.all([
      updateTransactionConfirmationStatus(dataDir, "0xfirst", "confirmed"),
      recordTransactionSent(dataDir, { key: "other-key", txHash: "0xsecond", network: "base", operation: "native_transfer" }),
    ]);

    const storePath = path.join(dataDir, "pending-transactions.json");
    const stored = JSON.parse(fs.readFileSync(storePath, "utf8"));
    assert.equal(stored.entries.length, 2, "both the update and the new record must survive");
    const first = stored.entries.find((entry) => entry.tx_hash === "0xfirst");
    const second = stored.entries.find((entry) => entry.tx_hash === "0xsecond");
    assert.ok(first, "the original entry must not have been dropped");
    assert.equal(first.confirmation_status, "confirmed", "the concurrent update must not be lost");
    assert.ok(second, "the concurrent new entry must not have been dropped");
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});

test("a second identical send within the window is still broadcast, but flagged", async () => {
  const dataDir = tempDataDir();
  try {
    const key = transactionIdempotencyKey({ from: "0xF00", to: "0xAAA", data: "0x1", value: "0", chainId: 8453 });
    await recordTransactionSent(dataDir, { key, txHash: "0xfirst", network: "base", operation: "native_transfer" });

    const duplicateCheck = await checkTransactionIdempotency(dataDir, key);
    assert.ok(duplicateCheck, "expected the second send to see the first as a duplicate candidate");

    // The warn-not-block contract: the caller proceeds to broadcast and
    // record the new send regardless of duplicateCheck's result.
    await recordTransactionSent(dataDir, { key, txHash: "0xsecond", network: "base", operation: "native_transfer" });
    const storePath = path.join(dataDir, "pending-transactions.json");
    const stored = JSON.parse(fs.readFileSync(storePath, "utf8"));
    assert.equal(stored.entries.length, 2, "both attempts must be recorded, not deduplicated away");
  } finally {
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});
