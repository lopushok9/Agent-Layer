// Provider exceptions can embed authenticated RPC URLs or request bodies. Only
// our fixed, credential-free diagnostics may cross the MCP boundary.
const publicMessages = new Set([
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
