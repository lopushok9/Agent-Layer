import { createHash } from "node:crypto";
import { decodeFunctionData, encodeFunctionData, erc20Abi, getAddress, isAddress, maxUint256, zeroAddress, type Abi, type Address, type Hex } from "viem";
import { z } from "zod";
import type { AbiSource, ClearSigning, ContractMetadata } from "./contract-metadata.js";

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
  if (encoded && (!v.function_name || v.data !== undefined)) ctx.addIssue({ code: "custom", message: "provide function_name (+ args, + abi to override the verified one), or data, not both" });
});
export const transactionInput = z.strictObject({
  network: walletNetwork,
  calls: z.array(callInput).min(1).max(16),
  received_tolerance_bps: z.number().int().min(0).max(500).default(50).describe("How far below the simulated amount a received token may fall at execution, in bps (vault shares and interest-bearing tokens change every block). Outgoing amounts never tolerate any increase."),
});
export type TransactionInput = z.input<typeof transactionInput>;
export type NormalizedCall = { to: Address; value: string; data: Hex };
export type CallDescription = { index: number; to: Address; value_wei: string; data: Hex; function?: string; arguments?: unknown; abi_source: "caller_supplied_unverified" | "standard_erc20" | "unknown" | "internal_verified" | AbiSource; implementation?: Address; clear_signing?: ClearSigning; warnings: string[] };

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
    if (c.function_name && !c.abi) throw new Error(`no verified ABI is available for ${to}; pass abi with function_name`);
    const data = (c.abi ? encodeFunctionData({ abi: c.abi as Abi, functionName: c.function_name!, args: c.args ?? [] }) : c.data ?? "0x") as Hex;
    if (data.length > 131074) throw new Error("encoded calldata is too large");
    const warnings = ["Contract safety and economic intent are not proven by its ABI or simulation."];
    let decoded: { functionName: string; args?: readonly unknown[] | undefined } | undefined;
    let source: CallDescription["abi_source"] = c.abi ? "caller_supplied_unverified" : "unknown";
    try { decoded = decodeFunctionData({ abi: (c.abi as Abi | undefined) ?? erc20Abi, data }); if (!c.abi) source = "standard_erc20"; } catch { /* opaque calldata remains usable, explicitly labelled */ }
    if (!decoded && data !== "0x") warnings.push(OPAQUE);
    warnings.push(...functionWarnings(decoded?.functionName));
    descriptions.push({ index, to, value_wei: c.value, data, ...(decoded ? { function: decoded.functionName, arguments: jsonValue(decoded.args) } : {}), abi_source: source, warnings });
    return { to, value: c.value, data };
  });
  return { network: parsed.network, chainId: chainIds[parsed.network], account: getAddress(account), calls, descriptions };
}

const OPAQUE = "Opaque calldata: financial effects are unknown; review the raw bytes.";
const FUNCTION_WARNINGS: Record<string, string> = {
  approve: "Changes a spender allowance; it can remain after this transaction.",
  setApprovalForAll: "May grant an operator control of all tokens in this collection.",
};
const functionWarnings = (name?: string) => name && FUNCTION_WARNINGS[name] ? [FUNCTION_WARNINGS[name]] : [];

// A call given only function_name (+ args) is encoded with the target's
// verified ABI, so an agent never pastes ABI fragments it may get wrong. Only
// that function's entries are kept (overloads included); a guessed
// selector-only ABI is refused because it does not carry argument types.
export async function withVerifiedAbis(input: TransactionInput, metadata?: ContractMetadata | null): Promise<TransactionInput> {
  const network = walletNetwork.safeParse(input.network);
  if (!network.success || !metadata || !Array.isArray(input.calls)) return input;
  const calls = await Promise.all(input.calls.map(async c => {
    if (c.abi !== undefined || !c.function_name || c.data !== undefined || !isAddress(c.to, { strict: false })) return c;
    const resolved = await metadata.contract(network.data, getAddress(c.to));
    if (!resolved || resolved.source === "bytecode_selectors") throw new Error(`no verified ABI is available for ${getAddress(c.to)}; pass abi with function_name`);
    const abi = resolved.abi.filter(e => e.type === "function" && e.name === c.function_name);
    if (!abi.length) throw new Error(`${getAddress(c.to)} has no function ${c.function_name} in its verified ABI${resolved.implementation ? " (behind its proxy)" : ""}`);
    return { ...c, abi: abi as unknown[] };
  }));
  return { ...input, calls };
}

// Decode each call against the ABI the chain's verification services hold for
// the target (behind any proxy), as Safe's Transaction Builder and Rabby do,
// instead of trusting the ABI the agent supplied, and attach the ERC-7730
// registry display when one exists. Only labels change: the calldata and the
// fingerprint stay exactly what normalizeTransaction produced.
export async function annotateCalls(network: WalletNetwork, account: Address, calls: NormalizedCall[], descriptions: CallDescription[], metadata: ContractMetadata): Promise<CallDescription[]> {
  return Promise.all(descriptions.map(async d => {
    const call = calls[d.index]!;
    if (call.data === "0x") return d;
    const [resolved, clear] = await Promise.all([metadata.contract(network, call.to), metadata.describeCall(network, call, account)]);
    const next: CallDescription = { ...d, warnings: [...d.warnings] };
    if (resolved) {
      if (resolved.implementation) { next.implementation = resolved.implementation; next.warnings.push(`Proxy contract: this call runs implementation ${resolved.implementation}, which an upgradeable proxy's admin can replace after this preview.`); }
      let decoded: { functionName: string; args?: readonly unknown[] | undefined } | undefined;
      try { decoded = decodeFunctionData({ abi: resolved.abi, data: call.data }); } catch { /* not a function of this ABI */ }
      const verified = resolved.source !== "bytecode_selectors";
      if (decoded && (verified || !d.function)) {
        const args = jsonValue(decoded.args);
        if (d.abi_source === "caller_supplied_unverified" && (decoded.functionName !== d.function || JSON.stringify(args) !== JSON.stringify(d.arguments))) next.warnings.push(`The supplied ABI described this call as ${d.function ?? "unknown"}; the ${verified ? "verified" : "guessed"} ABI decodes it as ${decoded.functionName}. Trust the verified decoding.`);
        next.warnings = next.warnings.filter(w => w !== OPAQUE && !Object.values(FUNCTION_WARNINGS).includes(w));
        next.warnings.push(...functionWarnings(decoded.functionName));
        Object.assign(next, { function: decoded.functionName, arguments: args, abi_source: resolved.source });
        if (!verified) next.warnings.push("Function name guessed from public selector databases (no verified source); different functions can share a selector.");
      } else if (verified && !decoded) next.warnings.push("Calldata matches no function in the contract's verified ABI.");
    }
    if (clear) next.clear_signing = clear;
    return next;
  }));
}

// Hash only execution-relevant canonical fields, never untrusted labels/ABI prose.
export function transactionFingerprint(network: WalletNetwork, account: Address, calls: NormalizedCall[]) {
  return createHash("sha256").update(JSON.stringify({ version: 1, chainId: chainIds[network], account: account.toLowerCase(), calls: calls.map(c => ({ to: c.to.toLowerCase(), value: BigInt(c.value).toString(), data: c.data.toLowerCase() })) })).digest("hex");
}

export function jsonValue(value: unknown): unknown { return JSON.parse(JSON.stringify(value, (_key, v) => typeof v === "bigint" ? v.toString() : v) ?? "null"); }
