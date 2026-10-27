import { parseAbi, parseEventLogs, parseAbiItem, type Address, type Hex, type PublicClient, type TransactionReceipt } from "viem";
import { entryPoint06Address } from "viem/account-abstraction";
const event = parseAbiItem("event UserOperationEvent(bytes32 indexed userOpHash,address indexed sender,address indexed paymaster,uint256 nonce,bool success,uint256 actualGasCost,uint256 actualGasUsed)");
export function matchedOperation(receipt: TransactionReceipt, hash: Hex, sender: Address, nonce?: bigint) {
  return parseEventLogs({ abi: [event], logs: receipt.logs.filter(l => l.address.toLowerCase() === entryPoint06Address.toLowerCase()) }).find(e => e.args.userOpHash.toLowerCase() === hash.toLowerCase() && e.args.sender.toLowerCase() === sender.toLowerCase() && (nonce === undefined || e.args.nonce === nonce));
}
export async function findOperationReceipt(rpc: PublicClient, hash: Hex, sender: Address, fromBlock: bigint, toBlock: bigint) {
  // Exhaustively cover the interval or fail closed; never interpret a truncated
  // search as proof of absence. No signatures/calldata are fetched or logged.
  if (fromBlock < 0n || fromBlock > toBlock || toBlock - fromBlock > 100_000n) throw new Error("Operation reconciliation requires an extended block search");
  for (let start = fromBlock; start <= toBlock; start += 2000n) {
    const end = start + 1999n < toBlock ? start + 1999n : toBlock;
    const logs = await rpc.getLogs({ address: entryPoint06Address, event, args: { userOpHash: hash, sender }, fromBlock: start, toBlock: end, strict: true });
    const log = logs.find(l => !l.removed && l.transactionHash);
    if (log?.transactionHash) return rpc.getTransactionReceipt({ hash: log.transactionHash });
  }
  return null;
}
