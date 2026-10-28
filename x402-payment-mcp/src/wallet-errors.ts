// Provider exceptions can embed authenticated RPC URLs or request bodies. Only
// our fixed, credential-free diagnostics may cross the MCP boundary.
const publicMessages = new Set([
  "Original nonce proof is unavailable; legacy CDP operation cannot be safely cancelled by this tool",
  "Original nonce has changed; reconcile transaction_status before cancellation",
  "cancellation target is no longer eligible", "cancellation preview not found for this user",
  "another unresolved operation prevents cancellation", "cancellation target proof mismatch",
  "cancellation preview binding mismatch", "unsupported cancellation nonce or EntryPoint",
  "UserOperation encryption key is not configured", "Bundler is not configured",
  "Bundler does not support this EntryPoint", "CDP smart account factory derivation mismatch",
  "Smart account owner or EntryPoint mismatch",
  "network fee exceeds the approved maximum; prepare and confirm a new operation",
  "insufficient ETH for value and network fee; nothing was signed",
  "preview has no approved network fee maximum; prepare a new operation",

  "operation type does not match this execution tool",
  "swap tokens must be distinct nonzero token addresses or the native ETH sentinel",
  "CDP swap terms do not match the requested tokens and amount",
  "CDP returned invalid swap output amounts", "CDP quote exceeds the approved slippage tolerance",
  "insufficient balance for this swap", "CDP swap simulation is incomplete; no signing is allowed",
  "unexpected swap allowance spender", "CDP quote network mismatch",
  "fresh swap quote is below the confirmed minimum; preview and approve again",
  "Permit2 approval is required before this swap; use transaction_prepare for the exact approval",
  "CDP returned an invalid swap transaction", "swap transaction native value does not match approved input",
  "native ETH swaps must not request Permit2 signatures", "ERC-20 swap is missing its bounded Permit2 authorization",
  "swap Permit2 domain or type is invalid", "swap Permit2 token or amount differs from approved input",
  "swap Permit2 spender or deadline is invalid", "no swap liquidity is available for these tokens and amount",
  "swap preview no longer matches this wallet and terms",
  "RPC chain ID mismatch", "base RPC is not configured", "ethereum RPC is not configured",
  "smart wallet registry mismatch", "smart account does not match wallet registry",
  "operation not found for this user", "preview already consumed; check transaction_status, never submit it again",
  "an unresolved operation exists on this network; reconcile it before another execution",
  "preview expired; prepare a new operation", "operation is no longer available for signing",
  "preview no longer matches this wallet and calls",
  "simulated asset changes differ from preview; prepare and confirm a new operation",
  "calldata target has no contract code on the selected network",
  "batch simulation reverted; nothing was signed",
  "zero address, wallet self-calls and internal owner calls are not allowed",
  "ABI numeric arguments must be safe integers; use strings for token amounts",
  "transaction input is too large", "encoded calldata is too large", "read input too large",
]);
export function publicWalletError(error: unknown): Error {
  const message = error instanceof Error ? error.message : "";
  return new Error(publicMessages.has(message) ? message : "Wallet request could not be completed. Check network, ABI and parameters; use transaction_status for any existing execution. Provider details are withheld.");
}

// Preserve useful failure categories without copying provider messages, URLs,
// request bodies, signatures, headers or nested causes into logs or the ledger.
export function walletErrorDiagnostic(error: unknown) {
  const e = error instanceof Error ? error as Error & { statusCode?: unknown; errorType?: unknown; correlationId?: unknown; errorMessage?: unknown } : null;
  const api = e?.name === "APIError" || e?.name === "NetworkError";
  const types = new Set(["invalid_request", "invalid_signature", "malformed_transaction", "policy_violation", "forbidden", "unauthorized", "not_found", "rate_limit_exceeded", "idempotency_error", "internal_server_error", "bad_gateway", "service_unavailable", "timed_out", "request_canceled", "insufficient_funds"]);
  const message = e ? `${e.message} ${typeof e.errorMessage === "string" ? e.errorMessage : ""}` : "";
  const category = /AA21|AA31|didn.t pay prefund|insufficient (?:funds|balance)/i.test(message) ? "insufficient_funds"
    : /signature.*expired|SignatureExpired/i.test(message) ? "signature_expired"
    : /simulation.*revert|execution reverted/i.test(message) ? "simulation_reverted" : "other";
  return {
    error_type: api && typeof e.errorType === "string" && types.has(e.errorType) ? e.errorType : "unexpected_error",
    category,
    ...(api && typeof e.statusCode === "number" && Number.isInteger(e.statusCode) && e.statusCode >= 0 && e.statusCode <= 599 ? { status_code: e.statusCode } : {}),
    ...(api && typeof e.correlationId === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(e.correlationId) ? { correlation_id: e.correlationId } : {}),
  };
}
