import { createHash, randomBytes } from "node:crypto";
import { z } from "zod";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import type { PaymentPayload, PaymentRequirements, ResourceInfo } from "@x402/core/types";
import { formatUnits, getAddress, hashTypedData, parseAbi, parseEventLogs, recoverAddress, serializeSignature, zeroAddress, type Address, type Hex } from "viem";
import { BASE_NETWORK, BASE_USDC, type Config } from "../config.js";
import { assertSafeResourceUrl, safeFetch, safeFetchManual } from "../network.js";
import { assertNoPathPlaceholders, buildResourceUrl, decodeSettlement, HTTP_METHODS, methodCandidates, normalizeRequestHeaders, paymentListing, preflight, readResult, requestInit, searchPaymentServices, selectSmartAccountRequirement, type DiscoveryProvider, type RequestSpec } from "../payments.js";
import type { Store } from "../store.js";
import type { NearAccountService } from "./account.js";
import { DERIVATION_PATH, MPC_SIGN_GAS, parseMpcSignature, SIMPLE_7702_ACCOUNT, type ChainSignatures } from "./chain-signatures.js";
import { NearPublicError, type NearOperations } from "./operations.js";
import type { NearOperation, NearStore } from "./store.js";
import { nearFingerprint, type NormalizedNearTransaction } from "./transaction.js";
import type { NearPayment, NearPaymentStore, PaymentState } from "./x402-store.js";

const N = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;
const MIN_REMAINING_SECONDS = 10;
export const USDC_ABI = parseAbi([
  "function balanceOf(address) view returns (uint256)",
  "function transferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce,bytes signature)",
  "event AuthorizationUsed(address indexed authorizer,bytes32 indexed nonce)",
  "event AuthorizationCanceled(address indexed authorizer,bytes32 indexed nonce)",
  "event Transfer(address indexed from,address indexed to,uint256 value)",
]);
const USED = USDC_ABI[2], CANCELED = USDC_ABI[3];
const ERC1271 = parseAbi(["function isValidSignature(bytes32,bytes) view returns (bytes4)"]);
export const AUTHORIZATION_TYPES = { TransferWithAuthorization: [
  { name: "from", type: "address" }, { name: "to", type: "address" }, { name: "value", type: "uint256" },
  { name: "validAfter", type: "uint256" }, { name: "validBefore", type: "uint256" }, { name: "nonce", type: "bytes32" },
] } as const;
type Authorization = { from: Address; to: Address; value: string; validAfter: string; validBefore: string; nonce: Hex };
export type PaymentPlan = {
  accountId: string; publicKey: string; payer: Address; path: string; url: string;
  request: RequestSpec | null; requestHash: string; maxNearFee: string; maxNearPrepay: string; resource: ResourceInfo; terms: PaymentRequirements; binding: string;
  authorization?: Authorization; digest?: Hex; signature?: Hex; startBlock?: string; transaction?: Hex;
};
export const nearX402Input = z.strictObject({
  url: z.string().url().max(2048), method: z.enum(HTTP_METHODS).optional(),
  query: z.record(z.string(), z.union([z.string(), z.number(), z.boolean()])).optional(),
  headers: z.record(z.string(), z.string()).optional(), body: z.unknown().optional(),
  text_body: z.string().max(100_000).optional(), scheme: z.enum(["auto", "exact"]).default("auto"),
}).refine(v => v.body === undefined || v.body === null || v.text_body === undefined, "provide body or text_body, not both");
type Deps = { probe: typeof fetch; send: typeof fetch; listing: typeof paymentListing; now: () => number };
const defaults: Deps = { probe: safeFetchManual, send: safeFetch, listing: paymentListing, now: Date.now };

export function authorizationTypedData(a: Authorization) {
  return { domain: { name: "USD Coin", version: "2", chainId: 8453, verifyingContract: getAddress(BASE_USDC) },
    types: AUTHORIZATION_TYPES, primaryType: "TransferWithAuthorization" as const,
    message: { ...a, value: BigInt(a.value), validAfter: BigInt(a.validAfter), validBefore: BigInt(a.validBefore) } };
}
export function paymentBinding(p: PaymentPlan) {
  return fingerprint({ accountId: p.accountId, publicKey: p.publicKey, payer: p.payer.toLowerCase(), path: p.path, url: p.url, requestHash: p.requestHash, resource: p.resource, terms: p.terms, maxNearFee: p.maxNearFee, maxNearPrepay: p.maxNearPrepay });
}
function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.entries(v).sort(([a], [b]) => a.localeCompare(b)).map(([k, x]) => `${JSON.stringify(k)}:${stable(x)}`).join(",")}}`;
  return JSON.stringify(v);
}
const fingerprint = (v: unknown) => createHash("sha256").update(stable(v)).digest("hex");

// This service has no CDP EVM account/signer dependency. Only the NEAR account
// can request its MPC authorization. The HTTP request is dispatched at most once.
export class NearX402Payments {
  private deps: Deps;
  constructor(private config: Config, private accounts: NearAccountService, private operations: NearOperations,
    private nearStore: NearStore, private cs: ChainSignatures, private store: NearPaymentStore,
    private locks: Pick<Store, "withPaymentLock">, deps: Partial<Deps> = {}) { this.deps = { ...defaults, ...deps }; }

  search(query: string, limit: number, provider: DiscoveryProvider = "bazaar") { return searchPaymentServices(this.config, query, limit, provider); }

  async preview(userId: string, input: z.input<typeof nearX402Input>) {
    const p = nearX402Input.parse(input);
    this.mainnet();
    assertNoPathPlaceholders(p.url);
    const url0 = buildResourceUrl(p.url, p.query);
    const headers = normalizeRequestHeaders(p.headers);
    const spec = { ...(p.method ? { method: p.method } : {}), ...(headers ? { headers } : {}), ...(p.body != null ? { body: p.body } : {}), ...(p.text_body !== undefined ? { textBody: p.text_body } : {}) };
    const listing = await this.deps.listing(p.url);
    const probe = await preflight(this.deps.probe, url0, spec, p.method ? [p.method] : methodCandidates(listing.method, p.body != null || p.text_body !== undefined), Math.min(this.config.PAYMENT_TIMEOUT_MS, 15_000));
    const terms = selectSmartAccountRequirement(probe.challenge, this.config, p.scheme);
    this.validateTerms(terms);
    const account = await this.accounts.account(userId);
    const payer = await this.cs.fromAddress(userId);
    const payerDelegate = await this.checkPayer(payer, terms.amount);
    const request: RequestSpec = { ...spec, method: probe.method };
    const plan: PaymentPlan = { accountId: account.accountId, publicKey: account.publicKey, payer, path: DERIVATION_PATH,
      url: probe.url, request, requestHash: fingerprint(request), maxNearFee: "", maxNearPrepay: "", resource: probe.challenge.resource, terms, binding: "" };
    // Only estimate a representative sign request here: the random EIP-3009
    // nonce/deadline are created after confirmation, then saved before signing.
    const [fee] = await this.operations.estimate(account.accountId, [this.signTransaction(`0x${"01".repeat(32)}`)]);
    if (fee!.deposit + fee!.prepay > fee!.available) throw new NearPublicError("insufficient NEAR for the MPC signing request; nothing was signed");
    plan.maxNearFee = fee!.maxFee.toString(); plan.maxNearPrepay = fee!.prepay.toString();
    plan.binding = paymentBinding(plan);
    const saved = await this.store.create(userId, terms.amount, plan, this.config.PREVIEW_TTL_SECONDS);
    return { preview_id: saved.id, expires_at: saved.expiresAt.toISOString(), near_account_id: account.accountId, payer_address: payer,
      network: BASE_NETWORK, signing: "near_chain_signatures", derivation_path: DERIVATION_PATH,
      payer_account: { type: payerDelegate ? "eip7702_delegated" : "eoa", ...(payerDelegate ? { delegate: payerDelegate, warning: "Some x402 providers or facilitators reject delegated accounts even when the on-chain USDC simulation succeeds; compatibility is not guaranteed." } : {}) },
      resource: { url: probe.url, description: probe.challenge.resource.description, bazaar_listed: listing.listed,
        ...(listing.listed === true ? {} : { warning: "Unlisted API: confirm this exact URL, amount and recipient." }) },
      payment: { scheme: "exact", asset_transfer_method: "eip3009", asset: BASE_USDC, amount_atomic: terms.amount, amount_usdc: formatUnits(BigInt(terms.amount), 6), pay_to: terms.payTo, authorization_window_seconds: terms.maxTimeoutSeconds },
      near_fee: { max_network_fee_yocto: fee!.maxFee.toString(), upfront_yocto: fee!.prepay.toString(), attached_yocto: fee!.deposit.toString() },
      request: { method: request.method, header_names: Object.keys(headers ?? {}), has_body: request.body != null || request.textBody !== undefined },
      confirmation: "Show the API URL, Base USDC amount, recipient, NEAR account, derived payer and NEAR fee. Call x402_pay only after confirmation. No Base ETH or token approval is needed for this payment; the facilitator pays settlement gas." };
  }

  async pay(userId: string, id: string, purpose: string) {
    return this.locks.withPaymentLock(userId, async () => {
      this.mainnet();
      let row = await this.store.reserve(userId, id, purpose, this.config.SPEND_LIMITS_ENABLED ? BigInt(this.config.MAX_DAILY_USDC_ATOMIC) : null);
      try {
        await this.validatePlan(userId, row.plan);
        await this.checkPayer(row.plan.payer, row.amount);
        const now = Math.floor(this.deps.now() / 1000);
        row.plan.authorization = { from: row.plan.payer, to: getAddress(row.plan.terms.payTo), value: row.amount, validAfter: "0", validBefore: String(now + row.plan.terms.maxTimeoutSeconds), nonce: `0x${randomBytes(32).toString("hex")}` };
        row.plan.digest = hashTypedData(authorizationTypedData(row.plan.authorization));
        if (BigInt(row.plan.digest) === 0n || BigInt(row.plan.digest) >= N) throw new NearPublicError("authorization digest is outside the MPC signing range; prepare a new preview");
        row.plan.startBlock = (await this.cs.rpcFor("base").getBlockNumber()).toString();
        // The encrypted preimage is durable BEFORE its public digest is signed.
        row = await this.store.update(userId, id, "signing", row.plan);
        const [fee] = await this.operations.estimate(row.plan.accountId, [this.signTransaction(row.plan.digest!)]);
        if (fee!.maxFee > BigInt(row.plan.maxNearFee) || fee!.prepay > BigInt(row.plan.maxNearPrepay)) throw new NearPublicError("NEAR signing fee increased beyond the confirmed preview; prepare a new preview");
        const nearPreview = await this.operations.preview(userId, this.signTransaction(row.plan.digest!), "x402_authorization", { near_x402_payment_id: id, digest: row.plan.digest }, {}, id);
        if (BigInt(nearPreview.max_network_fee_yocto) > BigInt(row.plan.maxNearFee)) throw new NearPublicError("NEAR signing fee increased beyond the confirmed preview; prepare a new preview");
        if (BigInt(row.plan.authorization!.validBefore) <= BigInt(Math.floor(this.deps.now() / 1000) + MIN_REMAINING_SECONDS)) return this.finish(row, "expired", { failure_reason: "Authorization expired before MPC signing; nothing was sent." });
        await this.operations.execute(userId, id, purpose, "x402_authorization", "FINAL");
      } catch (e) {
        const op = await this.nearStore.operation(userId, id);
        if (!op || op.status === "prepared" || op.status === "reserved" || op.status === "failed") {
          if (op?.status === "reserved") await this.nearStore.update(userId, id, { status: "failed", error: "payment interrupted before broadcast" });
          return this.finish(row, "failed", { failure_reason: e instanceof NearPublicError ? e.message : "Payment stopped before an MPC authorization was broadcast. Nothing was sent to the API." });
        }
        // A durable NEAR transaction may already have requested the signature.
        return this.public(await this.store.get(userId, id) ?? row, { next_step: "Use x402_status to reconcile this same payment; never prepare a replacement." });
      }
      return this.continue(row);
    });
  }

  async status(userId: string, id: string) {
    return this.locks.withPaymentLock(userId, async () => {
      const row = await this.store.get(userId, id);
      if (!row) throw new NearPublicError("payment not found for this user");
      if (["prepared", "settled", "failed", "expired", "cancelled"].includes(row.status)) return this.public(row);
      if (["sending", "unknown"].includes(row.status)) return this.reconcile(row);
      // Resume only the already-confirmed payment. No new nonce, signature
      // request or paid retry is created by status.
      return this.continue(row);
    });
  }

  private async continue(row: NearPayment): Promise<Record<string, unknown>> {
    if (row.status === "reserved") return this.finish(row, "failed", { failure_reason: "Execution was interrupted before signing; prepare a new preview." });
    await this.validatePlan(row.userId, row.plan);
    let op = await this.nearStore.operation(row.userId, row.id);
    if (!op || op.status === "prepared" || op.status === "reserved") {
      if (op?.status === "reserved") await this.nearStore.update(row.userId, row.id, { status: "failed", error: "payment interrupted before broadcast" });
      return this.finish(row, "failed", { failure_reason: "No MPC request was broadcast; prepare a new preview." });
    }
    this.validateAuthorization(row, op);
    if (op.status !== "confirmed" && op.status !== "failed") {
      await this.operations.status(row.userId, row.id, "x402_authorization");
      op = (await this.nearStore.operation(row.userId, row.id))!;
    }
    if (op.status === "failed") return this.finish(row, "failed", { failure_reason: "The NEAR signing request failed. No payment was sent to the API." });
    if (op.status !== "confirmed") return this.public(row, { near_transaction_hash: op.txHash, next_step: "MPC signing is pending; call x402_status with the same preview_id." });
    let parsed: ReturnType<typeof parseMpcSignature>;
    try { parsed = parseMpcSignature((op.outcome as { return_value?: unknown })?.return_value); }
    catch { return this.finish(row, "failed", { failure_reason: "MPC returned a malformed signature. Nothing was sent to the API." }); }
    let s = BigInt(parsed.s), yParity = parsed.yParity;
    if (BigInt(parsed.r) <= 0n || BigInt(parsed.r) >= N || s <= 0n || s >= N) return this.finish(row, "failed", { failure_reason: "Invalid MPC signature scalars; nothing was sent to the API." });
    if (s > N / 2n) { s = N - s; yParity ^= 1; }
    const signature = serializeSignature({ r: parsed.r, s: `0x${s.toString(16).padStart(64, "0")}`, yParity });
    if ((await recoverAddress({ hash: row.plan.digest!, signature })).toLowerCase() !== row.plan.payer.toLowerCase()) return this.finish(row, "failed", { failure_reason: "MPC signature does not recover to the NEAR-derived payer. Nothing was sent to the API." });
    row.plan.signature = signature;
    row = await this.store.update(row.userId, row.id, "signed", row.plan);
    if (BigInt(row.plan.authorization!.validBefore) <= BigInt(Math.floor(this.deps.now() / 1000) + MIN_REMAINING_SECONDS)) return this.finish(row, "expired", { failure_reason: "Authorization has insufficient time remaining after MPC signing. Nothing was sent to the API; only NEAR gas may have been spent." });
    try {
      const delegated = await this.checkPayer(row.plan.payer, row.amount);
      if (delegated) {
        const magic = await this.cs.rpcFor("base").readContract({ address: row.plan.payer, abi: ERC1271, functionName: "isValidSignature", args: [row.plan.digest!, signature] });
        if (magic !== "0x1626ba7e") throw new Error("ERC-1271 rejected the signature");
      }
      const a = row.plan.authorization!;
      await this.cs.rpcFor("base").simulateContract({ address: getAddress(BASE_USDC), abi: USDC_ABI, functionName: "transferWithAuthorization", args: [a.from, a.to, BigInt(a.value), BigInt(a.validAfter), BigInt(a.validBefore), a.nonce, signature], account: a.to });
    } catch {
      return this.finish(row, "failed", { failure_reason: "Base USDC authorization simulation or payer checks failed. Nothing was sent to the API; only NEAR gas may have been spent." });
    }
    if (BigInt(row.plan.authorization!.validBefore) <= BigInt(Math.floor(this.deps.now() / 1000) + MIN_REMAINING_SECONDS)) return this.finish(row, "expired", { failure_reason: "Authorization expired during Base simulation; nothing was sent to the API." });
    // No SDK createPaymentPayload here: it would generate a SECOND random nonce.
    const payload: PaymentPayload = { x402Version: 2, resource: row.plan.resource, accepted: row.plan.terms, payload: { authorization: row.plan.authorization!, signature } };
    const headers = new x402HTTPClient(new x402Client()).encodePaymentSignatureHeader(payload);
    const request = row.plan.request!;
    const init = requestInit(request, this.config.PAYMENT_TIMEOUT_MS);
    // Persist the dispatch boundary and scrub request credentials BEFORE I/O.
    // A crash beyond this point is unknown and must never cause a second POST.
    row.plan.request = null;
    row = await this.store.update(row.userId, row.id, "sending", row.plan);
    try {
      const response = await this.deps.send(row.plan.url, { ...init, headers: { ...(init.headers as Record<string, string> | undefined), ...headers } });
      const result = await readResult(response);
      const settlement = decodeSettlement(response);
      if (settlement?.network === BASE_NETWORK && settlement.transaction && /^0x[0-9a-f]{64}$/i.test(settlement.transaction)) row.plan.transaction = settlement.transaction as Hex;
      row = await this.store.update(row.userId, row.id, "unknown", row.plan, { response_status: response.status, result, resource_received: response.ok });
    } catch {
      row = await this.store.update(row.userId, row.id, "unknown", row.plan, { failure_reason: "The paid HTTP request could not be confirmed. It will not be sent again automatically." });
    }
    return this.reconcile(row);
  }

  private async reconcile(row: NearPayment): Promise<Record<string, unknown>> {
    const a = row.plan.authorization;
    if (!a || row.plan.startBlock === undefined) return this.public(row, { next_step: "Payment state is incomplete; do not pay again." });
    const rpc = this.cs.rpcFor("base");
    let check = "chain_id";
    try {
      if (await rpc.getChainId() !== 8453) throw new Error("Base RPC chain ID mismatch");
      check = "latest_block_and_authorization_logs";
      if (row.plan.transaction && await this.provesPayment(row, row.plan.transaction).catch(() => false)) return this.finish(row, "settled", { transaction: row.plan.transaction, settled_amount_atomic: a.value });
      const latest = await rpc.getBlock();
      const used = await rpc.getLogs({ address: getAddress(BASE_USDC), event: USED, args: { authorizer: a.from, nonce: a.nonce }, fromBlock: BigInt(row.plan.startBlock), toBlock: latest.number });
      for (const log of used) if (log.transactionHash && await this.provesPayment(row, log.transactionHash).catch(() => false)) return this.finish(row, "settled", { transaction: log.transactionHash, settled_amount_atomic: a.value });
      // A provider can still settle a disclosed authorization until its deadline.
      // Only finalized chain time plus complete finalized logs release the hold.
      check = "finalized_block_and_authorization_logs";
      const final = await rpc.getBlock({ blockTag: "finalized" });
      if (final.number >= BigInt(row.plan.startBlock)) {
        const canceled = await rpc.getLogs({ address: getAddress(BASE_USDC), event: CANCELED, args: { authorizer: a.from, nonce: a.nonce }, fromBlock: BigInt(row.plan.startBlock), toBlock: final.number });
        if (canceled.length) return this.finish(row, "cancelled", { failure_reason: "The USDC authorization was canceled on chain. This does not indicate payment." });
        const finalUsed = final.timestamp > BigInt(a.validBefore) ? await rpc.getLogs({ address: getAddress(BASE_USDC), event: USED, args: { authorizer: a.from, nonce: a.nonce }, fromBlock: BigInt(row.plan.startBlock), toBlock: final.number }) : [];
        if (final.timestamp > BigInt(a.validBefore) && !used.length && !finalUsed.length) return this.finish(row, "expired", { failure_reason: "Finalized Base time passed the authorization deadline without a payment or cancellation event." });
      }
    } catch {
      // Never expose provider errors or URLs; uncertainty must not release the hold.
      return this.public(row, { reconciliation: { state: "rpc_unavailable_or_incomplete", check }, next_step: "Base chain verification failed or is incomplete. Call x402_status again; do not create another payment." });
    }
    return this.public(row, { reconciliation: { state: "awaiting_finalized_proof" }, next_step: "Settlement is unknown. Call x402_status again; do not create another payment for this purchase." });
  }

  private async provesPayment(row: NearPayment, hash: Hex) {
    const receipt = await this.cs.rpcFor("base").getTransactionReceipt({ hash });
    if (receipt.status !== "success") return false;
    const logs = receipt.logs.filter(l => l.address.toLowerCase() === BASE_USDC);
    const a = row.plan.authorization!;
    const events = parseEventLogs({ abi: USDC_ABI, logs, strict: true });
    return events.some(e => e.eventName === "AuthorizationUsed" && e.args.authorizer.toLowerCase() === a.from.toLowerCase() && e.args.nonce.toLowerCase() === a.nonce.toLowerCase()) &&
      events.some(e => e.eventName === "Transfer" && e.args.from.toLowerCase() === a.from.toLowerCase() && e.args.to.toLowerCase() === a.to.toLowerCase() && e.args.value === BigInt(a.value));
  }

  private validateTerms(r: PaymentRequirements) {
    if (r.scheme !== "exact" || r.network !== BASE_NETWORK || r.asset.toLowerCase() !== BASE_USDC || r.extra?.name !== "USD Coin" || r.extra?.version !== "2" ||
      r.extra?.assetTransferMethod && r.extra.assetTransferMethod !== "eip3009" || r.extra?.paymentFlow && r.extra.paymentFlow !== "authorization" ||
      !/^\d{1,78}$/.test(r.amount) || BigInt(r.amount) <= 0n || BigInt(r.amount) >= 2n ** 256n || getAddress(r.payTo) === zeroAddress ||
      !Number.isSafeInteger(r.maxTimeoutSeconds) || r.maxTimeoutSeconds < 30 || r.maxTimeoutSeconds > 3600) throw new NearPublicError("Only x402 v2 exact/EIP-3009 with canonical Base USDC, its USD Coin/2 domain and a 30–3600 second authorization window is supported");
    if (this.config.SPEND_LIMITS_ENABLED && BigInt(r.amount) > BigInt(this.config.MAX_PAYMENT_USDC_ATOMIC)) throw new NearPublicError("per-payment spend limit exceeded");
  }
  private async validatePlan(userId: string, p: PaymentPlan) {
    this.mainnet(); this.validateTerms(p.terms);
    const a = await this.accounts.account(userId);
    if (p.binding !== paymentBinding(p) || p.path !== DERIVATION_PATH || a.accountId !== p.accountId || a.publicKey !== p.publicKey || (await this.cs.fromAddress(userId)).toLowerCase() !== p.payer.toLowerCase() ||
      p.request && fingerprint(p.request) !== p.requestHash) throw new NearPublicError("payment preview binding or NEAR account changed; nothing was sent");
    assertSafeResourceUrl(p.url);
  }
  private validateAuthorization(row: NearPayment, op: NearOperation) {
    const p = row.plan, a = p.authorization;
    if (!a || !p.digest || a.from.toLowerCase() !== p.payer.toLowerCase() || a.to.toLowerCase() !== p.terms.payTo.toLowerCase() || a.value !== row.amount || a.value !== p.terms.amount || a.validAfter !== "0" || !/^0x[0-9a-f]{64}$/i.test(a.nonce) ||
      hashTypedData(authorizationTypedData(a)) !== p.digest || op.kind !== "x402_authorization" || op.accountId !== p.accountId || op.publicKey !== p.publicKey ||
      nearFingerprint(op.network, op.accountId, op.publicKey, this.signTransaction(p.digest)) !== op.fingerprint) throw new NearPublicError("stored authorization does not match the confirmed payment; nothing was sent");
  }
  private async checkPayer(payer: Address, amount: string) {
    const rpc = this.cs.rpcFor("base");
    if (await rpc.getChainId() !== 8453) throw new NearPublicError("Base RPC chain ID mismatch");
    const delegate = await this.cs.delegation("base", payer);
    if (delegate && delegate.toLowerCase() !== SIMPLE_7702_ACCOUNT.toLowerCase()) throw new NearPublicError("payer has an unsupported EIP-7702 delegate; nothing was signed");
    const balance = await rpc.readContract({ address: getAddress(BASE_USDC), abi: USDC_ABI, functionName: "balanceOf", args: [payer] });
    if (balance < BigInt(amount)) throw new NearPublicError("insufficient USDC on the NEAR-derived Base address; fund it with omni_transfer first");
    return delegate;
  }
  private signTransaction(digest: Hex): NormalizedNearTransaction {
    return { receiverId: this.accounts.config.mpcContract, actions: [{ type: "function_call", method: "sign", args_base64: Buffer.from(JSON.stringify({ request: { path: DERIVATION_PATH, payload_v2: { Ecdsa: digest.slice(2) }, domain_id: 0 } })).toString("base64"), gas: MPC_SIGN_GAS.toString(), deposit: "1" }] };
  }
  private mainnet() { if (this.accounts.config.network !== "mainnet") throw new NearPublicError("NEAR x402 payments require NEAR mainnet and Base mainnet"); }
  private async finish(row: NearPayment, status: PaymentState, result: Record<string, unknown>) {
    row.plan.request = null;
    return this.public(await this.store.update(row.userId, row.id, status, row.plan, { ...row.result, ...result }));
  }
  private public(row: NearPayment, extra: Record<string, unknown> = {}): Record<string, unknown> {
    return { preview_id: row.id, payment_id: row.id, status: row.status, network: BASE_NETWORK, scheme: "exact", near_account_id: row.plan.accountId, payer_address: row.plan.payer,
      authorized_amount_atomic: row.amount, ...(row.plan.authorization ? { authorization_valid_before_unix: row.plan.authorization.validBefore } : {}), purpose: row.purpose, ...row.result, ...extra };
  }
}
