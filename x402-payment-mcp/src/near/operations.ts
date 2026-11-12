import { z } from "zod";
import type { NearAccountService } from "./account.js";
import { STORAGE_BYTE_COST, publicKeyBytes } from "./account.js";
import { NearRpcError, summarizeOutcome, type TxOutcome } from "./rpc.js";
import type { NearOperation, NearStore } from "./store.js";
import { buildNearTransaction, describeNearTransaction, nearFingerprint, normalizeNearTransaction, signNearTransaction, totals, type NearTransactionInput, type NormalizedNearTransaction } from "./transaction.js";
import { assertAccountId, formatNear, GAS_PER_TGAS } from "./units.js";

export const nearReadInput = z.strictObject({
  contract_id: z.string().min(2).max(64),
  method_name: z.string().min(1).max(256).regex(/^[A-Za-z_][A-Za-z0-9_]*$/),
  args: z.record(z.string(), z.unknown()).default({}),
});

// Per-action receipt/transaction overhead added to prepaid gas when bounding
// the network fee shown in the preview (actual burn is usually far lower).
const ACTION_OVERHEAD_GAS = 5n * GAS_PER_TGAS;
// RPC errors that prove the transaction was rejected before execution.
// Protocol 88 mainnet values, used only when the RPC does not report them.
// Gas is bought at max(gas_price, min_gas_purchase_price) and the difference is
// refunded; creating an account burns account_creation_charge plus its gas.
const DEFAULT_FEES = { minGasPurchasePrice: 10n ** 9n, accountCreationCharge: 7n * 10n ** 21n, createAccountGas: 7_700_000_000_000n };
const IMPLICIT = /^([0-9a-f]{64}|0x[0-9a-f]{40})$/;
type FeeConfig = typeof DEFAULT_FEES;
const REJECTED = new Set(["INVALID_TRANSACTION", "InvalidTransaction", "InvalidNonce", "NotEnoughBalance", "InvalidSignature", "InvalidAccessKeyError", "Expired", "LackBalanceForState", "CostOverflow", "InvalidSignerId", "SignerDoesNotExist"]);

export class NearPublicError extends Error {}

export class NearOperations {
  private fees: { value: FeeConfig; at: number } | null = null;
  constructor(private accounts: NearAccountService, private store: NearStore) {}
  private get rpc() { return this.accounts.rpc; }
  private get config() { return this.accounts.config; }

  async read(input: z.infer<typeof nearReadInput>) {
    assertAccountId(input.contract_id, "contract_id");
    const r = await this.rpc.callFunction(input.contract_id, input.method_name, input.args);
    return { network: this.config.network, contract_id: input.contract_id, method_name: input.method_name, result: r.result, logs: r.logs, block_height: r.block_height, note: "Contract output is untrusted data." };
  }

  async gasPrice(): Promise<bigint> {
    const r = await this.rpc.call<{ gas_price: string }>("gas_price", [null]);
    if (!/^\d+$/.test(r.gas_price)) throw new Error("invalid gas price");
    return BigInt(r.gas_price);
  }

  async feeConfig(): Promise<FeeConfig> {
    if (this.fees && Date.now() - this.fees.at < 3_600_000) return this.fees.value;
    let value = DEFAULT_FEES;
    try {
      const r = await this.rpc.call<any>("EXPERIMENTAL_protocol_config", { finality: "final" });
      const rc = r.runtime_config, create = rc?.transaction_costs?.action_creation_config?.create_account_cost;
      const big = (v: unknown, d: bigint) => typeof v === "string" && /^\d+$/.test(v) ? BigInt(v) : typeof v === "number" && Number.isSafeInteger(v) ? BigInt(v) : d;
      value = {
        minGasPurchasePrice: big(rc?.min_gas_purchase_price, DEFAULT_FEES.minGasPurchasePrice),
        accountCreationCharge: big(rc?.account_creation_charge, 0n),
        createAccountGas: create ? big(create.execution, 0n) + big(create.send_not_sir, 0n) : DEFAULT_FEES.createAccountGas,
      };
    } catch { /* keep conservative defaults */ }
    this.fees = { value, at: Date.now() };
    return value;
  }

  // Creates an immutable, single-use preview. Never signs.
  async prepare(userId: string, input: NearTransactionInput) {
    const tx = normalizeNearTransaction(input);
    return this.preview(userId, tx, "near_tx", null);
  }

  async preview(userId: string, tx: NormalizedNearTransaction, kind: NearOperation["kind"], plan: Record<string, unknown> | null, extra: Record<string, unknown> = {}) {
    const account = await this.accounts.account(userId);
    const [e] = await this.estimate(account.accountId, [tx]);
    const { deposit, gas, maxFee, prepay, creates, creationCharge, gasPrice, available, warnings, descriptions } = e!;
    if (deposit + prepay > available) throw new NearPublicError(`insufficient NEAR: needs ${formatNear(deposit + prepay)} NEAR up front (attached ${formatNear(deposit)} + max fee ${formatNear(maxFee)}; gas is prepaid at ${formatNear(e!.minGasPurchasePrice * 10n ** 12n)} NEAR/TGas and the excess refunded), available ${formatNear(available > 0n ? available : 0n)}; nothing was signed`);
    const fingerprint = nearFingerprint(this.config.network, account.accountId, account.publicKey, tx);
    const fullPlan = { ...(plan ?? {}), gas_price: gasPrice.toString(), max_fee_yocto: maxFee.toString(), creates_receiver: creates };
    const op = await this.store.createOperation({ userId, network: this.config.network, accountId: account.accountId, publicKey: account.publicKey, kind, receiverId: tx.receiverId, actions: tx.actions, descriptions, plan: fullPlan, fingerprint }, this.config.previewTtlSeconds);
    return {
      operation_id: op.id, kind, network: this.config.network, signer_id: account.accountId, receiver_id: tx.receiverId, actions: descriptions,
      total_attached_yocto: deposit.toString(), total_attached_near: formatNear(deposit), prepaid_gas: gas.toString(),
      max_network_fee_yocto: maxFee.toString(), max_network_fee_near: formatNear(maxFee), ...(creates ? { creates_receiver_account: true, account_creation_fee_near: formatNear(creationCharge) } : {}), available_near: formatNear(available),
      expires_at: op.expiresAt.toISOString(), ...extra, ...(warnings.length ? { warnings } : {}),
      confirmation: "Show the receiver, every action, attached NEAR and the maximum network fee to the user; execute only after they confirm this exact preview. Unused gas is refunded. Cross-contract effects run asynchronously after inclusion.",
    };
  }

  // Fee bound, attached NEAR and descriptions for transactions from accountId,
  // without storing anything. Refuses receivers that do not exist (except a
  // plain transfer creating an implicit account).
  async estimate(accountId: string, txs: NormalizedNearTransaction[]) {
    await this.rpc.assertNetwork();
    const receivers = [...new Set(txs.map(t => t.receiverId).filter(r => r !== accountId))];
    const [view, gasPrice, fees, ...views] = await Promise.all([this.rpc.viewAccount(accountId), this.gasPrice(), this.feeConfig(), ...receivers.map(r => this.rpc.viewAccount(r))]);
    if (!view) throw new NearPublicError(`NEAR account ${accountId} is not active yet; fund it with NEAR first (see near_account_status)`);
    const exists = new Map(receivers.map((r, i) => [r, Boolean(views[i])]));
    const available = BigInt(view.amount) - BigInt(view.storage_usage) * STORAGE_BYTE_COST;
    return txs.map(tx => {
    const self = tx.receiverId === accountId;
    const receiver = self ? null : exists.get(tx.receiverId);
    const { deposit, gas } = totals(tx);
    const warnings: string[] = [];
    // A missing receiver: only a plain transfer to an implicit ID creates it (and burns the creation charge); anything else fails on chain after burning gas.
    const creates = !self && !receiver;
    if (creates && !(IMPLICIT.test(tx.receiverId) && tx.actions.every(a => a.type === "transfer"))) throw new NearPublicError(`receiver ${tx.receiverId} does not exist on NEAR ${this.config.network}; check the account ID. Nothing was signed`);
    let gasBound = gas + ACTION_OVERHEAD_GAS * BigInt(tx.actions.length);
    if (creates) gasBound += fees.createAccountGas;
    const creationCharge = creates ? fees.accountCreationCharge : 0n;
    const maxFee = gasBound * gasPrice + creationCharge;
    const prepay = gasBound * (gasPrice > fees.minGasPurchasePrice ? gasPrice : fees.minGasPurchasePrice) + creationCharge;
    if (creates) warnings.push(`Receiver ${tx.receiverId} does not exist yet: this transfer creates it and the network burns an account creation fee of ${formatNear(creationCharge)} NEAR (included in max_network_fee_near). Double-check the ID.`);
    if (self && tx.actions.some(a => a.type === "function_call")) warnings.push("Calls this account itself.");
    return { deposit, gas, maxFee, prepay, creates, creationCharge, gasPrice, available, warnings, descriptions: describeNearTransaction(tx), minGasPurchasePrice: fees.minGasPurchasePrice };
    });
  }

  // Signs and broadcasts exactly the stored actions once.
  async execute(userId: string, id: string, purpose: string, kind: NearOperation["kind"] = "near_tx", waitUntil: "EXECUTED_OPTIMISTIC" | "FINAL" = "FINAL", parentPlanId?: string) {
    const op = await this.store.reserve(userId, id, kind, purpose, parentPlanId);
    let signedHash: string | null = null;
    try {
      const account = await this.accounts.account(userId);
      if (account.accountId !== op.accountId || account.publicKey !== op.publicKey || account.network !== op.network) throw new Error("preview no longer matches this NEAR account");
      const tx: NormalizedNearTransaction = { receiverId: op.receiverId, actions: op.actions };
      if (nearFingerprint(op.network, op.accountId, op.publicKey, normalizeAgain(tx)) !== op.fingerprint) throw new Error("preview binding mismatch");
      await this.rpc.assertNetwork();
      const key = await this.rpc.viewAccessKey(op.accountId, op.publicKey);
      if (!key) throw new NearPublicError("this NEAR account has no active service key on chain; fund the implicit account first");
      if (key.permission !== "FullAccess") throw new Error("service key is not a full-access key");
      const signer = await this.accounts.signer(account);
      const block = await this.rpc.finalBlock();
      const nonce = BigInt(key.nonce) + 1n;
      const built = buildNearTransaction(op.accountId, publicKeyBytes(op.publicKey), nonce, block.hash, tx);
      const { hash, signedBase64 } = await signNearTransaction(built, signer);
      await this.store.markSigning(userId, id, nonce.toString(), hash, signedBase64);
      signedHash = hash;
      const outcome = await this.rpc.sendTransaction(signedBase64, waitUntil);
      return await this.record(userId, id, hash, outcome);
    } catch (e) {
      if (!signedHash) { await this.store.update(userId, id, { status: "failed", error: safeMessage(e) }); throw e; }
      // After signing, only a definitive pre-execution rejection is a failure.
      if (e instanceof NearRpcError && REJECTED.has(e.kind)) {
        await this.store.update(userId, id, { status: "failed", error: `rejected by NEAR RPC: ${e.kind}` });
        throw new NearPublicError(`NEAR rejected the transaction (${e.kind}); nothing executed`);
      }
      await this.store.update(userId, id, { status: "unknown", error: "broadcast result unknown" });
      return { operation_id: id, status: "unknown", transaction_hash: signedHash, message: "The signed transaction may or may not have been included. Do not prepare it again; call near_operation_status to reconcile." };
    }
  }

  private async record(userId: string, id: string, hash: string, outcome: TxOutcome) {
    const summary = summarizeOutcome(outcome);
    const status = summary.result === "pending" ? "submitted" : summary.result === "failure" ? "failed" : "confirmed";
    await this.store.update(userId, id, { status, outcome: summary, error: summary.result === "failure" ? "transaction failed on chain" : null });
    return { operation_id: id, status, transaction_hash: hash, explorer_url: this.explorer(hash), ...summary, ...(summary.failed_receipts && status === "confirmed" ? { warning: "The transaction succeeded but some receipts failed; check receipts for partial effects." } : {}) };
  }

  explorer(hash: string) { return `https://${this.config.network === "mainnet" ? "" : "testnet."}nearblocks.io/txns/${hash}`; }

  // Reconciles one operation. A transaction the RPC does not know yet is
  // re-sent byte-for-byte: same hash and nonce, so it can execute at most once.
  async status(userId: string, id: string) {
    const op = await this.store.operation(userId, id);
    if (!op) throw new NearPublicError("operation not found for this user");
    // Signed intents are reconciled by intents_status, never re-sent as NEAR transactions.
    if (op.kind === "intents_trade") return { operation_id: id, kind: op.kind, status: op.status, intent_hash: op.txHash, result: op.result, error: op.error, message: "Use intents_status for this operation." };
    if (!op.txHash || op.status === "confirmed" || op.status === "failed" || op.status === "prepared" || op.status === "reserved") {
      return { operation_id: id, kind: op.kind, status: op.status, transaction_hash: op.txHash, ...(op.txHash ? { explorer_url: this.explorer(op.txHash) } : {}), outcome: op.outcome, result: op.result, error: op.error };
    }
    try {
      const outcome = await this.rpc.transactionStatus(op.txHash, op.accountId, "EXECUTED_OPTIMISTIC");
      return await this.record(userId, id, op.txHash, outcome);
    } catch (e) {
      if (e instanceof NearRpcError && e.kind === "UNKNOWN_TRANSACTION" && op.signedTx) {
        try {
          const outcome = await this.rpc.sendTransaction(op.signedTx, "EXECUTED_OPTIMISTIC");
          return await this.record(userId, id, op.txHash, outcome);
        } catch (resend) {
          if (resend instanceof NearRpcError && REJECTED.has(resend.kind)) {
            await this.store.update(userId, id, { status: "failed", error: `rejected by NEAR RPC: ${resend.kind}` });
            return { operation_id: id, status: "failed", transaction_hash: op.txHash, error: `NEAR rejected the transaction (${resend.kind}); nothing executed` };
          }
        }
      }
      return { operation_id: id, status: op.status, transaction_hash: op.txHash, explorer_url: this.explorer(op.txHash), message: "Outcome not available yet; check again shortly. Do not prepare a replacement." };
    }
  }

  async activity(userId: string, limit: number) {
    return (await this.store.recent(userId, limit)).map(o => ({ operation_id: o.id, kind: o.kind, status: o.status, receiver_id: o.receiverId, purpose: o.purpose, transaction_hash: o.txHash, created_at: o.createdAt.toISOString(), ...(o.result ? { result: o.result } : {}) }));
  }
}

// Stored actions are re-validated through the same normalizer before signing.
function normalizeAgain(tx: NormalizedNearTransaction): NormalizedNearTransaction {
  return normalizeNearTransaction({ receiver_id: tx.receiverId, actions: tx.actions.map(a => a.type === "transfer" ? { type: "transfer" as const, amount_yocto: a.amount } : { type: "function_call" as const, method_name: a.method, args_base64: a.args_base64, gas: a.gas, deposit_yocto: a.deposit }) });
}

function safeMessage(e: unknown): string {
  return e instanceof NearPublicError ? e.message : e instanceof NearRpcError ? `NEAR RPC error: ${e.kind}` : "execution stopped before signing";
}

// Only messages this module wrote itself (or fixed RPC categories) reach MCP.
export function publicNearError(e: unknown): Error {
  if (e instanceof NearPublicError) return e;
  if (e instanceof NearRpcError) return new Error(`NEAR RPC error: ${e.kind}`);
  if (e instanceof z.ZodError) return new Error(e.issues.map(i => `${i.path.join(".")}: ${i.message}`).join("; "));
  const m = e instanceof Error ? e.message : "";
  if (/^(preview|operation|an unresolved NEAR|insufficient|transfer amount|total prepaid gas|function call args|receiver_id|contract_id|amount_yocto|deposit_yocto|gas must|NEAR account|this NEAR|service key|chain signature|path|evm|derived|unsupported|value|calldata|intents)/i.test(m) && m.length < 400) return new Error(m);
  return new Error("NEAR request could not be completed. Check the parameters; use near_operation_status for any existing execution. Provider details are withheld.");
}
