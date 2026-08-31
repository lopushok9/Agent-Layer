// Integration-style test proving the idempotency wiring in wdk_evm_wallet.js
// (not just pending_transactions.js in isolation) actually surfaces a
// duplicate_warning on a real send call site's response. This would fail if
// the wiring added to sendNativeTransfer were ever removed.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import WalletManagerEvm from "@tetherto/wdk-wallet-evm";

import { WdkEvmWalletService, __testables } from "../src/wdk_evm_wallet.js";

const { setRpcRequestForTests } = __testables;

const VALID_MNEMONIC =
  "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
const RECIPIENT = "0x2222222222222222222222222222222222222222";

function tempDataDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "wdk-evm-send-idempotency-"));
}

function createHarness({ dataDir }) {
  const sentTransactions = [];
  const originalGetAccount = WalletManagerEvm.prototype.getAccount;
  const originalDispose = WalletManagerEvm.prototype.dispose;

  const fakeAccount = {
    async getAddress() {
      return "0x1111111111111111111111111111111111111111";
    },
    async sendTransaction(tx) {
      sentTransactions.push(tx);
      const hash = `0x${String(sentTransactions.length).padStart(64, "d")}`;
      return { hash, fee: 1n };
    },
  };

  WalletManagerEvm.prototype.getAccount = async function getAccount() {
    return fakeAccount;
  };
  WalletManagerEvm.prototype.dispose = function dispose() {};

  const service = new WdkEvmWalletService({
    network: "base",
    dataDir,
    networkProfiles: {
      base: {
        chainId: 8453,
        providerUrl: "http://fake-rpc.local",
        nativeSymbol: "ETH",
      },
    },
  });

  function restore() {
    WalletManagerEvm.prototype.getAccount = originalGetAccount;
    WalletManagerEvm.prototype.dispose = originalDispose;
  }

  return { service, sentTransactions, restore };
}

test("sendNativeTransfer flags a second identical send as a likely duplicate, but still broadcasts it", async () => {
  const dataDir = tempDataDir();
  const harness = createHarness({ dataDir });
  // confirmTransaction() polls the RPC for a real receipt; hand back an
  // immediately-confirmed receipt so this test isn't paced by its retry/
  // backoff window, which has nothing to do with the idempotency wiring
  // under test.
  setRpcRequestForTests(async () => ({ status: "0x1", blockNumber: "0x10" }));
  try {
    const params = {
      seedPhrase: VALID_MNEMONIC,
      to: RECIPIENT,
      value: "1000000000000000",
      network: "base",
    };

    const first = await harness.service.sendNativeTransfer(params);
    assert.equal(first.duplicate_warning, undefined, "first send must not be flagged");
    assert.ok(first.tx_hash, "first send must report a tx_hash");

    const second = await harness.service.sendNativeTransfer(params);
    assert.ok(
      second.duplicate_warning,
      "second identical send within the idempotency window must carry duplicate_warning"
    );
    assert.equal(
      second.duplicate_warning.tx_hash,
      first.tx_hash,
      "duplicate_warning must point back at the first send's tx_hash"
    );
    // Warn-not-block: the second send must still have gone out for real.
    assert.equal(harness.sentTransactions.length, 2, "both sends must actually broadcast");
    assert.notEqual(second.tx_hash, first.tx_hash, "each broadcast still gets its own tx_hash");
  } finally {
    setRpcRequestForTests(null);
    harness.restore();
    fs.rmSync(dataDir, { recursive: true, force: true });
  }
});
