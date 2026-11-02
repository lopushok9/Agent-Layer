import { decodeAbiParameters, decodeFunctionData, encodeAbiParameters, encodeFunctionData, getAddress, parseAbi, parseAbiParameters, zeroAddress, type Address, type Hex, type PublicClient } from "viem";
import type { NormalizedCall, WalletNetwork } from "./transaction-builder.js";
import { v4PositionManagers as managers, v4ModifyAbi as modifyAbi, v4Commands as commands, v4BurnParams as burnParams, v4TakeParams as takeParams } from "./uniswap-v4-constants.js";

const eth = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
const abi = parseAbi(["function modifyLiquidities(bytes unlockData,uint256 deadline) payable", "function getPoolAndPositionInfo(uint256 tokenId) view returns ((address currency0,address currency1,uint24 fee,int24 tickSpacing,address hooks) poolKey,bytes32 info)"]);
const decreaseParams = parseAbiParameters("uint256,uint256,uint128,uint128,bytes");
const max128 = (1n << 128n) - 1n;

// Support only a single, self-contained burn followed by TAKE_PAIR to the wallet.
// Aggregated batch inflows cannot safely be attributed to a particular position.
export function v4BurnCandidate(network: WalletNetwork, account: Address, calls: NormalizedCall[]) {
  if (calls.length !== 1) return null;
  const call = calls[0]!;
  if (call.to.toLowerCase() !== managers[network] || call.value !== "0") return null;
  try {
    const { args: [unlock, deadline] } = decodeFunctionData({ abi: modifyAbi, data: call.data });
    const [codes, params] = decodeAbiParameters(commands, unlock);
    if (codes.toLowerCase() !== "0x0311" || params.length !== 2) return null;
    const [id, min0, min1, hookData] = decodeAbiParameters(burnParams, params[0]!);
    const [currency0, currency1, recipient] = decodeAbiParameters(takeParams, params[1]!);
    if (recipient.toLowerCase() !== account.toLowerCase() || currency0.toLowerCase() === currency1.toLowerCase()) return null;
    return { call, id, min0, min1, hookData, currency0: getAddress(currency0), currency1: getAddress(currency1), deadline };
  } catch { return null; }
}

type Candidate = NonNullable<ReturnType<typeof v4BurnCandidate>>;
type Simulation = { asset_changes?: unknown; block_number?: unknown };
type Simulate = (network: WalletNetwork, account: Address, calls: NormalizedCall[], block: bigint) => Promise<Simulation>;
function amount(changes: unknown, currency: Address) {
  if (!Array.isArray(changes)) throw new Error("Cannot determine Uniswap v4 position output");
  const target = currency.toLowerCase() === zeroAddress ? eth : currency.toLowerCase();
  const matches = changes.filter((x: any) => x?.token?.address?.toLowerCase() === target);
  if (matches.length === 0) return 0n;
  if (matches.length !== 1 || !/^\d+$/.test(String(matches[0]?.value?.diff))) throw new Error("Cannot determine Uniswap v4 position output");
  return BigInt(String(matches[0].value.diff));
}
export async function protectV4Burn(network: WalletNetwork, account: Address, candidate: Candidate, initial: Simulation, bps: number, rpc: PublicClient, simulate: Simulate) {
  if (typeof initial.block_number !== "string" || !/^\d+$/.test(initial.block_number)) throw new Error("Cannot establish the Uniswap v4 simulation block");
  const block = BigInt(initial.block_number);
  const [pool] = await rpc.readContract({ address: candidate.call.to, abi, functionName: "getPoolAndPositionInfo", args: [candidate.id], blockNumber: block });
  if (pool.currency0.toLowerCase() !== candidate.currency0.toLowerCase() || pool.currency1.toLowerCase() !== candidate.currency1.toLowerCase()) throw new Error("Uniswap v4 pool currencies do not match the position");
  // Removal hooks can change deltas or behave differently for burn and zero
  // liquidity fee collection. Do not infer a principal amount for such pools.
  if ((BigInt(pool.hooks) & 0x300n) !== 0n) throw new Error("Automatic Uniswap v4 minimums do not support liquidity-removal hooks");
  const decrease = encodeAbiParameters(decreaseParams, [candidate.id, 0n, 0n, 0n, candidate.hookData]);
  const take = encodeAbiParameters(takeParams, [candidate.currency0, candidate.currency1, account]);
  const feeUnlock = encodeAbiParameters(commands, ["0x0111", [decrease, take]]);
  const feeCall: NormalizedCall = { to: candidate.call.to, value: "0", data: encodeFunctionData({ abi, functionName: "modifyLiquidities", args: [feeUnlock, candidate.deadline] }) };
  const fees = await simulate(network, account, [feeCall], block);
  if (fees.block_number !== initial.block_number) throw new Error("Uniswap v4 fee simulation block mismatch");
  const calc = (currency: Address, old: bigint) => {
    const total = amount(initial.asset_changes, currency), accrued = amount(fees.asset_changes, currency);
    if (accrued > total) throw new Error("Cannot separate Uniswap v4 principal from fees");
    const principal = total - accrued;
    if (principal > max128) throw new Error("Uniswap v4 principal exceeds uint128");
    const floor = principal * BigInt(10_000 - bps) / 10_000n;
    return { principal, accrued, minimum: old > floor ? old : floor };
  };
  const a = calc(candidate.currency0, candidate.min0), b = calc(candidate.currency1, candidate.min1);
  if (a.principal === 0n && b.principal === 0n) throw new Error("Cannot establish nonzero Uniswap v4 principal from the simulation");
  if (a.minimum > a.principal || b.minimum > b.principal) throw new Error("Uniswap v4 existing minimum exceeds simulated principal");
  const burn = encodeAbiParameters(burnParams, [candidate.id, a.minimum, b.minimum, candidate.hookData]);
  const unlock = encodeAbiParameters(commands, ["0x0311", [burn, take]]);
  const call: NormalizedCall = { ...candidate.call, data: encodeFunctionData({ abi, functionName: "modifyLiquidities", args: [unlock, candidate.deadline] }) };
  return { call, details: { type: "uniswap_v4_burn", token_id: candidate.id.toString(), simulation_block: initial.block_number, currencies: [candidate.currency0, candidate.currency1], principal: [a.principal.toString(), b.principal.toString()], accrued_fees: [a.accrued.toString(), b.accrued.toString()], minimums: [a.minimum.toString(), b.minimum.toString()], tolerance_bps: bps, note: "Minimums are enforced on-chain on principal, excluding accrued fees; a minimum of zero offers no protection for that asset, including when rounding dust. Simulations may miss nonstandard token behavior." } };
}
