import assert from "node:assert/strict";
import test from "node:test";
import { SmartWalletService } from "../src/smart-wallet.js";

const ownerAddress = "0x1111111111111111111111111111111111111111";
const address = "0x2222222222222222222222222222222222222222";
const hash = `0x${"a".repeat(64)}` as const;
test("fresh smart wallet uses a separate namespace and never exposes owner as receive address", async () => {
  let saved: any = null; const names: string[] = [];
  const cdp = { evm: { getOrCreateAccount: async ({ name }: any) => { names.push(name); return { address: ownerAddress }; }, getOrCreateSmartAccount: async ({ name, owner }: any) => { names.push(name); return { address, owners: [owner] }; } } };
  const wallets = new SmartWalletService({} as any, { wallet: async () => saved, saveWallet: async (_user, w) => { saved = w; } }, cdp as any);
  assert.equal((await wallets.account("user")).address, address);
  assert.equal(saved.ownerAddress, ownerAddress);
  assert.ok(names[0]!.startsWith("owner-v2-")); assert.ok(names[1]!.startsWith("smart-v2-"));
  assert.ok(names.every(n => n.length <= 36));
  saved.address = ownerAddress;
  await assert.rejects(wallets.account("user"), /registry/);
});
