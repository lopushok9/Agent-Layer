import { decodeAbiParameters, decodeFunctionData, getCreate2Address, keccak256, parseAbiParameters, sliceHex, type Abi, type AbiParameter, type Address, type Hex } from "viem";
import type { WalletNetwork } from "./transaction-builder.js";
import { v4PositionManagers, v4ModifyAbi as posAbi, v4Commands, v4BurnParams, v4TakeParams } from "./uniswap-v4-constants.js";

const factory = "0x4e59b44847b379578588920ca78fbf26c0b4956c";
const actions: Record<number, { name: string; params: readonly AbiParameter[] }> = {
  2: { name: "mint_position", params: parseAbiParameters("(address currency0,address currency1,uint24 fee,int24 tickSpacing,address hooks),int24 tickLower,int24 tickUpper,uint256 liquidity,uint128 amount0Max,uint128 amount1Max,address recipient,bytes hookData") },
  3: { name: "burn_position", params: v4BurnParams },
  13: { name: "settle_pair", params: parseAbiParameters("address currency0,address currency1") },
  17: { name: "take_pair", params: v4TakeParams },
  20: { name: "sweep", params: parseAbiParameters("address currency,address recipient") },
};
function json(x: unknown): unknown {
  if (typeof x === "bigint") return x.toString();
  if (Array.isArray(x)) return x.map(json);
  if (x && typeof x === "object") return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, json(v)]));
  return x;
}
// Display-only: never influences the transaction, signing or safety checks.
export function inspectCall(network: WalletNetwork, to: Address, data: Hex, abi?: Abi) {
  if (to.toLowerCase() === factory && data.length >= 68) {
    const salt = sliceHex(data, 0, 32), code = sliceHex(data, 32), hash = keccak256(code);
    return { kind: "create2_factory", salt, init_code_hash: hash, predicted_address: getCreate2Address({ from: to, salt, bytecodeHash: hash }), warning: "Predicted address only; verify factory code and deployed runtime independently." };
  }
  if (to.toLowerCase() === v4PositionManagers[network]) try {
    const outer = decodeFunctionData({ abi: posAbi, data });
    const [bytes, deadline] = outer.args;
    const [codes, params] = decodeAbiParameters(v4Commands, bytes);
    const numbers = codes.slice(2).match(/.{2}/g)?.map(x => parseInt(x, 16)) ?? [];
    if (numbers.length !== params.length || numbers.length > 32) throw new Error("invalid action count");
    const decoded = numbers.map((code, i) => {
      const entry = actions[code];
      if (!entry) return { code, name: "unknown", data: params[i] };
      try {
        const values = decodeAbiParameters(entry.params, params[i]!);
        return { code, name: entry.name, parameters: json(values), parameter_names: entry.params.map((p, index) => p.name || `arg${index}`), ...(code === 3 ? { onchain_minimums: { amount0: String(values[1]), amount1: String(values[2]) }, minimum_warning: "Contract-level minimums apply to the burn output; zero permits zero. Other effects and hook behavior require separate review." } : {}) };
      }
      catch { return { code, name: "invalid", data: params[i] }; }
    });
    return { kind: "uniswap_v4_position_manager", deadline: deadline.toString(), actions: decoded, warning: "Best-effort static decoding; nested data, pool and hook behavior are not verified." };
  } catch { /* not this call, or invalid */ }
  if (abi) try {
    const outer = decodeFunctionData({ abi, data });
    if (outer.functionName !== "multicall" || !outer.args) return null;
    const list = Array.from(outer.args).find(x => Array.isArray(x) && x.every(y => typeof y === "string" && /^0x[0-9a-f]*$/i.test(y))) as Hex[] | undefined;
    if (!list || list.length > 32) return null;
    return { kind: "multicall", calls: list.map(inner => { try { const decoded = decodeFunctionData({ abi, data: inner }); return { function: decoded.functionName, arguments: json(decoded.args ?? []) }; } catch { return { function: null, data: inner }; } }), warning: "Best-effort same-contract decoding; nested targets and semantics are not verified." };
  } catch { /* invalid or unknown */ }
  return null;
}
