import { createHash } from "node:crypto";
import { decodeFunctionData, encodeFunctionData, erc20Abi, getAddress, isAddress, maxUint256, zeroAddress, type Abi, type Address, type Hex } from "viem";
import { z } from "zod";

export const walletNetwork = z.enum(["base", "ethereum"]);
export type WalletNetwork = z.infer<typeof walletNetwork>;
export const chainIds = { base: 8453, ethereum: 1 } as const;
export const addressInput = z.string().refine(v => isAddress(v, { strict: false }), "invalid EVM address");
const atomicInput = z.string().regex(/^(0|[1-9][0-9]{0,77})$/, "use integer atomic units").refine(v => BigInt(v) <= maxUint256, "amount exceeds uint256");
const hexInput = z.string().regex(/^0x(?:[0-9a-fA-F]{2})*$/, "invalid calldata").max(131074);

export const callInput = z.strictObject({
  to: addressInput,
  value: atomicInput.default("0"),
  data: hexInput.optional(),
  abi: z.array(z.unknown()).min(1).max(200).optional(),
  function_name: z.string().min(1).max(200).optional(),
  args: z.array(z.unknown()).max(100).optional(),
}).superRefine((v, ctx) => {
  const encoded = v.abi !== undefined || v.function_name !== undefined || v.args !== undefined;
  if (encoded && (!v.abi || !v.function_name || v.data !== undefined)) ctx.addIssue({ code: "custom", message: "provide abi + function_name (+ args), or data, not both" });
});
export const transactionInput = z.strictObject({ network: walletNetwork, calls: z.array(callInput).min(1).max(16) });
export type TransactionInput = z.input<typeof transactionInput>;
export type NormalizedCall = { to: Address; value: string; data: Hex };
export type CallDescription = { index: number; to: Address; value_wei: string; data: Hex; function?: string; arguments?: unknown; abi_source: "caller_supplied_unverified" | "standard_erc20" | "unknown"; warnings: string[] };

function assertSafeNumbers(value: unknown): void {
  if (typeof value === "number" && !Number.isSafeInteger(value)) throw new Error("ABI numeric arguments must be safe integers; use strings for token amounts");
  if (Array.isArray(value)) value.forEach(assertSafeNumbers);
  else if (value && typeof value === "object") Object.values(value).forEach(assertSafeNumbers);
}

export function normalizeTransaction(input: TransactionInput, account: Address, owner?: Address) {
  if (JSON.stringify(input).length > 180_000) throw new Error("transaction input is too large");
  const parsed = transactionInput.parse(input);
  const descriptions: CallDescription[] = [];
  const calls = parsed.calls.map((c, index): NormalizedCall => {
    const to = getAddress(c.to);
    if ([zeroAddress, account, owner].some(a => a?.toLowerCase() === to.toLowerCase())) throw new Error("zero address, wallet self-calls and internal owner calls are not allowed");
    assertSafeNumbers(c.args);
    const data = (c.abi ? encodeFunctionData({ abi: c.abi as Abi, functionName: c.function_name!, args: c.args ?? [] }) : c.data ?? "0x") as Hex;
    if (data.length > 131074) throw new Error("encoded calldata is too large");
    const warnings = ["Contract safety and economic intent are not proven by its ABI or simulation."];
    let decoded: { functionName: string; args?: readonly unknown[] | undefined } | undefined;
    let source: CallDescription["abi_source"] = c.abi ? "caller_supplied_unverified" : "unknown";
    try { decoded = decodeFunctionData({ abi: (c.abi as Abi | undefined) ?? erc20Abi, data }); if (!c.abi) source = "standard_erc20"; } catch { /* opaque calldata remains usable, explicitly labelled */ }
    if (!decoded && data !== "0x") warnings.push("Opaque calldata: financial effects are unknown; review the raw bytes.");
    if (decoded?.functionName === "approve") warnings.push("Changes a spender allowance; it can remain after this transaction.");
    if (decoded?.functionName === "setApprovalForAll") warnings.push("May grant an operator control of all tokens in this collection.");
    descriptions.push({ index, to, value_wei: c.value, data, ...(decoded ? { function: decoded.functionName, arguments: jsonValue(decoded.args) } : {}), abi_source: source, warnings });
    return { to, value: c.value, data };
  });
  return { network: parsed.network, chainId: chainIds[parsed.network], account: getAddress(account), calls, descriptions };
}

// Hash only execution-relevant canonical fields, never untrusted labels/ABI prose.
export function transactionFingerprint(network: WalletNetwork, account: Address, calls: NormalizedCall[]) {
  return createHash("sha256").update(JSON.stringify({ version: 1, chainId: chainIds[network], account: account.toLowerCase(), calls: calls.map(c => ({ to: c.to.toLowerCase(), value: BigInt(c.value).toString(), data: c.data.toLowerCase() })) })).digest("hex");
}

export function jsonValue(value: unknown): unknown { return JSON.parse(JSON.stringify(value, (_key, v) => typeof v === "bigint" ? v.toString() : v) ?? "null"); }
