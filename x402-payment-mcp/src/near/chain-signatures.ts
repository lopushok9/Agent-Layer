import { z } from "zod";
import { baseDecode } from "@near-js/utils";
import { publicKeyToAddress } from "viem/accounts";
import { hashAuthorization, recoverAuthorizationAddress } from "viem/utils";
import { encodeFunctionData, formatEther, getAddress, keccak256, zeroAddress, type TransactionSerializableEIP7702, recoverAddress, serializeTransaction, isAddress, type Address, type Hex, type PublicClient, type TransactionSerializableEIP1559 } from "viem";
import { assetChangeMismatch } from "../asset-changes.js";
import type { ContractMetadata } from "../contract-metadata.js";
import { nftChangeMismatch, nftChanges } from "../nft-changes.js";
import { revertMessage, SimulationReverted } from "../revert-reason.js";
import { annotateCalls, jsonValue, normalizeTransaction, withVerifiedAbis, type CallDescription, type NormalizedCall } from "../transaction-builder.js";
import { receivedFloors } from "../transactions.js";
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
  function_name: z.string().min(1).max(200).optional().describe("Function to call; encoded with the contract's verified ABI (Sourcify/Etherscan, behind proxies)"),
  args: z.array(z.unknown()).max(30).optional().describe("Arguments for function_name; token amounts as integer strings"),
  abi: z.array(z.unknown()).min(1).max(50).optional().describe("Only when the contract has no verified ABI: the ABI to encode function_name with (unverified)"),
  received_tolerance_bps: z.number().int().min(0).max(500).default(50).describe("How far below the simulated amount a received token may fall when re-simulated before signing, in bps. Outgoing amounts never tolerate any increase."),
}).refine(v => !(v.data && v.function_name), "provide data, or function_name (+ args), not both").refine(v => !v.abi || v.function_name, "abi requires function_name");
export type EvmCallInput = z.input<typeof evmCallInput>;
const batchCall = z.strictObject({
  to: z.string().refine(v => isAddress(v, { strict: false }), "to must be an EVM address"),
  value_wei: z.string().regex(/^\d{1,78}$/).default("0"),
  data: z.string().regex(/^0x([0-9a-fA-F]{2})*$/).max(2 + 2 * 24_576).optional(),
  function_name: z.string().min(1).max(200).optional(),
  args: z.array(z.unknown()).max(30).optional(),
  abi: z.array(z.unknown()).min(1).max(50).optional(),
}).refine(v => !(v.data && v.function_name), "provide data, or function_name (+ args), not both").refine(v => !v.abi || v.function_name, "abi requires function_name");
export const evmBatchInput = z.strictObject({
  network: evmNetworkInput,
  calls: z.array(batchCall).min(2).max(8).describe("Calls run in order, atomically, in one transaction (e.g. approve then supply)"),
  received_tolerance_bps: z.number().int().min(0).max(500).default(50),
});
type ParsedEvmCall = z.output<typeof evmCallInput>;

type SignedAuth = { address: Address; chainId: number; nonce: number; r: Hex; s: Hex; yParity: number };
export type EvmPlan = { network: EvmNetwork; chainId: number; from: Address; path: string; tx: { to: Address; value: string; data: Hex; nonce: number; gas: string; maxFeePerGas: string; maxPriorityFeePerGas: string; authorizationList?: SignedAuth[] }; payload: Hex; simulation?: EvmSimulation; calls?: NormalizedCall[]; authorization?: { address: Address; chainId: number; nonce: number } };
export type EvmSimulation = { status: "success"; block_number: string; asset_changes: unknown; nft_changes: unknown; asset_floors: Record<string, string>; received_tolerance_bps: number; gas_used_execution_only: string; max_amount_growth_bps?: number };
// A "max" argument (type(uint256).max, e.g. Aave withdraw/repay of the whole
// position) moves an amount that accrues every block. Before signing, the whole
// previewed trade may scale up by at most this much, never at a worse rate.
export const MAX_AMOUNT_GROWTH_BPS = 100;
// EIP-7702 delegate: eth-infinitism Simple7702Account (account-abstraction v0.8),
// stateless; execute/executeBatch only from the account itself or EntryPoint
// v0.8. Same address on Base and Ethereum (Sourcify-verified). The service only
// ever signs authorizations for this address or for revocation (zero address).
export const SIMPLE_7702_ACCOUNT = "0x4Cd241E8d1510e30b2076397afc7508Ae59C66c9" as Address;
export const MAX_BATCH_CALLS = 8;
// A self-sent type-4 transaction with one authorization: 21000 intrinsic +
// 25000 per authorization + the empty call into the delegate's fallback.
const DELEGATION_GAS = 100_000n;
export const evmDelegationInput = z.strictObject({ network: evmNetworkInput, action: z.enum(["delegate", "revoke"]).default("delegate").describe("delegate: point the derived address at Simple7702Account (enables atomic batches); revoke: clear the delegation") });

function txFromPlan(plan: EvmPlan): TransactionSerializableEIP1559 | TransactionSerializableEIP7702 {
  const base = { chainId: plan.chainId, nonce: plan.tx.nonce, to: plan.tx.to, value: BigInt(plan.tx.value), data: plan.tx.data, gas: BigInt(plan.tx.gas), maxFeePerGas: BigInt(plan.tx.maxFeePerGas), maxPriorityFeePerGas: BigInt(plan.tx.maxPriorityFeePerGas) };
  return plan.tx.authorizationList ? { ...base, type: "eip7702", authorizationList: plan.tx.authorizationList } : { ...base, type: "eip1559" };
}
const EXECUTE_BATCH_ABI = [{ type: "function", name: "executeBatch", stateMutability: "nonpayable", inputs: [{ name: "calls", type: "tuple[]", components: [{ name: "target", type: "address" }, { name: "value", type: "uint256" }, { name: "data", type: "bytes" }] }], outputs: [] }] as const;
const UINT256_MAX = ((1n << 256n) - 1n).toString();

export class ChainSignatures {
  private derived = new Map<string, Address>();
  constructor(private accounts: NearAccountService, private operations: NearOperations, private store: NearStore, private evm: (network: EvmNetwork) => PublicClient, private contracts: ContractMetadata | null = null) {}

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
      try {
        const [wei, delegate] = await Promise.all([this.client(network).getBalance({ address }), this.delegation(network, address).catch(() => "unknown" as const)]);
        const eip7702 = delegate === null ? "none" : delegate === "unknown" ? "unknown" : delegate.toLowerCase() === SIMPLE_7702_ACCOUNT.toLowerCase() ? "simple7702_account (atomic batches enabled)" : `other delegate ${delegate}`;
        return { network, chain_id: EVM_CHAINS[network], balance_wei: wei.toString(), balance_eth: formatEther(wei), eip7702_delegation: eip7702 };
      }
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
  rpcFor(network: EvmNetwork): PublicClient { return this.client(network); }

  // Builds the exact EIP-1559 transaction with the same builder as the smart
  // wallet (verified ABI, decoded call, ERC-7730 display), simulates it from the
  // derived address with asset tracing, and previews the NEAR sign() over its hash.
  async prepare(userId: string, input: EvmCallInput) {
    const parsed = evmCallInput.parse(input);
    const from = await this.fromAddress(userId);
    const built = await this.build(parsed.network, from, parsed);
    return this.previewCalls(userId, parsed.network, from, built.calls, [built.description], parsed.received_tolerance_bps);
  }

  // Several calls in one atomic transaction (EIP-7702 executeBatch).
  async prepareBatch(userId: string, input: z.input<typeof evmBatchInput>) {
    const parsed = evmBatchInput.parse(input);
    const from = await this.fromAddress(userId);
    const built = await Promise.all(parsed.calls.map(c => this.build(parsed.network, from, c)));
    return this.previewCalls(userId, parsed.network, from, built.map(b => b.calls[0]!), built.map((b, index) => ({ ...b.description, index })), parsed.received_tolerance_bps);
  }

  async fromAddress(userId: string) {
    return this.address((await this.accounts.account(userId)).accountId);
  }

  // Delegation of the derived EOA (EIP-7702): the 23-byte designator 0xef0100 || implementation.
  async delegation(network: EvmNetwork, from: Address): Promise<Address | null> {
    const code = await this.client(network).getCode({ address: from });
    if (!code || code === "0x") return null;
    if (/^0xef0100[0-9a-f]{40}$/i.test(code)) return getAddress(`0x${code.slice(8)}`);
    throw new NearPublicError("derived address has unexpected contract code; nothing was signed");
  }

  // One EVM transaction from the derived address: a single call is sent as is;
  // several calls are sent atomically as executeBatch to the address itself,
  // which requires its EIP-7702 delegation to the pinned Simple7702Account.
  async previewCalls(userId: string, network: EvmNetwork, from: Address, calls: NormalizedCall[], descriptions: CallDescription[], toleranceBps: number, extra: Record<string, unknown> = {}) {
    const chainId = EVM_CHAINS[network];
    const rpc = this.client(network);
    if (await rpc.getChainId() !== chainId) throw new NearPublicError("evm RPC chain ID mismatch");
    if (!calls.length || calls.length > MAX_BATCH_CALLS) throw new NearPublicError(`evm batch must have 1 to ${MAX_BATCH_CALLS} calls`);
    if (calls.length > 1 && (await this.delegation(network, from))?.toLowerCase() !== SIMPLE_7702_ACCOUNT.toLowerCase()) throw new NearPublicError(`evm batches need the derived address delegated (EIP-7702) to Simple7702Account ${SIMPLE_7702_ACCOUNT} on ${network}; use evm_delegation_prepare first, or send the calls one at a time. Nothing was signed`);
    const outer = calls.length === 1 ? calls[0]! : { to: from, value: "0", data: encodeFunctionData({ abi: EXECUTE_BATCH_ABI, functionName: "executeBatch", args: [calls.map(c => ({ target: c.to, value: BigInt(c.value), data: c.data }))] }) };
    const value = BigInt(outer.value);
    const spent = calls.reduce((n, c) => n + BigInt(c.value), 0n);
    const simulation = await this.simulate(network, from, calls, toleranceBps);
    if (JSON.stringify(descriptions.map(d => d.arguments ?? [])).includes(`"${UINT256_MAX}"`)) simulation.max_amount_growth_bps = MAX_AMOUNT_GROWTH_BPS;
    const [nonce, fees, balance] = await Promise.all([rpc.getTransactionCount({ address: from, blockTag: "pending" }), rpc.estimateFeesPerGas(), rpc.getBalance({ address: from })]);
    let gas: bigint;
    try { gas = await rpc.estimateGas({ account: from, to: outer.to, value, data: outer.data }); }
    catch { throw new NearPublicError("evm call simulated but gas could not be estimated from the derived address; nothing was signed"); }
    gas = gas * 12n / 10n;
    // Head-room for base-fee growth while the user reads the preview.
    const maxPriorityFeePerGas = fees.maxPriorityFeePerGas ?? 0n;
    const maxFeePerGas = (fees.maxFeePerGas ?? 0n) * 2n + maxPriorityFeePerGas;
    const maxGasCost = gas * maxFeePerGas;
    if (balance < spent + maxGasCost) throw new NearPublicError(`insufficient ETH on derived address ${from}: needs up to ${formatEther(spent + maxGasCost)} ETH on ${network}, has ${formatEther(balance)}; nothing was signed`);
    const tx: TransactionSerializableEIP1559 = { type: "eip1559", chainId, nonce, to: outer.to, value, data: outer.data, gas, maxFeePerGas, maxPriorityFeePerGas };
    const payload = keccak256(serializeTransaction(tx));
    if (BigInt(payload) === 0n || BigInt(payload) >= SECP256K1_N) throw new NearPublicError("evm transaction hash is not a valid signing payload; prepare again");
    const plan: EvmPlan = { network, chainId, from, path: DERIVATION_PATH, tx: { to: outer.to, value: value.toString(), data: outer.data, nonce, gas: gas.toString(), maxFeePerGas: maxFeePerGas.toString(), maxPriorityFeePerGas: maxPriorityFeePerGas.toString() }, payload, simulation, ...(calls.length > 1 ? { calls } : {}) };
    const signArgs = { request: { path: DERIVATION_PATH, payload_v2: { Ecdsa: payload.slice(2) }, domain_id: 0 } };
    const nearTx = { receiverId: this.accounts.config.mpcContract, actions: [{ type: "function_call" as const, method: "sign", args_base64: Buffer.from(JSON.stringify(signArgs)).toString("base64"), gas: MPC_SIGN_GAS.toString(), deposit: "1" }] };
    return this.operations.preview(userId, nearTx, "chain_signature", { evm: plan }, {
      ...extra,
      evm_transaction: { network, chain_id: chainId, from, to: outer.to, value_wei: value.toString(), value_eth: formatEther(value), data: outer.data, nonce, gas_limit: gas.toString(), max_fee_per_gas: maxFeePerGas.toString(), max_evm_network_fee_wei: maxGasCost.toString(), max_evm_network_fee_eth: formatEther(maxGasCost), signing_payload: payload, ...(calls.length > 1 ? { kind: "eip7702_execute_batch", atomic: true } : {}) },
      ...(calls.length === 1 ? { evm_call: descriptions[0] } : { evm_calls: descriptions }),
      simulation,
      limitations: ["Simulated from the derived address at the block shown; it is re-simulated before the MPC signature is requested and refused if any outflow grows or a received token falls below simulation.asset_floors. On-chain execution can still differ.", ...(simulation.max_amount_growth_bps ? [`A max (uint256) amount: the whole position may have grown by up to ${simulation.max_amount_growth_bps / 100}% (e.g. accrued interest) when re-simulated; it is accepted only if every received token grows by at least the same proportion.`] : []), ...(calls.length > 1 ? ["The calls run in order in one transaction through the account's EIP-7702 code (Simple7702Account.executeBatch); if any call reverts, none takes effect."] : []), "Asset changes come from RPC tracing and can be incomplete; contract safety and economic intent are not proven by the ABI or simulation.", "The EVM fee is paid in ETH by the derived address; the NEAR fee by the NEAR account.", "Signing is asynchronous on the MPC network; the EVM transaction is broadcast only after its signature verifies for the derived address."],
    });
  }

  // One call through the smart wallet's builder: function_name alone uses the
  // verified ABI; the description is re-labelled from verification services.
  async build(network: EvmNetwork, from: Address, input: Omit<ParsedEvmCall, "network" | "received_tolerance_bps">): Promise<{ calls: NormalizedCall[]; description: CallDescription }> {
    const call = { to: input.to, value: input.value_wei, ...(input.data !== undefined ? { data: input.data } : {}), ...(input.function_name ? { function_name: input.function_name, args: input.args ?? [] } : {}), ...(input.abi ? { abi: input.abi } : {}) };
    let built: ReturnType<typeof normalizeTransaction>;
    try { built = normalizeTransaction(await withVerifiedAbis({ network, calls: [call] }, this.contracts), from); }
    catch (e) { throw new NearPublicError(`evm call is invalid: ${e instanceof Error ? e.message.slice(0, 300) : "cannot be encoded"}; nothing was signed`); }
    let descriptions = built.descriptions;
    if (this.contracts) descriptions = await annotateCalls(network, from, built.calls, descriptions, this.contracts).catch(() => descriptions);
    return { calls: built.calls, description: descriptions[0]! };
  }

  // eth_simulateV1 with asset tracing from the derived address (as the smart
  // wallet does for its account). A revert is named with the verified ABI.
  private async simulate(network: EvmNetwork, from: Address, calls: NormalizedCall[], toleranceBps: number, atBlock?: bigint): Promise<EvmSimulation> {
    const rpc = this.client(network);
    const blockNumber = atBlock ?? await rpc.getBlockNumber();
    for (const call of calls) if (call.data !== "0x") {
      const code = await rpc.getCode({ address: call.to, blockNumber });
      if (!code || code === "0x") throw new NearPublicError("evm calldata target has no contract code on the selected network; nothing was signed");
    }
    let result: { results: readonly { status: string; data?: Hex; logs?: readonly any[]; gasUsed: bigint }[]; assetChanges?: unknown };
    // Sequential calls from the derived address: the same msg.sender and order as
    // executeBatch, which calls each target from the account itself.
    try { result = await (rpc.simulateCalls as (a: unknown) => Promise<typeof result>)({ account: from, calls: calls.map(c => ({ to: c.to, value: BigInt(c.value), data: c.data })), blockNumber, traceAssetChanges: true, validation: false }); }
    catch { throw new NearPublicError("evm simulation is unavailable from the configured RPC; nothing was signed"); }
    const failed = calls.findIndex((_, i) => result.results[i]?.status !== "success");
    if (failed >= 0) {
      const call = calls[failed]!;
      const failure = new SimulationReverted(failed, call.to, (result.results[failed]?.data ?? "0x") as Hex);
      const abi = this.contracts ? await this.contracts.contract(network, call.to).then(x => x && x.source !== "bytecode_selectors" ? x.abi : undefined, () => undefined) : undefined;
      throw new NearPublicError(`evm ${revertMessage(failure.index, failure.to, failure.data, abi)}`);
    }
    const asset_changes = jsonValue(result.assetChanges);
    return { status: "success", block_number: blockNumber.toString(), asset_changes, nft_changes: nftChanges(result.results.flatMap(r => r.logs ?? []), from), asset_floors: receivedFloors(asset_changes, toleranceBps), received_tolerance_bps: toleranceBps, gas_used_execution_only: result.results.reduce((n, r) => n + r.gasUsed, 0n).toString() };
  }

  // Re-simulates the stored call right before the MPC request: anything worse
  // than the preview (or a revert now) refuses before NEAR is spent.
  private async recheck(plan: EvmPlan) {
    if (!plan.simulation) return;
    const calls: NormalizedCall[] = plan.calls ?? [{ to: plan.tx.to, value: plan.tx.value, data: plan.tx.data }];
    const fresh = await this.simulate(plan.network, plan.from, calls, plan.simulation.received_tolerance_bps);
    const floors = Object.fromEntries(Object.entries(plan.simulation.asset_floors).map(([k, v]) => [k, BigInt(v)]));
    let mismatch = assetChangeMismatch(plan.simulation.asset_changes, fresh.asset_changes, floors);
    if (mismatch && plan.simulation.max_amount_growth_bps) mismatch = scaledAssetMismatch(plan.simulation.asset_changes, fresh.asset_changes, floors, plan.simulation.max_amount_growth_bps);
    mismatch ??= nftChangeMismatch(plan.simulation.nft_changes, fresh.nft_changes);
    if (mismatch) throw new NearPublicError(`evm ${mismatch}. Nothing was signed`);
  }

  async execute(userId: string, id: string, purpose: string) {
    // The nonce is fixed in the preview. If the derived address sent anything
    // since, the signed transaction could never be mined: refuse before paying for MPC.
    const op = await this.store.operation(userId, id);
    const evmPlan = op?.kind === "chain_signature" && op.status === "prepared" ? (op.plan as { evm?: EvmPlan } | null)?.evm : undefined;
    if (evmPlan) {
      const pending = await this.client(evmPlan.network).getTransactionCount({ address: evmPlan.from, blockTag: "pending" });
      if (pending !== evmPlan.tx.nonce) throw new NearPublicError(`the derived address nonce on ${evmPlan.network} is now ${pending}, but this preview was built for nonce ${evmPlan.tx.nonce} (another transaction was sent since); call evm_call_prepare again. Nothing was signed`);
      await this.recheck(evmPlan);
    }
    const near = await this.operations.execute(userId, id, purpose, "chain_signature", "FINAL");
    if (near.status !== "confirmed") return { ...near, stage: "near_signature" };
    return this.complete(userId, id);
  }

  async operationStatus(userId: string, id: string): Promise<Record<string, unknown>> {
    const op = await this.store.operation(userId, id);
    if (!op || op.kind !== "chain_signature") return this.operations.status(userId, id);
    const result = op.result as { evm_tx_hash?: Hex; evm_receipt?: { status: string }; child_operation_id?: string; stage?: string } | null;
    if (result?.child_operation_id) return { ...await this.operationStatus(userId, result.child_operation_id) as Record<string, unknown>, operation_id: id, child_operation_id: result.child_operation_id };
    if (op.status === "failed" && result?.stage === "authorization_signed") return { operation_id: id, stage: "evm_dropped", message: op.error };
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
  private async complete(userId: string, id: string): Promise<Record<string, unknown>> {
    const op = (await this.store.operation(userId, id))!;
    const plan = (op.plan as { evm: EvmPlan }).evm;
    const returned = (op.outcome as { return_value?: unknown } | null)?.return_value;
    const signature = parseMpcSignature(returned);
    if (plan.authorization) return this.completeAuthorization(userId, id, plan, signature);
    const tx = txFromPlan(plan);
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

  // EIP-7702, step 1 of 2: the MPC signed the authorization tuple. Prove it
  // recovers to the derived address, then preview and run the NEAR sign() of the
  // self-sent type-4 transaction carrying it (step 2) under the same confirmation.
  private async completeAuthorization(userId: string, id: string, plan: EvmPlan, signature: { r: Hex; s: Hex; yParity: number }): Promise<Record<string, unknown>> {
    const auth = plan.authorization!;
    if (hashAuthorization(auth) !== plan.payload) throw new Error("stored authorization does not match its signing payload");
    if ((await recoverAuthorizationAddress({ authorization: auth, signature })).toLowerCase() !== plan.from.toLowerCase()) throw new NearPublicError("authorization signature does not recover to the derived address; nothing was broadcast");
    const signed: SignedAuth = { ...auth, ...signature };
    const rpc = this.client(plan.network);
    const nonce = await rpc.getTransactionCount({ address: plan.from, blockTag: "pending" });
    if (nonce + 1 !== auth.nonce) {
      await this.store.update(userId, id, { status: "failed", result: { stage: "authorization_signed", evm_network: plan.network }, error: "derived address nonce moved after the authorization was signed" });
      return { operation_id: id, stage: "evm_dropped", message: `Another transaction from ${plan.from} changed its nonce, so the signed authorization can no longer be used. Nothing changed on ${plan.network}; only the NEAR signing fee was spent. Prepare the delegation again.` };
    }
    const txPlan: EvmPlan = { network: plan.network, chainId: plan.chainId, from: plan.from, path: plan.path, tx: { ...plan.tx, nonce, authorizationList: [signed] }, payload: "0x" };
    txPlan.payload = keccak256(serializeTransaction(txFromPlan(txPlan)));
    const signArgs = { request: { path: DERIVATION_PATH, payload_v2: { Ecdsa: txPlan.payload.slice(2) }, domain_id: 0 } };
    const nearTx = { receiverId: this.accounts.config.mpcContract, actions: [{ type: "function_call" as const, method: "sign", args_base64: Buffer.from(JSON.stringify(signArgs)).toString("base64"), gas: MPC_SIGN_GAS.toString(), deposit: "1" }] };
    const child = await this.operations.preview(userId, nearTx, "chain_signature", { evm: txPlan, parent_operation_id: id });
    await this.store.update(userId, id, { status: "confirmed", result: { stage: "authorization_signed", authorization: signed, child_operation_id: child.operation_id, evm_network: plan.network } });
    const near = await this.operations.execute(userId, child.operation_id, `EIP-7702 ${auth.address === zeroAddress ? "revocation" : "delegation"} transaction for operation ${id}`, "chain_signature", "FINAL");
    if (near.status !== "confirmed") return { ...near, operation_id: id, child_operation_id: child.operation_id, stage: "near_signature", next: "Call near_operation_status with this operation_id." };
    return { ...await this.complete(userId, child.operation_id), operation_id: id, child_operation_id: child.operation_id };
  }

  // Preview of an EIP-7702 delegation to the pinned Simple7702Account (or its
  // revocation): the MPC signs the authorization, then the type-4 transaction.
  async prepareDelegation(userId: string, input: z.input<typeof evmDelegationInput>) {
    const { network, action } = evmDelegationInput.parse(input);
    const from = await this.fromAddress(userId);
    const chainId = EVM_CHAINS[network];
    const rpc = this.client(network);
    if (await rpc.getChainId() !== chainId) throw new NearPublicError("evm RPC chain ID mismatch");
    const current = await this.delegation(network, from);
    const target = action === "delegate" ? SIMPLE_7702_ACCOUNT : zeroAddress;
    if (action === "delegate" && current?.toLowerCase() === SIMPLE_7702_ACCOUNT.toLowerCase()) throw new NearPublicError(`evm address is already delegated to Simple7702Account on ${network}; nothing to do`);
    if (action === "revoke" && !current) throw new NearPublicError(`evm address has no delegation on ${network}; nothing to do`);
    const [nonce, fees, balance] = await Promise.all([rpc.getTransactionCount({ address: from, blockTag: "pending" }), rpc.estimateFeesPerGas(), rpc.getBalance({ address: from })]);
    const maxPriorityFeePerGas = fees.maxPriorityFeePerGas ?? 0n;
    const maxFeePerGas = (fees.maxFeePerGas ?? 0n) * 2n + maxPriorityFeePerGas;
    const maxGasCost = DELEGATION_GAS * maxFeePerGas;
    if (balance < maxGasCost) throw new NearPublicError(`insufficient ETH on derived address ${from}: needs up to ${formatEther(maxGasCost)} ETH on ${network}, has ${formatEther(balance)}; nothing was signed`);
    // Self-sponsored: the sender's nonce is consumed before the authorization is processed.
    const authorization = { address: target, chainId, nonce: nonce + 1 };
    const payload = hashAuthorization(authorization);
    const plan: EvmPlan = { network, chainId, from, path: DERIVATION_PATH, tx: { to: from, value: "0", data: "0x", nonce, gas: DELEGATION_GAS.toString(), maxFeePerGas: maxFeePerGas.toString(), maxPriorityFeePerGas: maxPriorityFeePerGas.toString() }, payload, authorization };
    const signArgs = { request: { path: DERIVATION_PATH, payload_v2: { Ecdsa: payload.slice(2) }, domain_id: 0 } };
    const nearTx = { receiverId: this.accounts.config.mpcContract, actions: [{ type: "function_call" as const, method: "sign", args_base64: Buffer.from(JSON.stringify(signArgs)).toString("base64"), gas: MPC_SIGN_GAS.toString(), deposit: "1" }] };
    return this.operations.preview(userId, nearTx, "chain_signature", { evm: plan }, {
      delegation: {
        network, action, evm_address: from, current_delegate: current, new_delegate: action === "delegate" ? { address: target, contract: "Simple7702Account (eth-infinitism account-abstraction v0.8)", source: "Sourcify-verified, stateless" } : null,
        authorization: { chain_id: chainId, address: target, nonce: nonce + 1, signing_payload: payload },
        transaction: { type: "eip7702", to: from, value_wei: "0", data: "0x", nonce, gas_limit: DELEGATION_GAS.toString(), max_fee_per_gas: maxFeePerGas.toString(), max_evm_network_fee_wei: maxGasCost.toString(), max_evm_network_fee_eth: formatEther(maxGasCost) },
        steps: ["NEAR sign() #1: the MPC signs this EIP-7702 authorization hash (shown above).", "NEAR sign() #2: the MPC signs the self-sent type-4 transaction carrying it (built right after #1, same nonce and fees).", "Broadcast after both signatures recover to the derived address."],
        near_fee: "Two sign() calls: up to 2 × max_network_fee_near (about 0.0008 NEAR each in practice).",
      },
      warnings: action === "delegate" ? [
        "The address keeps its key, balances and address; it also runs Simple7702Account code. execute/executeBatch accept calls only from the address itself or from EntryPoint v0.8 with a UserOperation signed by this key (this service never signs UserOperations).",
        "While delegated, ERC-1271 isValidSignature accepts any raw-hash signature of this key for this address.",
        "Undo any time with action \"revoke\".",
      ] : ["After revocation, batches (approve+swap in one transaction) are no longer possible; single calls still work."],
    });
  }

  // Re-broadcast of the persisted signed bytes when the EVM step is uncertain.
  async rebroadcast(userId: string, id: string) {
    const op = await this.store.operation(userId, id);
    const result = op?.result as { evm_raw_tx?: Hex; evm_network?: EvmNetwork } | null;
    if (!op || !result?.evm_raw_tx || !result.evm_network) throw new NearPublicError("operation has no signed EVM transaction");
    await this.client(result.evm_network).sendRawTransaction({ serializedTransaction: result.evm_raw_tx }).catch(() => undefined);
  }
}

function assetDeltas(changes: unknown): Map<string, bigint> | null {
  if (!Array.isArray(changes)) return changes == null ? new Map() : null;
  const out = new Map<string, bigint>();
  for (const c of changes as { token?: { address?: unknown }; value?: { diff?: unknown } }[]) {
    const token = c?.token?.address, diff = c?.value?.diff;
    if (typeof token !== "string" || !/^-?\d+$/.test(String(diff)) || out.has(token.toLowerCase())) return null;
    out.set(token.toLowerCase(), BigInt(String(diff)));
  }
  return out;
}

// For a call with a "max" amount: accepts the fresh simulation when it is the
// previewed trade scaled up by a factor k <= 1 + maxBps, where k is the largest
// growth of any outflow; every received token must grow by at least k too
// (against its floor). Same tokens, same or better rate, bounded size.
export function scaledAssetMismatch(preview: unknown, fresh: unknown, floors: Record<string, bigint>, maxBps: number): string | null {
  const approved = assetDeltas(preview), current = assetDeltas(fresh);
  const refuse = (why: string) => `simulated asset changes differ from preview (${why}); prepare and confirm a new operation`;
  if (!approved || !current) return refuse("unreadable");
  for (const [token, diff] of current) if (!approved.has(token) && diff !== 0n) return refuse(`${token}: previewed none, now ${diff}`);
  let kBps = 10_000n;
  for (const [token, diff] of approved) {
    if (diff >= 0n) continue;
    const now = current.get(token) ?? 0n;
    if (now > 0n) return refuse(`${token}: previewed outflow ${-diff}, now inflow ${now}`);
    const ratio = (-now * 10_000n + (-diff) - 1n) / -diff; // ceil, in bps of the previewed outflow
    if (ratio > kBps) kBps = ratio;
  }
  if (kBps > 10_000n + BigInt(maxBps)) return refuse(`a max amount grew more than ${maxBps} bps`);
  for (const [token, diff] of approved) {
    if (diff <= 0n) continue;
    const floor = floors[token] !== undefined && floors[token]! >= 0n && floors[token]! <= diff ? floors[token]! : diff;
    const minimum = floor * kBps / 10_000n;
    const now = current.get(token) ?? 0n;
    if (now < minimum) return refuse(`${token}: previewed ${diff}, minimum ${minimum} after scaling the max amount by ${kBps} bps, now ${now}`);
  }
  return null;
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

