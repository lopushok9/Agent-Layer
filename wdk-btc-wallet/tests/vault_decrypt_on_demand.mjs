// Focused verification of the decrypt-on-demand LocalBtcVault model.
// Run: node tests/vault_decrypt_on_demand.mjs
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { LocalBtcVault } from "../src/local_vault.js";

const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), "wdk-btc-vault-test-"));
const config = { dataDir, network: "bitcoin", unlockTimeoutSeconds: 0 };
const vault = new LocalBtcVault(config);
const PASSWORD = "correct horse battery staple";

async function main() {
  const created = await vault.createWallet({
    label: "test",
    password: PASSWORD,
    network: "bitcoin",
    revealSeedPhrase: true,
  });
  assert.equal(created.unlocked, false, "createWallet must not persist an unlocked state");
  assert.ok(created.seedPhrase, "revealSeedPhrase should return the seed once");
  const walletId = created.walletId;

  assert.equal(vault._unlocked, undefined, "vault must not keep an _unlocked map");

  const resolved = await vault.resolveSeedPhrase({ walletId, password: PASSWORD });
  assert.equal(resolved.source, "local-vault-jit");
  assert.equal(resolved.seedPhrase, created.seedPhrase, "JIT decrypt must match the created seed");

  await assert.rejects(() => vault.resolveSeedPhrase({ walletId }), /wallet is locked/i);
  await assert.rejects(() => vault.resolveSeedPhrase({ walletId, password: "nope" }), /invalid password/i);

  const unlock = await vault.unlockWallet({ walletId, password: PASSWORD });
  assert.equal(unlock.unlocked, false, "deprecated unlock must not report a persisted unlock");
  assert.equal(unlock.deprecated, true);
  await assert.rejects(() => vault.resolveSeedPhrase({ walletId }), /wallet is locked/i);

  // Continuity across a fresh instance (simulated restart): file still decrypts.
  const fileRaw = JSON.parse(
    await fs.readFile(path.join(dataDir, "wallets", `${walletId}.json`), "utf8"),
  );
  assert.equal(fileRaw.cipher.name, "aes-256-gcm");
  assert.equal(fileRaw.kdf.name, "scrypt");
  const freshVault = new LocalBtcVault(config);
  const afterRestart = await freshVault.resolveSeedPhrase({ walletId, password: PASSWORD });
  assert.equal(afterRestart.seedPhrase, created.seedPhrase, "seed must survive a restart with no unlock");

  console.log("vault_decrypt_on_demand (btc): ok");
}

main()
  .catch((error) => {
    console.error("vault_decrypt_on_demand (btc): FAIL");
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await fs.rm(dataDir, { recursive: true, force: true });
  });
