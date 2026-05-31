// Focused verification of the decrypt-on-demand LocalEvmVault model.
// Run: node tests/vault_decrypt_on_demand.mjs
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { LocalEvmVault } from "../src/local_vault.js";

const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), "wdk-evm-vault-test-"));
const config = { dataDir, network: "sepolia", unlockTimeoutSeconds: 0 };
const vault = new LocalEvmVault(config);
const PASSWORD = "correct horse battery staple";

async function main() {
  // 1. Create: must NOT report a persisted unlocked state.
  const created = await vault.createWallet({
    label: "test",
    password: PASSWORD,
    network: "sepolia",
    revealSeedPhrase: true,
  });
  assert.equal(created.unlocked, false, "createWallet must not persist an unlocked state");
  assert.ok(created.seedPhrase, "revealSeedPhrase should return the seed once");
  const walletId = created.walletId;

  // 2. The vault holds no in-memory unlocked map.
  assert.equal(vault._unlocked, undefined, "vault must not keep an _unlocked map");

  // 3. resolveSeedPhrase requires a password (decrypt-on-demand) and returns the seed.
  const resolved = await vault.resolveSeedPhrase({ walletId, password: PASSWORD });
  assert.equal(resolved.source, "local-vault-jit");
  assert.equal(resolved.seedPhrase, created.seedPhrase, "JIT decrypt must match the created seed");

  // 4. Without a password (and no seedPhrase) it reports a locked error -> maps to wallet_locked.
  await assert.rejects(
    () => vault.resolveSeedPhrase({ walletId }),
    /wallet is locked/i,
    "missing password must be reported as locked",
  );

  // 5. Wrong password fails with Invalid password.
  await assert.rejects(
    () => vault.resolveSeedPhrase({ walletId, password: "nope" }),
    /invalid password/i,
    "wrong password must fail",
  );

  // 6. Explicit seedPhrase in the request bypasses the vault (no password needed).
  const passthrough = await vault.resolveSeedPhrase({ seedPhrase: created.seedPhrase });
  assert.equal(passthrough.source, "request");

  // 7. unlock/lock are deprecated no-ops: unlock verifies the password but never persists.
  const unlock = await vault.unlockWallet({ walletId, password: PASSWORD });
  assert.equal(unlock.unlocked, false, "deprecated unlock must not report a persisted unlock");
  assert.equal(unlock.deprecated, true);
  const lock = await vault.lockWallet({ walletId });
  assert.equal(lock.unlocked, false);
  // After a deprecated unlock, the seed is STILL only obtainable via password (no state kept).
  await assert.rejects(() => vault.resolveSeedPhrase({ walletId }), /wallet is locked/i);

  // 8. Continuity: the encrypted file on disk is the unchanged AES-256-GCM/scrypt envelope
  //    and still decrypts after a fresh vault instance (simulates a service restart).
  const fileRaw = JSON.parse(
    await fs.readFile(path.join(dataDir, "wallets", `${walletId}.json`), "utf8"),
  );
  assert.equal(fileRaw.cipher.name, "aes-256-gcm");
  assert.equal(fileRaw.kdf.name, "scrypt");
  const freshVault = new LocalEvmVault(config);
  const afterRestart = await freshVault.resolveSeedPhrase({ walletId, password: PASSWORD });
  assert.equal(afterRestart.seedPhrase, created.seedPhrase, "seed must survive a restart with no unlock");

  // 9. changePassword re-encrypts and the old password no longer works.
  await vault.changePassword({ walletId, currentPassword: PASSWORD, newPassword: "new-pass-123" });
  await assert.rejects(() => vault.resolveSeedPhrase({ walletId, password: PASSWORD }), /invalid password/i);
  const reResolved = await vault.resolveSeedPhrase({ walletId, password: "new-pass-123" });
  assert.equal(reResolved.seedPhrase, created.seedPhrase);

  console.log("vault_decrypt_on_demand: ok");
}

main()
  .catch((error) => {
    console.error("vault_decrypt_on_demand: FAIL");
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await fs.rm(dataDir, { recursive: true, force: true });
  });
