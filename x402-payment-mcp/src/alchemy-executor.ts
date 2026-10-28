import { http, pad, parseAbi, type Address, type Hex, type PublicClient } from "viem";
import { toAccount } from "viem/accounts";
import { createBundlerClient, toCoinbaseSmartAccount, entryPoint06Abi, entryPoint06Address, type UserOperation } from "viem/account-abstraction";
import type { EvmSmartAccount } from "@coinbase/cdp-sdk";
import { chainIds, type NormalizedCall, type WalletNetwork } from "./transaction-builder.js";
import { operationHash, type PreparedOperation } from "./user-operation.js";

export const nonceAbi = parseAbi(["function getNonce(address sender,uint192 key) view returns(uint256)", "function incrementNonce(uint192 key)"]);
const ownerAbi = parseAbi(["function ownerAtIndex(uint256 index) view returns(bytes)", "function entryPoint() view returns(address)"]);
export function alchemyBundler(rpc: PublicClient, url: string) {
  return createBundlerClient({ client: rpc, transport: http(url, { timeout: 15_000, retryCount: 0 }) });
}
export async function coinbaseAccount(rpc: PublicClient, cdp: EvmSmartAccount, network: WalletNetwork) {
  if (await rpc.getChainId() !== chainIds[network]) throw new Error("RPC chain ID mismatch");
  const owner = cdp.owners[0];
  if (!owner || typeof owner === "string") throw new Error("CDP owner is unavailable");
  const signer = toAccount({ address: owner.address, sign: p => owner.sign(p), signMessage: p => owner.signMessage(p), signTypedData: p => owner.signTypedData(p), signTransaction: async () => { throw new Error("Owner EOA transaction signing is disabled"); } });
  // CDP uses factory v1.1 and deployment salt zero. Derive independently instead
  // of overriding address and accidentally deploying a different wallet.
  const account = await toCoinbaseSmartAccount({ client: rpc, owners: [signer], version: "1.1", nonce: 0n });
  if (account.address.toLowerCase() !== cdp.address.toLowerCase()) throw new Error("CDP smart account factory derivation mismatch");
  const code = await rpc.getCode({ address: account.address });
  if (code && code !== "0x") {
    const [storedOwner, entryPoint] = await Promise.all([
      rpc.readContract({ address: account.address, abi: ownerAbi, functionName: "ownerAtIndex", args: [0n] }),
      rpc.readContract({ address: account.address, abi: ownerAbi, functionName: "entryPoint" }),
    ]);
    if (storedOwner.toLowerCase() !== pad(owner.address).toLowerCase() || entryPoint.toLowerCase() !== entryPoint06Address.toLowerCase()) throw new Error("Smart account owner or EntryPoint mismatch");
  }
  return account;
}
export async function sendPreparedOperation(
  p: PreparedOperation,
  persist: (hash: Hex, p: PreparedOperation) => Promise<void>,
  sign: (op: UserOperation<"0.6">) => Promise<Hex>,
  broadcast: (op: UserOperation<"0.6">) => Promise<Hex>,
) {
  // No owner signature is stored or logged. Both signature and submission may
  // time out: the durable pre-signing record must survive either failure.
  const hash = operationHash(p);
  await persist(hash, p);
  const signature = await sign(p.operation);
  const returned = await broadcast({ ...p.operation, signature });
  if (returned.toLowerCase() !== hash.toLowerCase()) throw new Error("Bundler returned a different UserOperation hash");
  return { userOpHash: hash };
}
export type Fees = { maxFeePerGas: bigint; maxPriorityFeePerGas: bigint };
// replace: re-sign the same nonce with higher fees. Only used for cancellations,
// whose versions all perform the identical incrementNonce, so whichever one the
// EntryPoint includes has the same effect and at most one can be included.
export type SendOptions = { nonceKey?: bigint; maxPrefundWei?: bigint; replace?: { nonce: bigint; minFees: Fees } };
async function prepareAlchemyOperation(rpc: PublicClient, url: string, cdp: EvmSmartAccount, network: WalletNetwork, calls: NormalizedCall[], options: SendOptions) {
  const nonceKey = options.nonceKey ?? 0n;
  const account = await coinbaseAccount(rpc, cdp, network);
  const bundler = alchemyBundler(rpc, url);
  if (!(await bundler.getSupportedEntryPoints()).some(a => a.toLowerCase() === entryPoint06Address.toLowerCase())) throw new Error("Bundler does not support this EntryPoint");
  const blockNumber = await rpc.getBlockNumber();
  const nonce = await rpc.readContract({ address: entryPoint06Address, abi: nonceAbi, functionName: "getNonce", args: [account.address, nonceKey], blockNumber });
  if (options.replace && options.replace.nonce !== nonce) throw new Error("replaced operation nonce is no longer pending; reconcile transaction_status");
  // Alchemy's bundler has a service-tip requirement distinct from execution
  // RPC fee estimates. Follow its documented 50% base / 25% priority buffers.
  const [block, tip] = await Promise.all([
    rpc.getBlock({ blockTag: "latest" }),
    bundler.request<{ Parameters: []; ReturnType: Hex }>({ method: "rundler_maxPriorityFeePerGas", params: [] }),
  ]);
  if (block.baseFeePerGas === null || !/^0x[0-9a-f]+$/i.test(tip)) throw new Error("Bundler fee estimate unavailable");
  const fees = atLeast(alchemyFees(block.baseFeePerGas, BigInt(tip)), options.replace?.minFees);
  const prepared = await bundler.prepareUserOperation({ account, nonce, calls: calls.map(c => ({ ...c, value: BigInt(c.value) })), ...fees });
  // Keep only ERC-4337 v0.6 fields; never persist account objects/functions.
  const operation: UserOperation<"0.6"> = { sender: account.address, nonce: prepared.nonce, initCode: prepared.initCode ?? "0x", callData: prepared.callData, callGasLimit: prepared.callGasLimit, verificationGasLimit: prepared.verificationGasLimit, preVerificationGas: prepared.preVerificationGas, maxFeePerGas: prepared.maxFeePerGas, maxPriorityFeePerGas: prepared.maxPriorityFeePerGas, paymasterAndData: prepared.paymasterAndData ?? "0x", signature: "0x" };
  if (operation.nonce !== nonce || operation.callData !== await account.encodeCalls(calls.map(c => ({ ...c, value: BigInt(c.value) }))) || operation.paymasterAndData !== "0x") throw new Error("Prepared UserOperation changed the requested calls or nonce");
  const p: PreparedOperation = { chainId: chainIds[network], entryPoint: entryPoint06Address, blockNumber: blockNumber.toString(), operation };
  return { p, account, bundler };
}
// EntryPoint v0.6 _getRequiredPrefund: the account must be able to escrow this
// much before validation succeeds. A paymaster triples verification gas (postOp).
export function requiredPrefund(op: UserOperation<"0.6">) {
  const mul = op.paymasterAndData !== "0x" ? 3n : 1n;
  return (op.callGasLimit + op.verificationGasLimit * mul + op.preVerificationGas) * op.maxFeePerGas;
}
// Mirrors EntryPoint _validateAccountPrepayment: an existing deposit covers part
// of the prefund; CoinbaseSmartWallet.payPrefund sends the rest from its balance
// before the batch runs, so value transfers come out of what remains.
export async function assertFunded(rpc: Pick<PublicClient, "getBalance" | "readContract">, op: UserOperation<"0.6">, calls: NormalizedCall[], maxPrefundWei?: bigint) {
  const prefund = requiredPrefund(op);
  if (maxPrefundWei !== undefined && prefund > maxPrefundWei) throw new Error("network fee exceeds the approved maximum; prepare and confirm a new operation");
  const [balance, deposit] = await Promise.all([
    rpc.getBalance({ address: op.sender }),
    rpc.readContract({ address: entryPoint06Address, abi: entryPoint06Abi, functionName: "balanceOf", args: [op.sender] }),
  ]);
  const missing = deposit >= prefund ? 0n : prefund - deposit;
  if (balance < missing + calls.reduce((n, c) => n + BigInt(c.value), 0n)) throw new Error("insufficient ETH for value and network fee; nothing was signed");
  return prefund;
}
export async function estimateAlchemyOperation(rpc: PublicClient, url: string, cdp: EvmSmartAccount, network: WalletNetwork, calls: NormalizedCall[], options: SendOptions = {}) {
  const { p } = await prepareAlchemyOperation(rpc, url, cdp, network, calls, options);
  return requiredPrefund(p.operation);
}
export async function sendAlchemyOperation(rpc: PublicClient, url: string, cdp: EvmSmartAccount, network: WalletNetwork, calls: NormalizedCall[], persist: (hash: Hex, p: PreparedOperation) => Promise<void>, options: SendOptions = {}) {
  const { p, account, bundler } = await prepareAlchemyOperation(rpc, url, cdp, network, calls, options);
  // A bundler rejection after signing (AA21 prefund) leaves a valid signature
  // that becomes executable once funded; refuse before anything is signed.
  await assertFunded(rpc, p.operation, calls, options.maxPrefundWei);
  return sendPreparedOperation(p, persist, op => account.signUserOperation(op), op => bundler.sendUserOperation({ ...op, entryPointAddress: p.entryPoint }));
}

// The ERC-4337 mempool accepts a same-sender, same-nonce replacement only when
// both fee fields rise by a minimum percentage: rundler's
// min_replacement_fee_increase_percentage defaults to 10. Add 1 wei so integer
// rounding can never leave the bump at exactly the threshold.
export function replacementFees(previous: Fees): Fees {
  if (previous.maxFeePerGas < 0n || previous.maxPriorityFeePerGas < 0n) throw new Error("Invalid bundler fees");
  return { maxFeePerGas: (previous.maxFeePerGas * 110n + 99n) / 100n + 1n, maxPriorityFeePerGas: (previous.maxPriorityFeePerGas * 110n + 99n) / 100n + 1n };
}
function atLeast(fees: Fees, minimum?: Fees): Fees {
  if (!minimum) return fees;
  const maxPriorityFeePerGas = fees.maxPriorityFeePerGas > minimum.maxPriorityFeePerGas ? fees.maxPriorityFeePerGas : minimum.maxPriorityFeePerGas;
  const maxFeePerGas = fees.maxFeePerGas > minimum.maxFeePerGas ? fees.maxFeePerGas : minimum.maxFeePerGas;
  return { maxPriorityFeePerGas, maxFeePerGas: maxFeePerGas > maxPriorityFeePerGas ? maxFeePerGas : maxPriorityFeePerGas };
}
export function alchemyFees(baseFee: bigint, priorityFee: bigint) {
  if (baseFee < 0n || priorityFee < 0n) throw new Error("Invalid bundler fees");
  const maxPriorityFeePerGas = (priorityFee * 125n + 99n) / 100n;
  return { maxPriorityFeePerGas, maxFeePerGas: (baseFee * 150n + 99n) / 100n + maxPriorityFeePerGas };
}
