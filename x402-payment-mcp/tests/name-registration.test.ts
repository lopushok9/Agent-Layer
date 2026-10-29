import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, namehash, parseAbi } from "viem";
import { NameRegistration } from "../src/name-registration.js";

const account = "0xD09d6F783A9840E5Ca35E134912765dc11C895A1";
const abi = parseAbi([
  "struct RegisterRequest { string name; address owner; uint256 duration; address resolver; bytes[] data; bool reverseRecord; uint256[] coinTypes; uint256 signatureExpiry; bytes signature; }",
  "function register(RegisterRequest request) payable",
  "function renew(string name, uint256 duration) payable",
  "function setAddr(bytes32 node, address a)",
  "function setAddr(bytes32 node, uint256 coinType, bytes a)",
]);

function harness({ available = true, valid = true } = {}) {
  const prepared: any[] = [];
  const rpc = { readContract: async ({ functionName }: any) => ({ valid, available, registerPrice: 2_000_000_000_000_000n, rentPrice: { base: 1_000_000_000_000_000n, premium: 0n } } as Record<string, unknown>)[functionName] };
  const reg = new NameRegistration({ account: async () => ({ address: account }), rpc: () => rpc as any }, async (_u, input) => { prepared.push(input); return { operation_id: "op" }; });
  return { reg, prepared };
}

test("a Basename registers in one call paying registerPrice, with address records and the primary name", async () => {
  const { reg, prepared } = harness();
  const r: any = await reg.register("alice", { name: "Alice.base.eth", years: 2 });
  assert.deepEqual([r.operation_id, r.registration.name, r.registration.price_wei, r.registration.primary_name], ["op", "alice.base.eth", "2000000000000000", true]);
  assert.equal(prepared[0].network, "base");
  const call = prepared[0].calls[0];
  assert.deepEqual([call.to, call.value], ["0xa7d2607c6BD39Ae9521e514026CBB078405Ab322", "2000000000000000"]);
  const req: any = decodeFunctionData({ abi, data: call.data }).args![0];
  assert.deepEqual([req.name, req.owner, req.duration, req.resolver, req.reverseRecord, req.signature], ["alice", account, 2n * 365n * 86_400n, "0x426fA03fB86E510d0Dd9F70335Cf102a98b10875", true, "0x"]);
  const records = req.data.map((d: any) => decodeFunctionData({ abi, data: d }).args);
  assert.deepEqual(records.map((a: any) => a[0]), [namehash("alice.base.eth"), namehash("alice.base.eth")]);
  assert.deepEqual([records[0][1], records[1][1]], [account, 2_147_492_101n], "default address, then the Base chain record (ENSIP-11)");
  const noPrimary: any = decodeFunctionData({ abi, data: (await (async () => { const h = harness(); await h.reg.register("alice", { name: "alice.base.eth", years: 1, set_primary: false }); return h.prepared[0].calls[0].data; })()) }).args![0];
  assert.equal(noPrimary.reverseRecord, false);
});

test("ENS .eth names, nested or look-alike names, invalid and taken names are refused", async () => {
  await assert.rejects(harness().reg.register("alice", { name: "alice.eth", years: 1 }), /ENS \.eth registration and renewal are not supported/);
  await assert.rejects(harness().reg.register("alice", { name: "a.b.base.eth", years: 1 }), /one label followed by \.base\.eth/);
  await assert.rejects(harness().reg.register("alice", { name: "аpple.base.eth", years: 1 }), /not a valid ENS name/);
  await assert.rejects(harness({ valid: false }).reg.register("alice", { name: "ab.base.eth", years: 1 }), /not valid for registration/);
  await assert.rejects(harness({ available: false }).reg.register("alice", { name: "alice.base.eth", years: 1 }), /already registered/);
});

test("renewal pays the base rent price and needs a registered name", async () => {
  const h = harness({ available: false });
  const r: any = await h.reg.renew("alice", { name: "alice.base.eth", years: 3 });
  assert.equal(r.renewal.price_wei, "1000000000000000");
  assert.equal(h.prepared[0].calls[0].value, "1000000000000000");
  assert.deepEqual(decodeFunctionData({ abi, data: h.prepared[0].calls[0].data }).args, ["alice", 3n * 365n * 86_400n]);
  await assert.rejects(harness().reg.renew("alice", { name: "free.base.eth", years: 1 }), /not registered/);
  await assert.rejects(harness({ available: false }).reg.renew("alice", { name: "vitalik.eth", years: 1 }), /not supported/);
});
