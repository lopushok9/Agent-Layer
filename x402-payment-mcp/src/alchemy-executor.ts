import { http, pad, parseAbi, type Address, type Hex, type PublicClient } from "viem";
import { toAccount } from "viem/accounts";
import { createBundlerClient, toCoinbaseSmartAccount, entryPoint06Address, type UserOperation } from "viem/account-abstraction";
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
export async function sendAlchemyOperation(rpc: PublicClient, url: string, cdp: EvmSmartAccount, network: WalletNetwork, calls: NormalizedCall[], persist: (hash: Hex, p: PreparedOperation) => Promise<void>, nonceKey = 0n) {
  const account = await coinbaseAccount(rpc, cdp, network);
  const bundler = alchemyBundler(rpc, url);
  if (!(await bundler.getSupportedEntryPoints()).some(a => a.toLowerCase() === entryPoint06Address.toLowerCase())) throw new Error("Bundler does not support this EntryPoint");
  const blockNumber = await rpc.getBlockNumber();
  const nonce = await rpc.readContract({ address: entryPoint06Address, abi: nonceAbi, functionName: "getNonce", args: [account.address, nonceKey], blockNumber });
  const fees = await rpc.estimateFeesPerGas();
  const prepared = await bundler.prepareUserOperation({ account, nonce, calls: calls.map(c => ({ ...c, value: BigInt(c.value) })), ...fees });
  // Keep only ERC-4337 v0.6 fields; never persist account objects/functions.
  const operation: UserOperation<"0.6"> = { sender: account.address, nonce: prepared.nonce, initCode: prepared.initCode ?? "0x", callData: prepared.callData, callGasLimit: prepared.callGasLimit, verificationGasLimit: prepared.verificationGasLimit, preVerificationGas: prepared.preVerificationGas, maxFeePerGas: prepared.maxFeePerGas, maxPriorityFeePerGas: prepared.maxPriorityFeePerGas, paymasterAndData: prepared.paymasterAndData ?? "0x", signature: "0x" };
  if (operation.nonce !== nonce || operation.callData !== await account.encodeCalls(calls.map(c => ({ ...c, value: BigInt(c.value) }))) || operation.paymasterAndData !== "0x") throw new Error("Prepared UserOperation changed the requested calls or nonce");
  const p: PreparedOperation = { chainId: chainIds[network], entryPoint: entryPoint06Address, blockNumber: blockNumber.toString(), operation };
  return sendPreparedOperation(p, persist, op => account.signUserOperation(op), op => bundler.sendUserOperation({ ...op, entryPointAddress: p.entryPoint }));
}
