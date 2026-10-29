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

// For every token the fresh delta is no worse for the wallet: outflows may
// not grow, inflows may not shrink. A token the preview did not show fails; a
// previewed token missing now counts as 0, so it passes only with a 0 floor
// (leftover change the user accepted may vanish). Malformed data never passes.
// floors: a received token's approved minimum (a route's on-chain minimum, the
// tolerance below the simulation, or the user's minimum_received) replaces the
// simulated amount, as a swap's amountOutMinimum does; every other token keeps
// the strict comparison.
export function assetChangesWithinPreview(preview: unknown, fresh: unknown, floors: Record<string, bigint> = {}): boolean {
  return assetChangeMismatch(preview, fresh, floors) === null;
}

// null when within the preview; otherwise the first token that is worse, so
// the user sees which amount moved instead of a bare refusal.
export function assetChangeMismatch(preview: unknown, fresh: unknown, floors: Record<string, bigint> = {}): string | null {
  const approved = deltas(preview), current = deltas(fresh);
  if (!approved || !current) return "simulated asset changes differ from preview; prepare and confirm a new operation";
  for (const token of current.keys()) if (!approved.has(token)) return `simulated asset changes differ from preview (${token}: previewed none, now ${current.get(token)}); prepare and confirm a new operation`;
  for (const [token, diff] of approved) {
    const now = current.get(token) ?? 0n;
    const floor = floors[token];
    const minimum = floor !== undefined && floor >= 0n && floor <= diff ? floor : diff;
    if (now < minimum) return `simulated asset changes differ from preview (${token}: previewed ${diff}, minimum ${minimum}, now ${now}); prepare and confirm a new operation`;
  }
  return null;
}
