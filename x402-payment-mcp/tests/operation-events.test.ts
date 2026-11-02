import test from "node:test";
import assert from "node:assert/strict";
import { encodeAbiParameters, encodeEventTopics, parseAbi } from "viem";
import { entryPoint06Address } from "viem/account-abstraction";
import { operationLogs } from "../src/operation-receipt.js";
import { nftChanges } from "../src/nft-changes.js";
import { TransactionService } from "../src/transactions.js";

const me = "0x1111111111111111111111111111111111111111", other = "0x2222222222222222222222222222222222222222", nft = "0x3333333333333333333333333333333333333333";
const hash = `0x${"ab".repeat(32)}` as const, previous = `0x${"cd".repeat(32)}` as const;
const events = parseAbi(["event BeforeExecution()", "event UserOperationEvent(bytes32 indexed userOpHash,address indexed sender,address indexed paymaster,uint256 nonce,bool success,uint256 actualGasCost,uint256 actualGasUsed)", "event Transfer(address indexed from,address indexed to,uint256 indexed tokenId)"]);
const boundary = { address: entryPoint06Address, topics: encodeEventTopics({ abi: events, eventName: "BeforeExecution" }), data: "0x" };
const operation = (h: typeof hash, sender: `0x${string}`) => ({ address: entryPoint06Address, topics: encodeEventTopics({ abi: events, eventName: "UserOperationEvent", args: { userOpHash: h, sender, paymaster: other } }), data: encodeAbiParameters([{type:"uint256"},{type:"bool"},{type:"uint256"},{type:"uint256"}], [0n,true,42n,20n]) });
const transfer = (id: bigint) => ({ address: nft, topics: encodeEventTopics({ abi: events, eventName: "Transfer", args: { from: other, to: me, tokenId: id } }), data: "0x" });

test("actual logs and NFT IDs exclude other operations in the same bundler transaction", () => {
  const receipt = { logs: [boundary, transfer(1n), operation(previous, other), transfer(2n), operation(hash, me), transfer(3n)] } as any;
  const scoped = operationLogs(receipt, hash, me)!;
  assert.deepEqual(nftChanges(scoped.logs, me).map(x => x.token_id), ["2"]);
  assert.equal(scoped.event.args.actualGasCost, 42n);
  assert.equal(operationLogs({ logs: [transfer(1n), operation(hash, me)] } as any, hash, me), null, "unknown boundary is not the full receipt");
  assert.equal(operationLogs(receipt, hash, other), null, "sender is bound");
});

test("confirmed status exposes actual NFT id, and event access is scoped to the operation owner", async () => {
  const receipt = { status: "success", logs: [boundary, transfer(9n), operation(hash, me)] };
  const p = { id: "id", userId: "alice", network: "base", address: me, status: "confirmed", userOpHash: hash, transactionHash: `0x${"12".repeat(32)}`, calls: [], descriptions: [], simulation: {}, fingerprint: "f", expiresAt: new Date(), error: null };
  const store = { operation: async (user: string) => user === "alice" ? p : null, interruptedOperations: async () => [] };
  let locked = false;
  const rpc = { getChainId: async () => { assert.equal(locked, false); return 8453; }, getTransactionReceipt: async () => { assert.equal(locked, false); return receipt; } };
  const service = new TransactionService({ rpc: () => rpc } as any, store as any, { withPaymentLock: async (_u, f) => { locked=true; try { return await f(); } finally { locked=false; } } }, 60);
  const status: any = await service.status("alice", "id");
  assert.equal(status.actual.nft_changes[0].token_id, "9"); assert.equal(status.actual.network_fee_wei, "42");
  const result: any = await service.events("alice", { operation_id: "id", abi: [events[2]] });
  assert.equal(result.events[0].decoded.eventName, "Transfer");
  assert.equal(result.events[0].abi_source, "caller_supplied_unverified");
  await assert.rejects(service.events("bob", { operation_id: "id" }), /not found/);
});
