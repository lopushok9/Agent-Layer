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

test("the exact UserOperation hash must be durably recorded before owner signing", async () => {
  // Exercise the actual pinned SDK implementation, not a copy of its signing
  // sequence. This test must fail if an SDK update bypasses owner.sign(hash).
  const { sendUserOperation } = await import(new URL("./actions/evm/sendUserOperation.js", import.meta.resolve("@coinbase/cdp-sdk")).href);
  const order: string[] = [];
  const owner = { address: ownerAddress, sign: async () => { order.push("sign"); return "0x12"; } };
  const api = {
    prepareUserOperation: async () => ({ userOpHash: hash, status: "pending" }),
    sendUserOperation: async (_address: string, h: string, body: any, id: string) => { assert.equal(h, hash); assert.equal(body.signature, "0x12"); assert.equal(id, "idempotency-key"); order.push("submit"); return { status: "broadcast" }; },
  };
  const cdp = { evm: {
    getOrCreateAccount: async () => owner, getOrCreateSmartAccount: async () => ({ address, owners: [owner] }),
    sendUserOperation: async (p: any) => sendUserOperation(api, p),
  } };
  const wallets = new SmartWalletService({ BASE_PAYMASTER_URL: "https://paymaster.example" } as any, { wallet: async () => null, saveWallet: async () => {} }, cdp as any);
  await wallets.send("user", "base", [{ to: ownerAddress, value: "0", data: "0x" }], "idempotency-key", async h => { assert.equal(h, hash); order.push("persist"); });
  assert.deepEqual(order, ["persist", "sign", "submit"]);
  order.length = 0;
  await assert.rejects(wallets.send("user", "base", [{ to: ownerAddress, value: "0", data: "0x" }], "id", async () => { throw new Error("database unavailable"); }), /database unavailable/);
  assert.deepEqual(order, [], "failed durable write must prevent signing and submission");
});

