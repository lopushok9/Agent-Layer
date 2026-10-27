import { createPublicClient, encodeFunctionData, erc20Abi, formatEther, formatUnits, getAddress, http, isAddress, keccak256, parseUnits, type Hex, type TransactionSerializable } from "viem";
import { BASE_NETWORK, BASE_USDC, type Config } from "./config.js";
import type { Store } from "./store.js";
import { publicActionsL2 } from "viem/op-stack";
import { base } from "viem/chains";
import { getDefaultEvmRpcUrls } from "@coinbase/cdp-sdk/x402";

// Fixed Base mainnet USDC transfers only; never accepts arbitrary calldata.
const USDC_DECIMALS = 6;
const BASE_CHAIN_ID = 8453;
const ZERO = "0x0000000000000000000000000000000000000000";

export type BaseSigner = { address: string; signTransaction(tx: TransactionSerializable): Promise<Hex> };
type BasePublicClient = ReturnType<typeof createBaseClient>;
function createBaseClient(rpcUrl: string) {
  return createPublicClient({ chain: base, transport: http(rpcUrl, { timeout: 15_000, retryCount: 0 }) }).extend(publicActionsL2());
}
export type BaseChain = Pick<BasePublicClient, "estimateL1Fee" | "estimateOperatorFee" | "getBalance" | "getChainId" | "readContract" | "estimateGas" | "estimateFeesPerGas" | "getTransactionCount" | "sendRawTransaction" | "waitForTransactionReceipt">;
export type BaseStore = Pick<Store, "baseTransferredToday" | "createBasePreview" | "reserveBaseTransfer" | "finishBaseTransfer" | "withPaymentLock">;

export function parseUsdcAmount(value: string): bigint {
  const text = value.trim();
  if (!/^\d+(\.\d{1,6})?$/.test(text)) throw new Error("amount_usdc must be a positive decimal with at most 6 decimal places");
  const atomic = parseUnits(text, USDC_DECIMALS);
  if (atomic <= 0n) throw new Error("amount_usdc must be greater than zero");
  return atomic;
}

export function normalizeRecipient(value: string, self: string): `0x${string}` {
  if (!isAddress(value, { strict: false })) throw new Error("to must be a 0x-prefixed 20-byte EVM address");
  const to = getAddress(value);
  if (to === ZERO) throw new Error("refusing to send to the zero address");
  if (to.toLowerCase() === self.toLowerCase()) throw new Error("refusing to send to this wallet's own address");
  if (to.toLowerCase() === BASE_USDC) throw new Error("refusing to send to the USDC token contract");
  return to;
}

const usdc = (atomic: bigint) => formatUnits(atomic, USDC_DECIMALS);

export class BaseService {
  constructor(private config: Config, private store: BaseStore, private signerFor: (userId: string) => Promise<BaseSigner>, private chain: BaseChain) {}

  static async create(config: Config, store: Store, signerFor: (userId: string) => Promise<BaseSigner>) {
    const rpcUrl = (await getDefaultEvmRpcUrls())[BASE_NETWORK]?.rpcUrl;
    if (!rpcUrl) throw new Error("Base RPC is unavailable");
    const client = createBaseClient(rpcUrl);
    return new BaseService(config, store, signerFor, client as unknown as BaseChain);
  }

  private get perTransferLimit() { return BigInt(this.config.BASE_MAX_TRANSFER_USDC_ATOMIC); }
  private get dailyLimit() { return BigInt(this.config.BASE_MAX_DAILY_TRANSFER_USDC_ATOMIC); }

  private balance(address: string) {
    return this.chain.readContract({ address: BASE_USDC, abi: erc20Abi, functionName: "balanceOf", args: [address as `0x${string}`] }) as Promise<bigint>;
  }

  private async extraFees(account: Hex, data: Hex) {
    const [l1, operator] = await Promise.all([
      this.chain.estimateL1Fee({ account, to: BASE_USDC, data, value: 0n }),
      this.chain.estimateOperatorFee({ account, to: BASE_USDC, data, value: 0n }),
    ]);
    return l1 + operator;
  }

  async preview(userId: string, toInput: string, amountInput: string) {
    if (await this.chain.getChainId() !== BASE_CHAIN_ID) throw new Error("RPC is not Base mainnet");
    const signer = await this.signerFor(userId);
    const to = normalizeRecipient(toInput, signer.address);
    const amount = parseUsdcAmount(amountInput);
    if (amount > this.perTransferLimit) throw new Error(`amount exceeds the per-transfer limit of ${usdc(this.perTransferLimit)} USDC`);
    const usedToday = await this.store.baseTransferredToday(userId);
    if (usedToday + amount > this.dailyLimit) throw new Error(`amount exceeds the remaining daily limit of ${usdc(this.dailyLimit - usedToday > 0n ? this.dailyLimit - usedToday : 0n)} USDC`);
    const balance = await this.balance(signer.address);
    if (amount > balance) throw new Error(`insufficient balance: ${usdc(balance)} USDC available on Base`);
    const data = encodeFunctionData({ abi: erc20Abi, functionName: "transfer", args: [to, amount] });
    const gasEstimate = await this.chain.estimateGas({ account: signer.address as `0x${string}`, to: BASE_USDC, data });
    const fees = await this.chain.estimateFeesPerGas();
    const gas = (gasEstimate * 12n + 9n) / 10n;
    const extras = await this.extraFees(signer.address as Hex, data);
    const fee = gas * fees.maxFeePerGas + extras;
    const ethBalance = await this.chain.getBalance({ address: signer.address as Hex });
    if (ethBalance < fee) throw new Error(`insufficient ETH for Base gas: need at least ~${formatEther(fee)} ETH including estimated L1/operator fees; fund ${signer.address} with ETH on Base`);
    const saved = await this.store.createBasePreview({ userId, to, amount, fee, from: signer.address }, this.config.PREVIEW_TTL_SECONDS);
    return {
      preview_id: saved.id,
      expires_at: saved.expiresAt,
      network: BASE_NETWORK,
      from: signer.address,
      to,
      amount_usdc: usdc(amount),
      estimated_network_fee_eth: formatEther(fee),
      note: "Gas is paid separately in ETH on Base. Includes estimated L1/operator fees and a gas buffer; actual network fees may vary.",
      balance_usdc: usdc(balance),
      next_step: "Confirm the recipient and amount with the user, then call base_transfer with this preview_id. Nothing has been signed or sent.",
    };
  }

  async transfer(userId: string, previewId: string, purpose: string) {
    return this.store.withPaymentLock(userId, () => this.transferLocked(userId, previewId, purpose));
  }

  private async transferLocked(userId: string, previewId: string, purpose: string) {
    const reserved = await this.store.reserveBaseTransfer(userId, previewId, purpose, this.dailyLimit);
    if (!reserved) throw new Error("preview is expired, already used, or does not belong to this user");
    const { transferId, amount } = reserved;
    const to = getAddress(reserved.to);
    let hash: Hex | null = null;
    try {
      const signer = await this.signerFor(userId);
      if (signer.address.toLowerCase() !== reserved.from.toLowerCase()) throw new Error("wallet changed; create a new preview");
      if (await this.chain.getChainId() !== BASE_CHAIN_ID) throw new Error("RPC is not Base mainnet");
      normalizeRecipient(to, signer.address);
      if (amount <= 0n || amount > this.perTransferLimit) throw new Error("amount exceeds current transfer policy; create a new preview");
      const from = signer.address as `0x${string}`;
      if (await this.balance(from) < amount) throw new Error("insufficient USDC on Base; create a new preview");
      const data = encodeFunctionData({ abi: erc20Abi, functionName: "transfer", args: [to, amount] });
      const [nonce, gas, fees] = await Promise.all([
        this.chain.getTransactionCount({ address: from, blockTag: "pending" }),
        this.chain.estimateGas({ account: from, to: BASE_USDC, data }),
        this.chain.estimateFeesPerGas(),
      ]);
      const gasLimit = (gas * 12n + 9n) / 10n;
      const executionFee = gasLimit * fees.maxFeePerGas + await this.extraFees(from, data);
      if (executionFee > reserved.fee) throw new Error("Base gas fee increased; create and confirm a new preview");
      if (await this.chain.getBalance({ address: from }) < executionFee) throw new Error("insufficient ETH for Base gas; fund this wallet on Base");
      const signed = await signer.signTransaction({ type: "eip1559", chainId: BASE_CHAIN_ID, to: BASE_USDC, data, value: 0n, nonce, gas: gasLimit, maxFeePerGas: fees.maxFeePerGas, maxPriorityFeePerGas: fees.maxPriorityFeePerGas });
      hash = keccak256(signed);
      // Persist the hash before broadcast so a process crash is auditable.
      await this.store.finishBaseTransfer(transferId, "unknown", hash, null);
      await this.chain.sendRawTransaction({ serializedTransaction: signed });
      await this.store.finishBaseTransfer(transferId, "submitted", hash, null);
    } catch (e) {
      // Once a signed transaction exists it may have reached the network even
      // if the RPC call failed, so it is recorded as unknown, never retried.
      try {
        await this.store.finishBaseTransfer(transferId, hash ? "unknown" : "failed", hash, errorMessage(e));
      } catch (storeError) {
        if (!hash) throw storeError;
        // A database outage must not turn a possibly broadcast transfer into
        // a retryable generic tool error. Its preview remains consumed.
        console.error(JSON.stringify({ event: "base_transfer_audit_unavailable", transfer_id: transferId, tx_hash: hash }));
      }
      if (hash) return { status: "unknown", tx_hash: hash, network: BASE_NETWORK, to, amount_usdc: usdc(amount), note: "A transaction was signed and broadcast may have succeeded. Do not resend; check the hash on BaseScan." };
      throw e;
    }
    try {
      const receipt = await this.chain.waitForTransactionReceipt({ hash, timeout: 20_000 });
      const ok = receipt.status === "success";
      await this.store.finishBaseTransfer(transferId, ok ? "confirmed" : "failed", hash, ok ? null : "transaction reverted");
      return { status: ok ? "confirmed" : "failed", tx_hash: hash, network: BASE_NETWORK, to, amount_usdc: usdc(amount) };
    } catch {
      return { status: "submitted", tx_hash: hash, network: BASE_NETWORK, to, amount_usdc: usdc(amount), note: "Broadcast but not yet confirmed. Do not resend; check the transaction hash later." };
    }
  }
}

function errorMessage(e: unknown) { return e instanceof Error ? e.message : String(e); }
