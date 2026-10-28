import { parseAbiItem, parseEventLogs, type Address, type Hex, type PublicClient, type TransactionReceipt } from "viem";
import { entryPoint06Address } from "viem/account-abstraction";
import { nonceAbi } from "./alchemy-executor.js";
const event = parseAbiItem("event UserOperationEvent(bytes32 indexed userOpHash,address indexed sender,address indexed paymaster,uint256 nonce,bool success,uint256 actualGasCost,uint256 actualGasUsed)");
export function matchedOperation(receipt: TransactionReceipt, hash: Hex, sender: Address, nonce?: bigint) {
  return parseEventLogs({ abi: [event], logs: receipt.logs.filter(l => l.address.toLowerCase() === entryPoint06Address.toLowerCase()) }).find(e => e.args.userOpHash.toLowerCase() === hash.toLowerCase() && e.args.sender.toLowerCase() === sender.toLowerCase() && (nonce === undefined || e.args.nonce === nonce));
}

export type OperationLocation =
  | { state: "pending" }
  | { state: "included"; block: bigint; receipt: TransactionReceipt }
  | { state: "invalidated"; block: bigint }
  | { state: "superseded"; block: bigint };

// Same approach as Erigon/Otterscan ots_getTransactionBySenderAndNonce: binary
// search the block where the sender's nonce moved past ours, then read logs of
// that single block. EntryPoint.getNonce(sender, key) returns key << 64 | seq,
// so it compares directly with the full 4337 nonce. Needs archive state reads;
// O(log n) calls, with no block-window limit and no truncated-scan ambiguity.
export async function locateOperation(rpc: Pick<PublicClient, "readContract" | "getLogs" | "getTransactionReceipt">, hash: Hex, sender: Address, nonce: bigint, fromBlock: bigint, toBlock: bigint): Promise<OperationLocation> {
  if (fromBlock < 0n || fromBlock > toBlock) throw new Error("Operation reconciliation block range is invalid");
  const key = nonce >> 64n;
  const consumed = async (blockNumber: bigint) => await rpc.readContract({ address: entryPoint06Address, abi: nonceAbi, functionName: "getNonce", args: [sender, key], blockNumber }) > nonce;
  if (!await consumed(toBlock)) return { state: "pending" };
  // The proof block is where the nonce was read as unused; anything else means
  // the stored proof and chain disagree, so nothing can be concluded.
  if (await consumed(fromBlock)) throw new Error("Operation nonce was consumed before its preparation block");
  let lo = fromBlock, hi = toBlock;
  while (hi - lo > 1n) {
    const mid = (lo + hi) / 2n;
    if (await consumed(mid)) hi = mid; else lo = mid;
  }
  const logs = await rpc.getLogs({ address: entryPoint06Address, event, args: { sender }, fromBlock: hi, toBlock: hi, strict: true });
  const log = logs.find(l => !l.removed && l.args.nonce === nonce);
  // The nonce advanced in this block without a UserOperationEvent for it:
  // EntryPoint.incrementNonce from a cancellation consumed it.
  if (!log) return { state: "invalidated", block: hi };
  if (log.args.userOpHash.toLowerCase() !== hash.toLowerCase() || !log.transactionHash) return { state: "superseded", block: hi };
  return { state: "included", block: hi, receipt: await rpc.getTransactionReceipt({ hash: log.transactionHash }) };
}
