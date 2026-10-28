import { decodeErrorResult, parseAbi, type Abi, type Address, type Hex } from "viem";
import { jsonValue } from "./transaction-builder.js";

// Errors common enough to name without the target's ABI: OpenZeppelin v5
// token and vault errors, which routers and vaults bubble up from the token.
const COMMON_ERRORS = parseAbi([
  "error ERC20InsufficientBalance(address sender, uint256 balance, uint256 needed)",
  "error ERC20InsufficientAllowance(address spender, uint256 allowance, uint256 needed)",
  "error ERC20InvalidSender(address sender)",
  "error ERC20InvalidReceiver(address receiver)",
  "error ERC20InvalidApprover(address approver)",
  "error ERC20InvalidSpender(address spender)",
  "error ERC4626ExceededMaxDeposit(address receiver, uint256 assets, uint256 max)",
  "error ERC4626ExceededMaxMint(address receiver, uint256 shares, uint256 max)",
  "error ERC4626ExceededMaxWithdraw(address owner, uint256 assets, uint256 max)",
  "error ERC4626ExceededMaxRedeem(address owner, uint256 shares, uint256 max)",
  "error SafeERC20FailedOperation(address token)",
]);
const PANICS: Record<string, string> = { "0x01": "assertion failed", "0x11": "arithmetic overflow or underflow", "0x12": "division by zero", "0x21": "invalid enum value", "0x22": "invalid storage byte array", "0x31": "pop on empty array", "0x32": "array index out of bounds", "0x41": "out of memory", "0x51": "call to an uninitialised function" };

// The call that reverted, kept so the caller can name a custom error with the
// target's verified ABI before the message leaves the server.
export class SimulationReverted extends Error {
  constructor(readonly index: number, readonly to: Address, readonly data: Hex) { super(revertMessage(index, to, data)); }
}

export function revertMessage(index: number, to: Address, data: Hex, abi?: Abi) {
  return `simulation reverted at call ${index} (${to}): ${revertReason(data, abi).slice(0, 500)}; nothing was signed`;
}

// Revert data is contract output: the reason string is quoted, stripped of
// control characters and cut short, and never treated as an instruction.
function revertReason(data: Hex, abi?: Abi) {
  if (!data || data === "0x") return "reverted without data (a require without a message, an empty revert or out of gas)";
  for (const candidate of [abi, COMMON_ERRORS]) {
    try {
      const e = decodeErrorResult({ abi: (candidate ?? []) as Abi, data });
      if (e.errorName === "Error") return `contract reason (untrusted text): "${clean(String(e.args?.[0] ?? ""), 200)}"`;
      if (e.errorName === "Panic") { const code = `0x${BigInt(e.args?.[0] as bigint).toString(16).padStart(2, "0")}`; return `panic ${code} (${PANICS[code] ?? "unknown panic code"})`; }
      const inputs = e.abiItem && "inputs" in e.abiItem ? e.abiItem.inputs : [];
      const args = (jsonValue(e.args ?? []) as unknown[]).map((v, i) => `${inputs[i]?.name || `arg${i}`}=${clean(typeof v === "string" ? v : JSON.stringify(v), 80)}`);
      return `${clean(e.errorName, 80)}(${args.join(", ")})`;
    } catch { /* not an error of this ABI */ }
  }
  return `custom error ${data.slice(0, 10)} (not in the contract's verified ABI; it may come from a contract this call reached)`;
}

function clean(text: string, max: number) { return text.replace(/[^\x20-\x7e]/g, "?").slice(0, max); }
