import { createPublicClient, defineChain, encodeFunctionData, erc20Abi, formatUnits, getAddress, http, isAddress, keccak256, parseUnits, type Hex, type PublicClient, type TransactionSerializable } from "viem";
import { ARC_CHAIN_ID, ARC_NETWORK, ARC_USDC, type Config } from "./config.js";
import type { Store } from "./store.js";

// Basic Arc support for the hosted wallet: show the receive address and USDC
// balance, and send USDC on Arc through a single-use preview. CDP has no Arc
// network yet, so the CDP account only signs a fully built EIP-1559 transfer
// (chain id 5042, fixed USDC transfer calldata) and we broadcast it ourselves.
// No generic signing is exposed: the only transaction ever built here is a
// USDC transfer(to, amount) on Arc.

const USDC_DECIMALS = 6;
const NATIVE_TO_USDC_ATOMIC = 10n ** 12n; // native USDC gas uses 18 decimals
const ZERO = "0x0000000000000000000000000000000000000000";

export type ArcSigner = { address: string; signTransaction(tx: TransactionSerializable): Promise<Hex> };
export type ArcChain = Pick<PublicClient, "readContract" | "estimateGas" | "estimateFeesPerGas" | "getTransactionCount" | "sendRawTransaction" | "waitForTransactionReceipt">;
type ArcStore = Pick<Store, "arcTransferredToday" | "createArcPreview" | "reserveArcTransfer" | "finishArcTransfer" | "withPaymentLock">;

export function arcChain(rpcUrl: string) {
  return defineChain({ id: ARC_CHAIN_ID, name: "Arc", nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 }, rpcUrls: { default: { http: [rpcUrl] } } });
}

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
  if (to.toLowerCase() === ARC_USDC) throw new Error("refusing to send to the USDC token contract");
  return to;
}

const usdc = (atomic: bigint) => formatUnits(atomic, USDC_DECIMALS);

export class ArcService {
  constructor(private config: Config, private store: ArcStore, private signerFor: (userId: string) => Promise<ArcSigner>, private chain: ArcChain) {}

  static create(config: Config, store: Store, signerFor: (userId: string) => Promise<ArcSigner>) {
    const client = createPublicClient({ chain: arcChain(config.ARC_RPC_URL), transport: http(config.ARC_RPC_URL, { timeout: 15_000 }) });
    return new ArcService(config, store, signerFor, client as unknown as ArcChain);
  }

  private get perTransferLimit() { return BigInt(this.config.ARC_MAX_TRANSFER_USDC_ATOMIC); }
  private get dailyLimit() { return BigInt(this.config.ARC_MAX_DAILY_TRANSFER_USDC_ATOMIC); }

  private balance(address: string) {
    return this.chain.readContract({ address: ARC_USDC, abi: erc20Abi, functionName: "balanceOf", args: [address as `0x${string}`] }) as Promise<bigint>;
  }

  async status(userId: string) {
    const signer = await this.signerFor(userId);
    const [balance, usedToday] = await Promise.all([this.balance(signer.address), this.store.arcTransferredToday(userId)]);
    return {
      network: ARC_NETWORK,
      chain_id: ARC_CHAIN_ID,
      address: signer.address,
      usdc_atomic: balance.toString(),
      usdc: usdc(balance),
      receive: `Send USDC on Arc (chain id ${ARC_CHAIN_ID}) to ${signer.address}. Funds sent on another network will not appear here.`,
      limits: { per_transfer_usdc: usdc(this.perTransferLimit), daily_usdc: usdc(this.dailyLimit), used_last_24h_usdc: usdc(usedToday) },
      note: "Gas on Arc is paid in USDC from this same balance.",
    };
  }

  async preview(userId: string, toInput: string, amountInput: string) {
    const signer = await this.signerFor(userId);
    const to = normalizeRecipient(toInput, signer.address);
    const amount = parseUsdcAmount(amountInput);
    if (amount > this.perTransferLimit) throw new Error(`amount exceeds the per-transfer limit of ${usdc(this.perTransferLimit)} USDC`);
    const usedToday = await this.store.arcTransferredToday(userId);
    if (usedToday + amount > this.dailyLimit) throw new Error(`amount exceeds the remaining daily limit of ${usdc(this.dailyLimit - usedToday > 0n ? this.dailyLimit - usedToday : 0n)} USDC`);
    const balance = await this.balance(signer.address);
    if (amount > balance) throw new Error(`insufficient balance: ${usdc(balance)} USDC available on Arc`);
    const data = encodeFunctionData({ abi: erc20Abi, functionName: "transfer", args: [to, amount] });
    const gas = await this.chain.estimateGas({ account: signer.address as `0x${string}`, to: ARC_USDC, data });
    const fees = await this.chain.estimateFeesPerGas();
    const fee = ceilDiv(gas * fees.maxFeePerGas, NATIVE_TO_USDC_ATOMIC);
    if (amount + fee > balance) throw new Error(`insufficient balance for amount plus network fee (~${usdc(fee)} USDC); ${usdc(balance)} USDC available`);
    const saved = await this.store.createArcPreview({ userId, to, amount, fee }, this.config.PREVIEW_TTL_SECONDS);
    return {
      preview_id: saved.id,
      expires_at: saved.expiresAt,
      network: ARC_NETWORK,
      from: signer.address,
      to,
      amount_usdc: usdc(amount),
      max_network_fee_usdc: usdc(fee),
      balance_usdc: usdc(balance),
      next_step: "Confirm the recipient and amount with the user, then call arc_transfer with this preview_id. Nothing has been signed or sent.",
    };
  }

  async transfer(userId: string, previewId: string, purpose: string) {
    return this.store.withPaymentLock(userId, () => this.transferLocked(userId, previewId, purpose));
  }

  private async transferLocked(userId: string, previewId: string, purpose: string) {
    const reserved = await this.store.reserveArcTransfer(userId, previewId, purpose, this.dailyLimit);
    if (!reserved) throw new Error("preview is expired, already used, or does not belong to this user");
    const { transferId, amount } = reserved;
    const to = getAddress(reserved.to);
    let hash: Hex | null = null;
    try {
      const signer = await this.signerFor(userId);
      const from = signer.address as `0x${string}`;
      const data = encodeFunctionData({ abi: erc20Abi, functionName: "transfer", args: [to, amount] });
      const [nonce, gas, fees] = await Promise.all([
        this.chain.getTransactionCount({ address: from, blockTag: "pending" }),
        this.chain.estimateGas({ account: from, to: ARC_USDC, data }),
        this.chain.estimateFeesPerGas(),
      ]);
      const signed = await signer.signTransaction({ type: "eip1559", chainId: ARC_CHAIN_ID, to: ARC_USDC, data, value: 0n, nonce, gas: (gas * 12n) / 10n, maxFeePerGas: fees.maxFeePerGas, maxPriorityFeePerGas: fees.maxPriorityFeePerGas });
      hash = keccak256(signed);
      await this.chain.sendRawTransaction({ serializedTransaction: signed });
    } catch (e) {
      // Once a signed transaction exists it may have reached the network even
      // if the RPC call failed, so it is recorded as unknown, never retried.
      await this.store.finishArcTransfer(transferId, hash ? "unknown" : "failed", hash, errorMessage(e));
      throw e;
    }
    await this.store.finishArcTransfer(transferId, "submitted", hash, null);
    try {
      const receipt = await this.chain.waitForTransactionReceipt({ hash, timeout: 20_000 });
      const ok = receipt.status === "success";
      await this.store.finishArcTransfer(transferId, ok ? "confirmed" : "failed", hash, ok ? null : "transaction reverted");
      return { status: ok ? "confirmed" : "failed", tx_hash: hash, network: ARC_NETWORK, to, amount_usdc: usdc(amount) };
    } catch {
      return { status: "submitted", tx_hash: hash, network: ARC_NETWORK, to, amount_usdc: usdc(amount), note: "Broadcast but not yet confirmed. Do not resend; check the transaction hash later." };
    }
  }
}

function ceilDiv(a: bigint, b: bigint) { return (a + b - 1n) / b; }
function errorMessage(e: unknown) { return e instanceof Error ? e.message : String(e); }
