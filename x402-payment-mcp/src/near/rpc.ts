import { assertAccountId } from "./units.js";

// Minimal NEAR JSON-RPC client. The URL is deployment-owned configuration and
// never comes from MCP input. Responses are external data: shapes are checked
// before use and contract results are returned as untrusted JSON.
export type Finality = "final" | "optimistic";
export type TxWait = "NONE" | "INCLUDED" | "EXECUTED_OPTIMISTIC" | "INCLUDED_FINAL" | "EXECUTED" | "FINAL";
export type AccountView = { amount: string; locked: string; storage_usage: number; code_hash: string; block_height: number; block_hash: string };
export type AccessKeyView = { nonce: number | string; permission: "FullAccess" | { FunctionCall: { allowance: string | null; receiver_id: string; method_names: string[] } }; block_hash: string; block_height: number };

export class NearRpcError extends Error {
  constructor(message: string, readonly kind: string, readonly data?: unknown) { super(message); }
}

export class NearRpc {
  private id = 0;
  constructor(private url: string, private expectedChainId: string, private fetcher: typeof fetch = fetch, private timeoutMs = 20_000) {}

  async call<T>(method: string, params: unknown, timeoutMs = this.timeoutMs): Promise<T> {
    const response = await this.fetcher(this.url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: ++this.id, method, params }), signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) throw new NearRpcError(`NEAR RPC HTTP ${response.status}`, "HTTP_ERROR");
    const body = await response.json() as { result?: T; error?: { name?: string; cause?: { name?: string; info?: unknown }; message?: string; data?: unknown } };
    if (body.error) {
      const kind = body.error.cause?.name ?? body.error.name ?? "RPC_ERROR";
      throw new NearRpcError(`NEAR RPC ${method} failed: ${kind}${typeof body.error.data === "string" ? `: ${body.error.data.slice(0, 300)}` : ""}`, kind, body.error.cause?.info ?? body.error.data);
    }
    if (body.result === undefined) throw new NearRpcError(`NEAR RPC ${method} returned no result`, "EMPTY_RESULT");
    return body.result;
  }

  // Called before any signing path: refuses an RPC that serves another network.
  async assertNetwork(): Promise<void> {
    const status = await this.call<{ chain_id?: string }>("status", []);
    if (status.chain_id !== this.expectedChainId) throw new Error(`NEAR RPC chain_id mismatch: expected ${this.expectedChainId}`);
  }

  async viewAccount(accountId: string, finality: Finality = "final"): Promise<AccountView | null> {
    assertAccountId(accountId);
    try {
      return await this.call<AccountView>("query", { request_type: "view_account", finality, account_id: accountId });
    } catch (e) {
      if (e instanceof NearRpcError && e.kind === "UNKNOWN_ACCOUNT") return null;
      throw e;
    }
  }

  async viewAccessKey(accountId: string, publicKey: string, finality: Finality = "final"): Promise<AccessKeyView | null> {
    assertAccountId(accountId);
    try {
      return await this.call<AccessKeyView>("query", { request_type: "view_access_key", finality, account_id: accountId, public_key: publicKey });
    } catch (e) {
      if (e instanceof NearRpcError && (e.kind === "UNKNOWN_ACCESS_KEY" || e.kind === "UNKNOWN_ACCOUNT")) return null;
      throw e;
    }
  }

  async viewAccessKeyList(accountId: string): Promise<{ public_key: string; access_key: Omit<AccessKeyView, "block_hash" | "block_height"> }[]> {
    assertAccountId(accountId);
    try {
      const r = await this.call<{ keys: { public_key: string; access_key: Omit<AccessKeyView, "block_hash" | "block_height"> }[] }>("query", { request_type: "view_access_key_list", finality: "final", account_id: accountId });
      return r.keys;
    } catch (e) {
      if (e instanceof NearRpcError && e.kind === "UNKNOWN_ACCOUNT") return [];
      throw e;
    }
  }

  // View call on a contract. Args are JSON; the result is decoded as JSON when
  // possible, otherwise returned as base64. Logs are contract-controlled text.
  async callFunction(contractId: string, method: string, args: unknown, finality: Finality = "final"): Promise<{ result: unknown; raw_base64: string; logs: string[]; block_height: number }> {
    assertAccountId(contractId, "contract_id");
    const r = await this.call<{ result: number[]; logs: string[]; block_height: number }>("query", { request_type: "call_function", finality, account_id: contractId, method_name: method, args_base64: Buffer.from(JSON.stringify(args ?? {})).toString("base64") });
    const raw = Buffer.from(r.result);
    let result: unknown;
    try { result = raw.length ? JSON.parse(raw.toString("utf8")) : null; } catch { result = { base64: raw.toString("base64") }; }
    return { result, raw_base64: raw.toString("base64"), logs: r.logs ?? [], block_height: r.block_height };
  }

  async finalBlock(): Promise<{ hash: string; height: number }> {
    const b = await this.call<{ header: { hash: string; height: number } }>("block", { finality: "final" });
    return { hash: b.header.hash, height: b.header.height };
  }

  // send_tx with an explicit wait level; the signed transaction is base64 borsh.
  async sendTransaction(signedBase64: string, waitUntil: TxWait, timeoutMs = 60_000): Promise<TxOutcome> {
    return this.call<TxOutcome>("send_tx", { signed_tx_base64: signedBase64, wait_until: waitUntil }, timeoutMs);
  }

  async transactionStatus(hash: string, senderId: string, waitUntil: TxWait = "NONE"): Promise<TxOutcome> {
    return this.call<TxOutcome>("EXPERIMENTAL_tx_status", { tx_hash: hash, sender_account_id: senderId, wait_until: waitUntil });
  }
}

export type ExecutionStatus = { SuccessValue?: string; SuccessReceiptId?: string; Failure?: unknown; Unknown?: unknown } | "Unknown" | "Pending";
export type ExecutionOutcome = { id: string; outcome: { logs: string[]; receipt_ids: string[]; gas_burnt: number; tokens_burnt: string; executor_id: string; status: ExecutionStatus } };
export type TxOutcome = {
  final_execution_status?: TxWait;
  status?: { SuccessValue?: string; Failure?: unknown } | "NotStarted" | "Started";
  transaction?: { hash: string; signer_id: string; receiver_id: string };
  transaction_outcome?: ExecutionOutcome;
  receipts_outcome?: ExecutionOutcome[];
};

// Summarises a transaction outcome. A transaction whose own status succeeded
// can still contain failed receipts (e.g. a failed cross-contract promise), so
// every receipt failure is reported separately and never hidden.
export function summarizeOutcome(o: TxOutcome) {
  const receipts = (o.receipts_outcome ?? []).map(r => ({ receipt_id: r.id, executor_id: r.outcome.executor_id, status: receiptStatus(r.outcome.status), gas_burnt: String(r.outcome.gas_burnt), tokens_burnt: r.outcome.tokens_burnt, logs: r.outcome.logs }));
  const failedReceipts = receipts.filter(r => r.status.kind === "failure");
  const status = o.status;
  let result: "success" | "failure" | "pending" = "pending";
  let returnValue: unknown = undefined;
  let failure: unknown = undefined;
  if (status && typeof status === "object") {
    if ("Failure" in status && status.Failure !== undefined) { result = "failure"; failure = status.Failure; }
    else if ("SuccessValue" in status) { result = "success"; returnValue = decodeValue(status.SuccessValue ?? ""); }
  }
  const tokensBurnt = [o.transaction_outcome, ...(o.receipts_outcome ?? [])].reduce((n, x) => n + BigInt(x?.outcome.tokens_burnt ?? "0"), 0n);
  return { result, final_execution_status: o.final_execution_status ?? null, return_value: returnValue, failure, failed_receipts: failedReceipts.length, receipts, tokens_burnt_yocto: tokensBurnt.toString() };
}

function receiptStatus(s: ExecutionStatus): { kind: "success" | "failure" | "pending"; value?: unknown; failure?: unknown } {
  if (typeof s === "string") return { kind: "pending" };
  if (s.Failure !== undefined) return { kind: "failure", failure: s.Failure };
  if (s.SuccessValue !== undefined) return { kind: "success", value: decodeValue(s.SuccessValue) };
  if (s.SuccessReceiptId !== undefined) return { kind: "success", value: { receipt: s.SuccessReceiptId } };
  return { kind: "pending" };
}

export function decodeValue(b64: string): unknown {
  if (!b64) return null;
  const raw = Buffer.from(b64, "base64");
  try { return JSON.parse(raw.toString("utf8")); } catch { return { base64: b64 }; }
}
