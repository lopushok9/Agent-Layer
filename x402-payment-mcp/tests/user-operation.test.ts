import assert from "node:assert/strict";
import test from "node:test";
import { randomBytes } from "node:crypto";
import { entryPoint06Address } from "viem/account-abstraction";
import { operationHash, validateOperation, sealOperation, openOperation, type PreparedOperation } from "../src/user-operation.js";
import { sendPreparedOperation } from "../src/alchemy-executor.js";
const address = "0x1111111111111111111111111111111111111111";
export function prepared(): PreparedOperation {
  return { chainId: 8453, entryPoint: entryPoint06Address, blockNumber: "123", operation: { sender: address, nonce: 7n, initCode: "0x", callData: "0xabcd", callGasLimit: 100000n, verificationGasLimit: 150000n, preVerificationGas: 50000n, maxFeePerGas: 200n, maxPriorityFeePerGas: 100n, paymasterAndData: "0x", signature: "0x" } };
}
test("nonce proof binds full operation, sender, EntryPoint and chain", () => {
  const p = prepared(), hash = operationHash(p);
  assert.equal(validateOperation(p, "base", address, hash).nonce, "7");
  for (const mutate of [(x: PreparedOperation) => { x.operation.nonce++; }, (x: PreparedOperation) => { x.operation.callData = "0x1234"; }, (x: PreparedOperation) => { x.chainId = 1; }, (x: PreparedOperation) => { x.entryPoint = address; }]) {
    const x = structuredClone(p); mutate(x); assert.throws(() => validateOperation(x, "base", address, hash));
  }
  assert.throws(() => validateOperation(p, "ethereum", address, hash));
});
test("operation payload encryption is authenticated and bound to its ledger row", () => {
  const key = randomBytes(32).toString("base64"), p = prepared();
  const sealed = sealOperation(p, key, "id");
  assert.ok(!sealed.includes(p.operation.callData)); assert.deepEqual(openOperation(sealed, key, "id"), p);
  assert.throws(() => openOperation(sealed, key, "other-id"));
  assert.throws(() => openOperation(sealed, randomBytes(32).toString("base64"), "id"));
  assert.throws(() => sealOperation(p, undefined, "id"));
});
test("failed durable write prevents signing; lost send response never rebuilds or signs twice", async () => {
  const order: string[] = [], p = prepared();
  const sign = async () => { order.push("sign"); return "0xab" as const; };
  const broadcast = async () => { order.push("send"); throw new Error("timeout"); };
  await assert.rejects(sendPreparedOperation(p, async () => { throw new Error("database"); }, sign, broadcast), /database/);
  assert.equal(order.length, 0);
  await assert.rejects(sendPreparedOperation(p, async (hash, proof) => { assert.equal(hash, operationHash(p)); assert.deepEqual(proof, p); order.push("persist"); }, sign, broadcast), /timeout/);
  assert.deepEqual(order, ["persist", "sign", "send"]);
});

test("viem wraps the CDP owner signature for the exact ERC-4337 hash", async () => {
  const { privateKeyToAccount } = await import("viem/accounts");
  const { createPublicClient, custom, encodeAbiParameters, pad, decodeAbiParameters, recoverAddress } = await import("viem");
  const { base } = await import("viem/chains");
  const { coinbaseAccount } = await import("../src/alchemy-executor.js");
  const local = privateKeyToAccount(`0x${"01".repeat(32)}`);
  const requests: string[] = [];
  const rpc = createPublicClient({ chain: base, transport: custom({ request: async ({ method, params }: any) => {
    requests.push(method);
    if (method === "eth_chainId") return "0x2105";
    if (method === "eth_getCode") return "0x6000";
    if (method === "eth_call") {
      if (params[0].to.toLowerCase() === "0xba5ed110efdba3d005bfc882d75358acbbb85842") return encodeAbiParameters([{ type: "address" }], [address]);
      const { toFunctionSelector } = await import("viem");
      if (params[0].data.startsWith(toFunctionSelector("ownerAtIndex(uint256)"))) return encodeAbiParameters([{ type: "bytes" }], [pad(local.address)]);
      return encodeAbiParameters([{ type: "address" }], [entryPoint06Address]);
    }
    throw new Error("Unexpected RPC in signing test");
  } }) });
  let signedHash = "";
  const owner = { ...local, sign: async ({ hash }: { hash: `0x${string}` }) => { signedHash = hash; return local.sign!({ hash }); } };
  const account = await coinbaseAccount(rpc as any, { address, owners: [owner] } as any, "base");
  const p = prepared(), signature = await account.signUserOperation(p.operation);
  const [wrapped] = decodeAbiParameters([{ type: "tuple", components: [{ name: "ownerIndex", type: "uint256" }, { name: "signatureData", type: "bytes" }] }], signature);
  assert.equal(wrapped.ownerIndex, 0n); assert.equal(signedHash, operationHash(p));
  assert.equal(await recoverAddress({ hash: operationHash(p), signature: wrapped.signatureData }), local.address);
  assert.ok(!requests.some(m => /send|sign/.test(m)), "RPC never receives signing requests");
});
