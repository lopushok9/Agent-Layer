import assert from "node:assert/strict";
import test from "node:test";

import { __testables } from "../src/wdk_evm_wallet.js";

const { confirmTransaction, setRpcRequestForTests } = __testables;

const RUNTIME_CONFIG = { providerUrl: "http://example.invalid", network: "base" };

test("confirmTransaction returns confirmed when the receipt lands with status 0x1", async () => {
  setRpcRequestForTests(async () => ({ status: "0x1", blockNumber: "0x10" }));
  try {
    const result = await confirmTransaction(RUNTIME_CONFIG, "0xabc", { maxWaitMs: 500 });
    assert.deepEqual(result, { status: "confirmed", receipt: { status: "0x1", blockNumber: "0x10" } });
  } finally {
    setRpcRequestForTests(null);
  }
});

test("confirmTransaction throws a tagged error when the receipt shows a revert", async () => {
  setRpcRequestForTests(async () => ({ status: "0x0" }));
  try {
    await assert.rejects(
      () => confirmTransaction(RUNTIME_CONFIG, "0xabc", { operationLabel: "Test op", failureCode: "test_reverted", maxWaitMs: 500 }),
      (error) => {
        assert.equal(error.errorCode, "test_reverted");
        assert.equal(error.errorDetails.txHash, "0xabc");
        return true;
      }
    );
  } finally {
    setRpcRequestForTests(null);
  }
});

test("confirmTransaction returns submitted when the wait window elapses with clean but empty responses", async () => {
  setRpcRequestForTests(async () => null);
  try {
    const result = await confirmTransaction(RUNTIME_CONFIG, "0xabc", { maxWaitMs: 1200 });
    assert.deepEqual(result, { status: "submitted" });
  } finally {
    setRpcRequestForTests(null);
  }
});

test("confirmTransaction returns unknown when every poll attempt errors", async () => {
  setRpcRequestForTests(async () => {
    throw new Error("connect ECONNREFUSED");
  });
  try {
    const result = await confirmTransaction(RUNTIME_CONFIG, "0xabc", { maxWaitMs: 1200 });
    assert.deepEqual(result, { status: "unknown" });
  } finally {
    setRpcRequestForTests(null);
  }
});

test("confirmTransaction recovers to submitted if a later poll succeeds after early errors", async () => {
  let calls = 0;
  setRpcRequestForTests(async () => {
    calls += 1;
    if (calls === 1) throw new Error("transient");
    return null;
  });
  try {
    const result = await confirmTransaction(RUNTIME_CONFIG, "0xabc", { maxWaitMs: 1200 });
    assert.deepEqual(result, { status: "submitted" });
  } finally {
    setRpcRequestForTests(null);
  }
});

test("a submitted (not yet confirmed) result still carries a usable tx_hash and status", async () => {
  setRpcRequestForTests(async () => null);
  try {
    const confirmation = await confirmTransaction(RUNTIME_CONFIG, "0xdeadbeef", { maxWaitMs: 500 });
    const merged = {
      result: { hash: "0xdeadbeef" },
      confirmed: confirmation.status === "confirmed",
      tx_hash: "0xdeadbeef",
      confirmation_status: confirmation.status,
    };
    assert.equal(merged.confirmed, false);
    assert.equal(merged.tx_hash, "0xdeadbeef");
    assert.equal(merged.confirmation_status, "submitted");
  } finally {
    setRpcRequestForTests(null);
  }
});
