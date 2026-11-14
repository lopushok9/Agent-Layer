import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, parseAbi } from "viem";
import { NearNameRegistration } from "../src/near/names.js";
import { NearPublicError } from "../src/near/operations.js";

const owner = "0xD09d6F783A9840E5Ca35E134912765dc11C895A1";
const abi = parseAbi([
  "struct RegisterRequest { string name; address owner; uint256 duration; address resolver; bytes[] data; bool reverseRecord; uint256[] coinTypes; uint256 signatureExpiry; bytes signature; }",
  "function register(RegisterRequest request) payable",
]);
function setup(available = true) {
  const calls: any[] = [];
  const chain: any = {
    fromAddress: async (user: string) => { assert.equal(user, "alice"); return owner; },
    rpcFor: (network: string) => { assert.equal(network, "base"); return { readContract: async ({ functionName }: any) => ({ valid: true, available, registerPrice: 123n } as any)[functionName] }; },
    prepare: async (user: string, input: any) => { calls.push({ user, input }); return { operation_id: "preview", simulation: { status: "success" } }; },
  };
  return { service: new NearNameRegistration(chain), calls };
}

test("registration uses NEAR-derived owner and binds the exact Base call to the standard preview", async () => {
  const { service, calls } = setup();
  const result = await service.prepare("alice", { name: "Alice.base.eth", years: 2, set_primary: false });
  assert.equal(result.registration.owner, owner);
  assert.equal(result.registration.price_wei, "123");
  assert.equal((result as Record<string, unknown>).operation_id, "preview");
  assert.equal(calls.length, 1);
  const { input, user } = calls[0];
  assert.equal(user, "alice");
  assert.equal(input.network, "base");
  assert.equal(input.to, "0xa7d2607c6BD39Ae9521e514026CBB078405Ab322");
  assert.equal(input.value_wei, "123");
  const request: any = decodeFunctionData({ abi, data: input.data }).args![0];
  assert.equal(request.owner, owner);
  assert.equal(request.name, "alice");
  assert.equal(request.reverseRecord, false);
  assert.equal(request.duration, 63072000n);
});

test("taken names and unsupported ENS names fail without preparing a transaction", async () => {
  const taken = setup(false);
  await assert.rejects(taken.service.prepare("alice", { name: "alice.base.eth", years: 1 }), (e: unknown) => e instanceof NearPublicError && /already registered/.test(e.message));
  assert.equal(taken.calls.length, 0);
  const eth = setup();
  await assert.rejects(eth.service.prepare("alice", { name: "alice.eth", years: 1 }), (e: unknown) => e instanceof NearPublicError && /not supported/.test(e.message));
  assert.equal(eth.calls.length, 0);
});
