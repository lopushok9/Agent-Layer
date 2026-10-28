import { buildApprovedNamespaces, getSdkError, parseUri } from "@walletconnect/utils";
import type { ProposalTypes, SessionTypes, Verify } from "@walletconnect/types";
import { getAddress, hexToBigInt, isAddress, isAddressEqual, isHex, numberToHex, type Address, type Hex } from "viem";
import type { DappApp, DappRequest, DappSession, DappStore, DappVerification } from "./dapp-store.js";
import type { SignatureService } from "./signatures.js";
import type { SmartWalletService } from "./smart-wallet.js";
import { chainIds, type WalletNetwork } from "./transaction-builder.js";
import type { TransactionService } from "./transactions.js";

// The subset of @reown/walletkit this service uses; WalletKit satisfies it.
type RpcResponse = { id: number; jsonrpc: "2.0"; result: unknown } | { id: number; jsonrpc: "2.0"; error: { code: number; message: string } };
export type DappClient = {
  pair(p: { uri: string }): Promise<unknown>;
  approveSession(p: { id: number; namespaces: SessionTypes.Namespaces }): Promise<SessionTypes.Struct>;
  rejectSession(p: { id: number; reason: { code: number; message: string } }): Promise<unknown>;
  respondSessionRequest(p: { topic: string; response: RpcResponse }): Promise<unknown>;
  disconnectSession(p: { topic: string; reason: { code: number; message: string } }): Promise<unknown>;
  on(event: string, listener: (args: any) => unknown): unknown;
};
type Proposal = { id: number; params: ProposalTypes.Struct; verifyContext?: Verify.Context };
type SessionRequest = { id: number; topic: string; params: { chainId: string; request: { method: string; params: unknown; expiryTimestamp?: number } }; verifyContext?: Verify.Context };

const CHAINS: Record<string, WalletNetwork> = { "eip155:8453": "base", "eip155:1": "ethereum" };
// Methods a smart account can honour. eth_sign (raw hash) and eth_signTransaction
// / eth_sendRawTransaction (EOA-only) are left out, so dApps fall back or fail early.
const METHODS = ["eth_sendTransaction", "wallet_sendCalls", "wallet_getCallsStatus", "wallet_getCapabilities", "personal_sign", "eth_signTypedData_v4", "eth_chainId", "eth_accounts", "wallet_switchEthereumChain"];
const EVENTS = ["accountsChanged", "chainChanged"];
const PROPOSAL_WAIT_MS = 20_000, DEFAULT_REQUEST_TTL_S = 300, SEND_TX_WAIT_MS = 30_000;
// EIP-1193 / EIP-5792 error codes.
const E = { rejected: 4001, unauthorized: 4100, unsupported: 4200, chain: 4901, unknownChain: 4902, params: -32602, internal: -32603, capability: 5700, unknownBundle: 5730 } as const;

type Backend = Pick<SmartWalletService, "account" | "rpc">;
type Transactions = Pick<TransactionService, "prepare" | "execute" | "status">;
type Signatures = Pick<SignatureService, "prepare" | "execute">;

// A hosted wallet joining dApps over WalletConnect, modelled on Fireblocks'
// Web3 Connections API: the user hands over a wc: URI, sees the dApp's metadata
// and WalletConnect Verify result, and accepts the connection explicitly.
// Every request the dApp sends then becomes an ordinary preview that needs the
// same confirmation as a request the agent built itself.
export class DappService {
  private waiting = new Map<string, { userId: string; resolve: (p: Record<string, unknown>) => void; reject: (e: Error) => void }>();
  constructor(private client: DappClient, private store: DappStore, private wallets: Backend, private transactions: Transactions, private signatures: Signatures, private wait = (ms: number) => new Promise(r => setTimeout(r, ms))) {
    client.on("session_proposal", (p: Proposal) => this.onProposal(p).catch(e => log("dapp_proposal_failed", e)));
    client.on("session_request", (r: SessionRequest) => this.onRequest(r).catch(e => log("dapp_request_failed", e)));
    client.on("session_delete", ({ topic }: { topic: string }) => this.store.endSession(topic).catch(e => log("dapp_session_delete_failed", e)));
  }

  async connect(userId: string, uri: string) {
    const parsed = (() => { try { return parseUri(uri); } catch { return null; } })();
    if (!parsed || !/^wc:/.test(uri) || parsed.version !== 2 || !/^[0-9a-f]{64}$/.test(parsed.topic) || !parsed.symKey) throw new Error("not a WalletConnect v2 pairing URI");
    if (this.waiting.has(parsed.topic)) throw new Error("this pairing URI is already being connected");
    const proposal = new Promise<Record<string, unknown>>((resolve, reject) => {
      const timer = setTimeout(() => { this.waiting.delete(parsed.topic); reject(new Error("the app sent no connection proposal; create a new WalletConnect URI in the app")); }, PROPOSAL_WAIT_MS);
      this.waiting.set(parsed.topic, { userId, resolve: v => { clearTimeout(timer); resolve(v); }, reject: e => { clearTimeout(timer); reject(e); } });
    });
    try { await this.client.pair({ uri }); } catch (e) { this.waiting.get(parsed.topic)?.reject(e instanceof Error ? e : new Error(String(e))); this.waiting.delete(parsed.topic); }
    return proposal;
  }

  private async onProposal(p: Proposal) {
    const waiter = this.waiting.get(p.params.pairingTopic);
    this.waiting.delete(p.params.pairingTopic);
    if (!waiter) return void await this.client.rejectSession({ id: p.id, reason: getSdkError("USER_REJECTED") });
    const verification = verified(p.verifyContext);
    // Reown's Verify API: isScam is a known-malicious domain, INVALID means the
    // metadata URL is not the origin the request really came from (impersonation).
    if (verification.is_scam || verification.validation === "INVALID") {
      await this.client.rejectSession({ id: p.id, reason: getSdkError("USER_REJECTED") });
      return waiter.reject(new Error(verification.is_scam ? "WalletConnect Verify lists this app as a known scam; connection refused" : "WalletConnect Verify: the app's claimed domain does not match where it runs; connection refused"));
    }
    const expiresAt = new Date((p.params.expiryTimestamp ?? Math.floor(Date.now() / 1000) + 300) * 1000);
    await this.store.saveProposal({ id: String(p.id), userId: waiter.userId, pairingTopic: p.params.pairingTopic, params: p.params as unknown as Record<string, unknown>, verification, expiresAt });
    const requested = [p.params.requiredNamespaces, p.params.optionalNamespaces].flatMap(n => Object.entries(n ?? {}).flatMap(([k, v]) => v.chains ?? [k]));
    waiter.resolve({
      proposal_id: String(p.id), app: app(p.params.proposer.metadata), verification, expires_at: expiresAt.toISOString(),
      requested_chains: [...new Set(requested)], supported_chains: Object.keys(CHAINS),
      trust: "App name, description and icons are self-declared; verification.origin is what WalletConnect Verify observed.",
      next_step: "Show the app, its verified origin and validation to the user. If they want this connection, call dapp_connect_respond with approve true. Connecting shares only the smart-account address; every later request needs its own confirmation.",
    });
  }

  async respondProposal(userId: string, id: string, approve: boolean) {
    const p = await this.store.proposal(userId, id);
    if (!p) throw new Error("connection proposal not found for this user");
    if (p.status !== "pending") throw new Error("connection proposal was already answered");
    if (p.expiresAt.getTime() <= Date.now()) throw new Error("connection proposal expired; create a new WalletConnect URI in the app");
    if (!await this.store.settleProposal(userId, id, approve ? "approved" : "rejected")) throw new Error("connection proposal was already answered");
    if (!approve) { await this.client.rejectSession({ id: Number(id), reason: getSdkError("USER_REJECTED") }); return { proposal_id: id, status: "rejected" }; }
    const address = (await this.wallets.account(userId)).address;
    let namespaces: SessionTypes.Namespaces;
    try {
      namespaces = buildApprovedNamespaces({ proposal: p.params as unknown as ProposalTypes.Struct, supportedNamespaces: { eip155: { chains: Object.keys(CHAINS), methods: METHODS, events: EVENTS, accounts: Object.keys(CHAINS).map(c => `${c}:${address}`) } } });
    } catch {
      await this.client.rejectSession({ id: Number(id), reason: getSdkError("UNSUPPORTED_CHAINS") });
      throw new Error("the app requires chains or methods this wallet does not support (Base and Ethereum smart account only); connection refused");
    }
    const session = await this.client.approveSession({ id: Number(id), namespaces });
    await this.store.saveSession({ topic: session.topic, userId, address, app: app(session.peer.metadata), verification: p.verification, expiresAt: new Date(session.expiry * 1000) });
    return { session_topic: session.topic, status: "connected", app: app(session.peer.metadata), verification: p.verification, address, chains: namespaces.eip155?.chains ?? [], expires_at: new Date(session.expiry * 1000).toISOString(), next_step: "Use the app normally. Its transaction and signature requests appear in dapp_requests; each needs dapp_request_prepare, the user's confirmation, then dapp_request_execute." };
  }

  async sessions(userId: string) {
    return { sessions: (await this.store.sessions(userId)).map(s => ({ session_topic: s.topic, app: s.app, verification: s.verification, address: s.address, expires_at: s.expiresAt.toISOString() })) };
  }

  async disconnect(userId: string, topic: string) {
    const s = await this.store.session(topic);
    if (!s || s.userId !== userId) throw new Error("app session not found for this user");
    await this.store.endSession(topic);
    await this.client.disconnectSession({ topic, reason: getSdkError("USER_DISCONNECTED") }).catch(e => log("dapp_disconnect_failed", e));
    return { session_topic: topic, status: "disconnected" };
  }

  private async onRequest(r: SessionRequest) {
    const { id, topic } = r, { method, params, expiryTimestamp } = r.params.request;
    const respond = (result: unknown) => this.client.respondSessionRequest({ topic, response: { id, jsonrpc: "2.0", result } });
    const fail = (code: number, message: string) => this.client.respondSessionRequest({ topic, response: { id, jsonrpc: "2.0", error: { code, message } } });
    const session = await this.store.session(topic);
    if (!session || session.endedAt || session.expiresAt.getTime() <= Date.now()) return fail(E.unauthorized, "Unauthorized");
    if (verified(r.verifyContext).is_scam) return fail(E.unauthorized, "Request origin is flagged by WalletConnect Verify");
    const network = CHAINS[r.params.chainId];
    if (!network) return fail(E.chain, "Unsupported chain");
    const hexChain = numberToHex(chainIds[network]);
    try {
      switch (method) {
        case "eth_chainId": return await respond(hexChain);
        case "eth_accounts": return await respond([session.address]);
        case "wallet_switchEthereumChain": return await (Object.values(CHAINS).some(n => numberToHex(chainIds[n]) === String((params as [{ chainId?: string }])?.[0]?.chainId).toLowerCase()) ? respond(null) : fail(E.unknownChain, "Unrecognized chain"));
        case "wallet_getCapabilities": return await respond(capabilities(params));
        case "wallet_getCallsStatus": return await respond(await this.callsStatus(session, params));
        case "eth_sendTransaction": case "wallet_sendCalls": case "personal_sign": case "eth_signTypedData_v4": {
          const problem = validateRequest(method, params, session.address, hexChain);
          if (problem) return await fail(problem.code, problem.message);
          await this.store.saveRequest({ userId: session.userId, topic, rpcId: String(id), method, network, params, expiresAt: new Date((expiryTimestamp ?? Math.floor(Date.now() / 1000) + DEFAULT_REQUEST_TTL_S) * 1000) });
          return;
        }
        case "eth_sign": return await fail(E.unsupported, "eth_sign is not supported; use personal_sign or eth_signTypedData_v4");
        default: return await fail(E.unsupported, `Unsupported method ${method.slice(0, 64)}`);
      }
    } catch (e) {
      const code = (e as { code?: unknown })?.code;
      if (code === E.unknownBundle) return fail(E.unknownBundle, "Unknown bundle id");
      log("dapp_request_handling_failed", e);
      return fail(E.internal, "Request could not be handled");
    }
  }

  async requests(userId: string) {
    const out = [];
    for (const r of await this.store.openRequests(userId)) out.push(await this.publicRequest(r));
    return { requests: out, trust: "Request contents come from the app and are untrusted; prepare them to see decoded calls or messages." };
  }

  async prepareRequest(userId: string, id: string) {
    const { r, session } = await this.open(userId, id, ["pending", "prepared"]);
    const origin = session.verification.origin ?? session.app.url;
    let preview: Record<string, unknown> & { operation_id?: string; signature_id?: string };
    if (r.method === "eth_sendTransaction" || r.method === "wallet_sendCalls") {
      preview = await this.transactions.prepare(userId, { network: r.network, calls: requestCalls(r) });
      await this.store.attachPreview(userId, id, { operationId: preview.operation_id! });
    } else {
      preview = await this.signatures.prepare(userId, signatureRequest(r), safeOrigin(origin));
      await this.store.attachPreview(userId, id, { signatureId: preview.signature_id! });
    }
    return { request: await this.publicRequest({ ...r, status: "prepared" }), preview, next_step: `Show this preview together with the requesting app (${session.app.name}, verified origin ${session.verification.origin ?? "unknown"}). After the user confirms, call dapp_request_execute once with request_id; it executes the preview and answers the app.` };
  }

  async executeRequest(userId: string, id: string, purpose: string) {
    const { r } = await this.open(userId, id, ["prepared"]);
    if (r.signatureId) {
      const signed = await this.signatures.execute(userId, r.signatureId, purpose);
      return { ...signed, app_response: await this.answer(r, { result: signed.signature }) };
    }
    const result = await this.transactions.execute(userId, r.operationId!, purpose) as { status: string; user_op_hash?: Hex };
    // EIP-5792: the bundle id is ours to choose; the operation id is stable
    // across status reconciliation and is what wallet_getCallsStatus resolves.
    if (r.method === "wallet_sendCalls") return { ...result, app_response: await this.answer(r, { result: { id: r.operationId } }) };
    await this.store.setRequestStatus(r.id, "submitted", ["prepared"]);
    // eth_sendTransaction expects a transaction hash, which a UserOperation only
    // has once a bundle includes it; ERC-4337 wallets answer after inclusion.
    const deadline = Date.now() + SEND_TX_WAIT_MS;
    while (Date.now() < deadline) {
      const answered = await this.answerSendTransaction(userId, { ...r, status: "submitted" });
      if (answered) return { ...result, app_response: answered };
      await this.wait(3_000);
    }
    return { ...result, app_response: "pending", next_step: "The operation was submitted but is not yet included. Call dapp_request_status to answer the app once it is; never execute it again." };
  }

  async requestStatus(userId: string, id: string) {
    const r = await this.store.request(userId, id);
    if (!r) throw new Error("app request not found for this user");
    const app_response = r.status === "submitted" ? await this.answerSendTransaction(userId, r) ?? "pending" : r.status;
    return { request: await this.publicRequest((await this.store.request(userId, id))!), app_response };
  }

  async rejectRequest(userId: string, id: string) {
    const { r } = await this.open(userId, id, ["pending", "prepared"]);
    return { request_id: id, app_response: await this.answer(r, { error: { code: E.rejected, message: "User rejected the request" } }, "rejected") };
  }

  private async answerSendTransaction(userId: string, r: DappRequest) {
    const s = await this.transactions.status(userId, r.operationId!) as { status: string; transaction_hash?: Hex | null };
    if (s.status === "confirmed" && s.transaction_hash) return this.answer(r, { result: s.transaction_hash });
    if (s.status === "failed" || s.status === "cancelled") return this.answer(r, { error: { code: E.internal, message: s.transaction_hash ? `UserOperation reverted in ${s.transaction_hash}` : "Transaction was not executed" } });
    return null;
  }

  private async answer(r: DappRequest, body: { result: unknown } | { error: { code: number; message: string } }, status: "responded" | "rejected" = "responded") {
    if (!await this.store.setRequestStatus(r.id, status, ["pending", "prepared", "submitted"])) return "already_answered";
    try {
      await this.client.respondSessionRequest({ topic: r.topic, response: { id: Number(r.rpcId), jsonrpc: "2.0", ...body } as RpcResponse });
      return "sent";
    } catch (e) {
      log("dapp_response_failed", e);
      await this.store.setRequestStatus(r.id, status, [status], "the app no longer accepted the response (request expired or session closed)");
      return "app_unreachable";
    }
  }

  private async open(userId: string, id: string, states: DappRequest["status"][]) {
    const r = await this.store.request(userId, id);
    if (!r) throw new Error("app request not found for this user");
    if (!states.includes(r.status)) throw new Error(`app request is ${r.status}`);
    if (r.status !== "submitted" && r.expiresAt && r.expiresAt.getTime() <= Date.now()) {
      await this.store.setRequestStatus(r.id, "expired", ["pending", "prepared"]);
      throw new Error("the app's request expired; repeat the action in the app");
    }
    const session = await this.store.session(r.topic);
    if (!session || session.userId !== userId || session.endedAt) throw new Error("the app session has ended");
    return { r, session };
  }

  private async callsStatus(session: DappSession, params: unknown) {
    const id = (params as [unknown])?.[0];
    const r = typeof id === "string" ? await this.store.requestByOperation(session.userId, id).catch(() => null) : null;
    if (!r || r.topic !== session.topic || r.method !== "wallet_sendCalls") throw Object.assign(new Error("Unknown bundle id"), { code: E.unknownBundle });
    const s = await this.transactions.status(session.userId, r.operationId!) as { status: string; transaction_hash?: Hex | null };
    const code = s.status === "confirmed" ? 200 : s.status === "failed" ? (s.transaction_hash ? 500 : 400) : s.status === "cancelled" ? 400 : 100;
    let receipts: unknown[] | undefined;
    if ((code === 200 || code === 500) && s.transaction_hash) {
      const t = await this.wallets.rpc(r.network).getTransactionReceipt({ hash: s.transaction_hash });
      receipts = [{ logs: t.logs.map(l => ({ address: l.address, data: l.data, topics: l.topics })), status: code === 200 ? "0x1" : "0x0", blockHash: t.blockHash, blockNumber: numberToHex(t.blockNumber), gasUsed: numberToHex(t.gasUsed), transactionHash: t.transactionHash }];
    }
    return { version: "2.0.0", id, chainId: numberToHex(chainIds[r.network]), status: code, atomic: true, ...(receipts ? { receipts } : {}) };
  }

  private async publicRequest(r: DappRequest) {
    const session = await this.store.session(r.topic);
    return { request_id: r.id, method: r.method, network: r.network, status: r.status, app: session?.app, verification: session?.verification, received_at: r.createdAt.toISOString(), expires_at: r.expiresAt?.toISOString() ?? null, ...(r.operationId ? { operation_id: r.operationId } : {}), ...(r.signatureId ? { signature_id: r.signatureId } : {}), ...(r.error ? { error: r.error } : {}) };
  }
}

function verified(v?: Verify.Context): DappVerification {
  const x = v?.verified;
  return { validation: x?.validation === "VALID" || x?.validation === "INVALID" ? x.validation : "UNKNOWN", ...(x?.origin ? { origin: x.origin } : {}), ...(x?.isScam ? { is_scam: true } : {}) };
}
function app(m: { name?: string; url?: string; description?: string; icons?: string[] }): DappApp {
  return { name: String(m?.name ?? "unknown").slice(0, 100), url: String(m?.url ?? "").slice(0, 300), ...(m?.description ? { description: String(m.description).slice(0, 300) } : {}) };
}
function safeOrigin(origin: string | undefined) { try { return origin ? new URL(origin).origin : undefined; } catch { return undefined; } }
function log(event: string, e: unknown) { console.error(JSON.stringify({ level: "error", event, message: e instanceof Error ? e.message : String(e) })); }

// EIP-5792 v2: atomic batches are native to a smart account (one executeBatch).
function capabilities(params: unknown) {
  const wanted = (params as [unknown, string[]?])?.[1];
  return Object.fromEntries(Object.values(CHAINS).map(n => numberToHex(chainIds[n])).filter(c => !Array.isArray(wanted) || wanted.map(w => String(w).toLowerCase()).includes(c)).map(c => [c, { atomic: { status: "supported" } }]));
}

const quantity = (v: unknown) => v === undefined || v === null ? "0" : isHex(v) ? hexToBigInt(v).toString() : null;
function validateRequest(method: string, params: unknown, address: Address, hexChain: string): { code: number; message: string } | null {
  const bad = (message: string) => ({ code: E.params, message });
  const p = Array.isArray(params) ? params : [];
  const sameAccount = (a: unknown) => typeof a === "string" && isAddress(a, { strict: false }) && isAddressEqual(getAddress(a), address);
  if (method === "eth_sendTransaction") {
    const tx = p[0] as Record<string, unknown> | undefined;
    if (!tx || (tx.from !== undefined && !sameAccount(tx.from))) return bad("from must be the connected account");
    if (typeof tx.to !== "string" || !isAddress(tx.to, { strict: false })) return { code: E.unsupported, message: "Contract deployment is not supported" };
    if (quantity(tx.value) === null || (tx.data !== undefined && !isHex(tx.data))) return bad("invalid value or data");
    return null;
  }
  if (method === "wallet_sendCalls") {
    const b = p[0] as { chainId?: string; from?: string; calls?: Record<string, unknown>[]; capabilities?: Record<string, { optional?: boolean }> } | undefined;
    if (!b || String(b.chainId).toLowerCase() !== hexChain) return bad("chainId does not match the request chain");
    if (b.from !== undefined && !sameAccount(b.from)) return bad("from must be the connected account");
    if (!Array.isArray(b.calls) || !b.calls.length || b.calls.length > 16) return { code: 5740, message: "Batch must have 1 to 16 calls" };
    if (b.calls.some(c => typeof c.to !== "string" || !isAddress(c.to, { strict: false }) || quantity(c.value) === null || (c.data !== undefined && !isHex(c.data)))) return bad("invalid call");
    const required = Object.entries(b.capabilities ?? {}).filter(([k, v]) => k !== "atomic" && v?.optional !== true).map(([k]) => k);
    if (required.length) return { code: E.capability, message: `Unsupported non-optional capability ${required[0]!.slice(0, 64)}` };
    for (const c of b.calls) if (c.capabilities && Object.values(c.capabilities as Record<string, { optional?: boolean }>).some(v => v?.optional !== true)) return { code: E.capability, message: "Unsupported non-optional call capability" };
    return null;
  }
  if (method === "personal_sign") return typeof p[0] === "string" && sameAccount(p[1]) ? null : bad("personal_sign expects [message, connected account]");
  if (method === "eth_signTypedData_v4") return sameAccount(p[0]) && (typeof p[1] === "string" || (p[1] && typeof p[1] === "object")) ? null : bad("eth_signTypedData_v4 expects [connected account, typed data]");
  return bad("unsupported method");
}

function requestCalls(r: DappRequest) {
  const p = r.params as Record<string, unknown>[];
  const calls = r.method === "eth_sendTransaction" ? [p[0]!] : (p[0] as { calls: Record<string, unknown>[] }).calls;
  return calls.map(c => ({ to: getAddress(c.to as string), value: quantity(c.value)!, ...(c.data && c.data !== "0x" ? { data: c.data as Hex } : {}) }));
}
function signatureRequest(r: DappRequest) {
  const p = r.params as unknown[];
  if (r.method === "personal_sign") return isHex(p[0]) ? { network: r.network, message_hex: p[0] } : { network: r.network, message: String(p[0]) };
  const typed = typeof p[1] === "string" ? JSON.parse(p[1]) : p[1];
  return { network: r.network, typed_data: typed };
}
