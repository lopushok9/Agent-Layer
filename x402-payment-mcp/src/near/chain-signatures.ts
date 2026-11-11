import { z } from "zod";
import { baseDecode } from "@near-js/utils";
import { publicKeyToAddress } from "viem/accounts";
import { encodeFunctionData, formatEther, keccak256, recoverAddress, serializeTransaction, isAddress, getAddress, type Abi, type Address, type Hex, type PublicClient, type TransactionSerializableEIP1559 } from "viem";
import type { NearAccountService } from "./account.js";
import { NearOperations, NearPublicError } from "./operations.js";
import type { NearStore } from "./store.js";
import { GAS_PER_TGAS } from "./units.js";

// NEAR Chain Signatures: the user's NEAR account asks the MPC contract to sign
// an EVM transaction hash for a key derived from (account, path). The derived
// address is a separate EOA on every EVM chain; it holds its own funds and pays
// its own gas. The service never asks the MPC network to sign anything other
// than the hash of the exact EVM transaction shown in the preview.
export const EVM_CHAINS = { base: 8453, ethereum: 1 } as const;
export type EvmNetwork = keyof typeof EVM_CHAINS;
export const DERIVATION_PATH = "agentlayer-evm-1";
// A direct sign() burns ~7.6 TGas on mainnet (4.2 sign + 3.4 resume callback); the
// contract requires >= 15 TGas. Prepaid gas is bought at 0.001 NEAR/TGas up front.
export const MPC_SIGN_GAS = 50n * GAS_PER_TGAS;
const SECP256K1_N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;

export const evmNetworkInput = z.enum(["base", "ethereum"]);
export const evmCallInput = z.strictObject({
  network: evmNetworkInput,
  to: z.string().refine(v => isAddress(v, { strict: false }), "to must be an EVM address"),
  value_wei: z.string().regex(/^\d{1,78}$/).default("0").describe("Native ETH in wei"),
  data: z.string().regex(/^0x([0-9a-fA-F]{2})*$/).max(2 + 2 * 24_576).optional().describe("Raw calldata; omit for a plain ETH transfer"),
  abi: z.array(z.unknown()).min(1).max(50).optional().describe("ABI with function_name and args to encode calldata"),
  function_name: z.string().min(1).max(200).optional(),
  args: z.array(z.unknown()).max(30).optional(),
}).refine(v => !(v.data && v.abi), "provide data or abi+function_name, not both").refine(v => !v.abi === !v.function_name, "abi and function_name go together");
export type EvmCallInput = z.infer<typeof evmCallInput>;

export type EvmPlan = { network: EvmNetwork; chainId: number; from: Address; path: string; tx: { to: Address; value: string; data: Hex; nonce: number; gas: string; maxFeePerGas: string; maxPriorityFeePerGas: string }; payload: Hex };

export class ChainSignatures {
  private derived = new Map<string, Address>();
  constructor(private accounts: NearAccountService, private operations: NearOperations, private store: NearStore, private evm: (network: EvmNetwork) => PublicClient) {}

  // Authoritative derivation from the MPC contract itself (view call), so the
  // address always matches the key the network will sign with.
  async address(accountId: string, path = DERIVATION_PATH): Promise<Address> {
    const cacheKey = `${accountId}:${path}`;
    const hit = this.derived.get(cacheKey);
    if (hit) return hit;
    const r = await this.accounts.rpc.callFunction(this.accounts.config.mpcContract, "derived_public_key", { path, predecessor: accountId, domain_id: 0 });
    const address = secp256k1KeyToAddress(r.result);
    this.derived.set(cacheKey, address);
    return address;
  }

  async status(userId: string) {
    const account = await this.accounts.account(userId);
    const address = await this.address(account.accountId);
    const balances = await Promise.all((Object.keys(EVM_CHAINS) as EvmNetwork[]).map(async network => {
      try { const wei = await this.client(network).getBalance({ address }); return { network, chain_id: EVM_CHAINS[network], balance_wei: wei.toString(), balance_eth: formatEther(wei) }; }
      catch { return { network, chain_id: EVM_CHAINS[network], error: "balance unavailable" }; }
    }));
    return {
      near_account_id: account.accountId, mpc_contract: this.accounts.config.mpcContract, derivation_path: DERIVATION_PATH,
      evm_address: address, balances,
      receive: `Fund ${address} with ETH on Base or Ethereum for gas and value. It is controlled by NEAR Chain Signatures for your NEAR account, separate from your AgentLayer smart wallet.`,
      requirements: "Each EVM transaction needs ETH on the derived address for gas and about 0.01 NEAR (prepaid MPC gas, mostly refunded) on the NEAR account.",
    };
  }

  private client(network: EvmNetwork): PublicClient {
    return this.evm(network);
  }

  // Builds the exact EIP-1559 transaction, estimates it from the derived
  // address (a revert stops here), and previews the NEAR sign() call over its hash.
  async prepare(userId: string, input: EvmCallInput) {
    const account = await this.accounts.account(userId);
    const from = await this.address(account.accountId);
    const network = input.network;
    const chainId = EVM_CHAINS[network];
    const rpc = this.client(network);
    if (await rpc.getChainId() !== chainId) throw new NearPublicError("evm RPC chain ID mismatch");
    const to = getAddress(input.to);
    const data: Hex = input.abi ? encodeFunctionData({ abi: input.abi as Abi, functionName: input.function_name!, args: input.args ?? [] }) : (input.data as Hex | undefined) ?? "0x";
    const value = BigInt(input.value_wei);
    const [nonce, fees, balance] = await Promise.all([rpc.getTransactionCount({ address: from, blockTag: "pending" }), rpc.estimateFeesPerGas(), rpc.getBalance({ address: from })]);
    let gas: bigint;
    try { gas = await rpc.estimateGas({ account: from, to, value, data }); }
    catch { throw new NearPublicError("evm call reverts or cannot be estimated from the derived address; nothing was signed"); }
    gas = gas * 12n / 10n;
    // Head-room for base-fee growth while the user reads the preview.
    const maxPriorityFeePerGas = fees.maxPriorityFeePerGas ?? 0n;
    const maxFeePerGas = (fees.maxFeePerGas ?? 0n) * 2n + maxPriorityFeePerGas;
    const maxGasCost = gas * maxFeePerGas;
    if (balance < value + maxGasCost) throw new NearPublicError(`insufficient ETH on derived address ${from}: needs up to ${formatEther(value + maxGasCost)} ETH on ${network}, has ${formatEther(balance)}; nothing was signed`);
    const tx: TransactionSerializableEIP1559 = { type: "eip1559", chainId, nonce, to, value, data, gas, maxFeePerGas, maxPriorityFeePerGas };
    const payload = keccak256(serializeTransaction(tx));
    if (BigInt(payload) === 0n || BigInt(payload) >= SECP256K1_N) throw new NearPublicError("evm transaction hash is not a valid signing payload; prepare again");
    const plan: EvmPlan = { network, chainId, from, path: DERIVATION_PATH, tx: { to, value: value.toString(), data, nonce, gas: gas.toString(), maxFeePerGas: maxFeePerGas.toString(), maxPriorityFeePerGas: maxPriorityFeePerGas.toString() }, payload };
    const signArgs = { request: { path: DERIVATION_PATH, payload_v2: { Ecdsa: payload.slice(2) }, domain_id: 0 } };
    const nearTx = { receiverId: this.accounts.config.mpcContract, actions: [{ type: "function_call" as const, method: "sign", args_base64: Buffer.from(JSON.stringify(signArgs)).toString("base64"), gas: MPC_SIGN_GAS.toString(), deposit: "1" }] };
    return this.operations.preview(userId, nearTx, "chain_signature", { evm: plan }, {
      evm_transaction: { network, chain_id: chainId, from, to, value_wei: value.toString(), value_eth: formatEther(value), data, nonce, gas_limit: gas.toString(), max_fee_per_gas: maxFeePerGas.toString(), max_evm_network_fee_wei: maxGasCost.toString(), max_evm_network_fee_eth: formatEther(maxGasCost), signing_payload: payload },
      limitations: ["Estimated, not simulated with state overrides; on-chain execution can still revert.", "The EVM fee is paid in ETH by the derived address; the NEAR fee by the NEAR account.", "Signing is asynchronous on the MPC network; the EVM transaction is broadcast only after its signature verifies for the derived address."],
    });
  }

  async execute(userId: string, id: string, purpose: string) {
    // The nonce is fixed in the preview. If the derived address sent anything
    // since, the signed transaction could never be mined: refuse before paying for MPC.
    const op = await this.store.operation(userId, id);
    const evmPlan = op?.kind === "chain_signature" && op.status === "prepared" ? (op.plan as { evm?: EvmPlan } | null)?.evm : undefined;
    if (evmPlan) {
      const pending = await this.client(evmPlan.network).getTransactionCount({ address: evmPlan.from, blockTag: "pending" });
      if (pending !== evmPlan.tx.nonce) throw new NearPublicError(`the derived address nonce on ${evmPlan.network} is now ${pending}, but this preview was built for nonce ${evmPlan.tx.nonce} (another transaction was sent since); call evm_call_prepare again. Nothing was signed`);
    }
    const near = await this.operations.execute(userId, id, purpose, "chain_signature", "FINAL");
    if (near.status !== "confirmed") return { ...near, stage: "near_signature" };
    return this.complete(userId, id);
  }

  async operationStatus(userId: string, id: string) {
    const op = await this.store.operation(userId, id);
    if (!op || op.kind !== "chain_signature") return this.operations.status(userId, id);
    const result = op.result as { evm_tx_hash?: Hex; evm_receipt?: { status: string } } | null;
    const plan0 = (op.plan as { evm: EvmPlan }).evm;
    if (result?.evm_receipt?.status === "dropped") return this.dropped(id, op.txHash, plan0, result.evm_tx_hash!);
    if (op.status !== "confirmed" || !result?.evm_tx_hash) {
      const near = op.status === "confirmed" ? { status: "confirmed" } : await this.operations.status(userId, id);
      if (near.status !== "confirmed") return { ...near, stage: "near_signature" };
      return this.complete(userId, id);
    }
    const plan = (op.plan as { evm: EvmPlan }).evm;
    const lookup = await receiptLookup(this.client(plan.network), result.evm_tx_hash);
    const receipt = lookup.receipt;
    if (lookup.notFound && await this.nonceConsumed(plan)) return this.markDropped(userId, id, op.txHash, plan, result);
    if (!receipt) await this.rebroadcast(userId, id);
    const evm = receipt ? { status: receipt.status, block_number: receipt.blockNumber.toString(), gas_used: receipt.gasUsed.toString() } : { status: "pending" };
    await this.store.update(userId, id, { status: "confirmed", result: { ...result, evm_receipt: evm } });
    return { operation_id: id, stage: receipt ? "evm_final" : "evm_pending", near_transaction_hash: op.txHash, evm_network: plan.network, evm_tx_hash: result.evm_tx_hash, evm_explorer_url: evmExplorer(plan.network, result.evm_tx_hash), evm };
  }

  // Turns the MPC response into an EVM signature, proves it recovers to the
  // derived address for the stored payload, then broadcasts the stored tx.
  private async complete(userId: string, id: string) {
    const op = (await this.store.operation(userId, id))!;
    const plan = (op.plan as { evm: EvmPlan }).evm;
    const returned = (op.outcome as { return_value?: unknown } | null)?.return_value;
    const signature = parseMpcSignature(returned);
    const tx: TransactionSerializableEIP1559 = { type: "eip1559", chainId: plan.chainId, nonce: plan.tx.nonce, to: plan.tx.to, value: BigInt(plan.tx.value), data: plan.tx.data, gas: BigInt(plan.tx.gas), maxFeePerGas: BigInt(plan.tx.maxFeePerGas), maxPriorityFeePerGas: BigInt(plan.tx.maxPriorityFeePerGas) };
    if (keccak256(serializeTransaction(tx)) !== plan.payload) throw new Error("stored evm transaction does not match its signing payload");
    const recovered = await recoverAddress({ hash: plan.payload, signature });
    if (recovered.toLowerCase() !== plan.from.toLowerCase()) throw new NearPublicError("chain signature does not recover to the derived address; nothing was broadcast");
    const raw = serializeTransaction(tx, signature);
    const hash = keccak256(raw);
    await this.store.update(userId, id, { status: "confirmed", result: { evm_tx_hash: hash, evm_raw_tx: raw, evm_network: plan.network } });
    const rpc = this.client(plan.network);
    try { await rpc.sendRawTransaction({ serializedTransaction: raw }); }
    catch (e) {
      // Re-sending identical bytes is safe; "already known" means it is in the pool.
      const message = e instanceof Error ? e.message : "";
      if (/nonce too low|nonce has already been used/i.test(message)) {
        // Fine only if this exact transaction is the one that used the nonce.
        if ((await receiptLookup(rpc, hash)).notFound && await this.nonceConsumed(plan)) return this.markDropped(userId, id, op.txHash, plan, { evm_tx_hash: hash, evm_raw_tx: raw, evm_network: plan.network });
      } else if (!/already known|known transaction/i.test(message)) return { operation_id: id, stage: "evm_broadcast_unknown", evm_network: plan.network, evm_tx_hash: hash, message: "Signed EVM transaction could not be confirmed as broadcast; call near_operation_status to retry the same bytes. Do not prepare a replacement." };
    }
    return { operation_id: id, stage: "evm_submitted", near_transaction_hash: op.txHash, evm_network: plan.network, evm_from: plan.from, evm_tx_hash: hash, evm_explorer_url: evmExplorer(plan.network, hash), next: "Call near_operation_status for the EVM receipt." };
  }

  // True when a mined transaction already used this plan's nonce (so ours never can be).
  private async nonceConsumed(plan: EvmPlan) {
    const latest = await this.client(plan.network).getTransactionCount({ address: plan.from, blockTag: "latest" }).catch(() => null);
    return latest !== null && latest > plan.tx.nonce;
  }

  private async markDropped(userId: string, id: string, nearTx: string | null, plan: EvmPlan, result: Record<string, unknown>) {
    const hash = result.evm_tx_hash as Hex;
    await this.store.update(userId, id, { status: "failed", result: { ...result, evm_receipt: { status: "dropped" } }, error: "evm nonce was used by another transaction; the signed transaction can never be mined" });
    return this.dropped(id, nearTx, plan, hash);
  }

  private dropped(id: string, nearTx: string | null, plan: EvmPlan, hash: Hex) {
    return { operation_id: id, stage: "evm_dropped", near_transaction_hash: nearTx, evm_network: plan.network, evm_tx_hash: hash, evm: { status: "dropped" }, message: `Another transaction from ${plan.from} used nonce ${plan.tx.nonce}, so this signed transaction can never be mined and nothing moved on ${plan.network}. Only the NEAR signing fee was spent. Prepare a new call if still needed.` };
  }

  // Re-broadcast of the persisted signed bytes when the EVM step is uncertain.
  async rebroadcast(userId: string, id: string) {
    const op = await this.store.operation(userId, id);
    const result = op?.result as { evm_raw_tx?: Hex; evm_network?: EvmNetwork } | null;
    if (!op || !result?.evm_raw_tx || !result.evm_network) throw new NearPublicError("operation has no signed EVM transaction");
    await this.client(result.evm_network).sendRawTransaction({ serializedTransaction: result.evm_raw_tx }).catch(() => undefined);
  }
}

// Distinguishes "no receipt for this hash" from an RPC failure, so a transient
// error is never mistaken for a dropped transaction.
async function receiptLookup(rpc: PublicClient, hash: Hex) {
  try { return { receipt: await rpc.getTransactionReceipt({ hash }), notFound: false }; }
  catch (e) { return { receipt: null, notFound: (e as { name?: string })?.name === "TransactionReceiptNotFoundError" }; }
}

export function secp256k1KeyToAddress(value: unknown): Address {
  if (typeof value !== "string" || !value.startsWith("secp256k1:")) throw new Error("derived key is not secp256k1");
  const raw = baseDecode(value.slice("secp256k1:".length));
  if (raw.length !== 64) throw new Error("derived key must be a 64-byte uncompressed point");
  return publicKeyToAddress(`0x04${Buffer.from(raw).toString("hex")}`);
}

// MPC response: { scheme: "Secp256k1", big_r: { affine_point: "02|03"+x }, s: { scalar }, recovery_id }
export function parseMpcSignature(value: unknown): { r: Hex; s: Hex; yParity: number } {
  const v = value as { scheme?: string; big_r?: { affine_point?: string }; s?: { scalar?: string }; recovery_id?: number } | null;
  const point = v?.big_r?.affine_point, scalar = v?.s?.scalar;
  if (!v || (v.scheme !== undefined && v.scheme !== "Secp256k1") || typeof point !== "string" || !/^0[23][0-9a-fA-F]{64}$/.test(point) || typeof scalar !== "string" || !/^[0-9a-fA-F]{64}$/.test(scalar) || (v.recovery_id !== 0 && v.recovery_id !== 1)) throw new NearPublicError("chain signature response is missing or malformed");
  return { r: `0x${point.slice(2)}`, s: `0x${scalar}`, yParity: v.recovery_id };
}

export function evmExplorer(network: EvmNetwork, hash: Hex) {
  return `${network === "base" ? "https://basescan.org" : "https://etherscan.io"}/tx/${hash}`;
}

