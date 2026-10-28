// viem simulateCalls({ traceAssetChanges }) reports { token, value: { pre, post, diff } }.
// pre/post are absolute balances: any unrelated transfer or x402 payment between
// preview and execution moves them. The user approved the per-token delta only.
type Deltas = Map<string, bigint>;

function deltas(changes: unknown): Deltas | null {
  if (changes === undefined || changes === null) return new Map();
  if (!Array.isArray(changes)) return null;
  const result: Deltas = new Map();
  for (const change of changes) {
    const token = (change as { token?: { address?: unknown } })?.token?.address;
    const diff = (change as { value?: { diff?: unknown } })?.value?.diff;
    if (typeof token !== "string" || !/^-?\d+$/.test(String(diff))) return null;
    const key = token.toLowerCase();
    if (result.has(key)) return null;
    result.set(key, BigInt(String(diff)));
  }
  return result;
}

// Same token set, and for every token the fresh delta is no worse for the wallet:
// outflows may not grow, inflows may not shrink. Malformed data never passes.
// floors: a route's output token whose approved minimum (enforced on-chain by
// the route itself) replaces the simulated amount, as a swap's amountOutMinimum
// does; every other token keeps the strict comparison.
export function assetChangesWithinPreview(preview: unknown, fresh: unknown, floors: Record<string, bigint> = {}): boolean {
  const approved = deltas(preview), current = deltas(fresh);
  if (!approved || !current || approved.size !== current.size) return false;
  for (const [token, diff] of approved) {
    const now = current.get(token);
    const floor = floors[token];
    if (now === undefined || now < (floor !== undefined && floor > 0n && floor <= diff ? floor : diff)) return false;
  }
  return true;
}
