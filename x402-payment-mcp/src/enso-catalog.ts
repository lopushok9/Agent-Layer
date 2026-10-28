import { getAddress, isAddress } from "viem";
import { z } from "zod";
import { ROUTER_ACTIONS, type EnsoApi } from "./enso-routes.js";
import { addressInput, chainIds, walletNetwork, type WalletNetwork } from "./transaction-builder.js";

type Standard = { protocol?: { slug?: unknown; url?: unknown }; forks?: { slug?: unknown; url?: unknown }[]; actions?: { action?: unknown; functionNames?: unknown; supportedChains?: { id?: unknown }[] }[] };
type Action = { action?: unknown; inputs?: Record<string, { type?: unknown; description?: unknown; optional?: unknown }> };
type Position = Record<string, any>;

// Inputs this wallet fills itself or never forwards (see actionInput).
const FIXED_INPUTS = new Set(["receiver", "onBehalfOf", "args", "maxAmountOut", "ensoFeeReceiver", "estimateAmountIn", "path", "salt"]);

export const catalogInput = z.strictObject({
  network: walletNetwork,
  action: z.enum(ROUTER_ACTIONS).optional(),
  protocol: z.string().min(1).max(64).optional().describe("Substring of a protocol slug, e.g. aave, morpho, aerodrome"),
  limit: z.number().int().min(1).max(300).default(100),
});
export const positionsInput = z.strictObject({
  network: walletNetwork,
  underlying_token: addressInput.optional().describe("Only positions whose underlying tokens include this token"),
  protocol: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/).optional().describe("Exact protocol slug, e.g. aave-v3"),
  min_tvl_usd: z.number().min(0).optional(),
  min_apy: z.number().min(0).optional(),
  limit: z.number().int().min(1).max(50).default(20),
});

// Enso's protocol catalog and position data. Both are third-party data, not
// verified by this server; an action taken from them still goes through
// action_preview's on-chain checks.
export class EnsoCatalog {
  private standards: { at: number; data: Standard[] } | null = null;
  private actions: { at: number; data: Action[] } | null = null;
  private positionsCache = new Map<string, { at: number; data: Position[] }>();
  constructor(private api: EnsoApi, private now: () => number = Date.now) {}

  async supported(network: WalletNetwork, protocol: string, action: string) {
    const chain = chainIds[network];
    return (await this.loadStandards()).some(s => slugsOf(s).some(x => x.slug === protocol) && (s.actions ?? []).some(a => a.action === action && chainsOf(a).includes(chain)));
  }

  async catalog(input: z.input<typeof catalogInput>) {
    const p = catalogInput.parse(input);
    const chain = chainIds[p.network];
    const wanted = p.action ? [p.action] : [...ROUTER_ACTIONS];
    // A standard is one integration; its forks (same contracts, another
    // deployment) take the same action under their own slug.
    const matches = (await this.loadStandards()).flatMap(s => {
      const actions = [...new Set((s.actions ?? []).filter(a => typeof a.action === "string" && (wanted as string[]).includes(a.action) && chainsOf(a).includes(chain)).map(a => a.action as string))];
      if (!actions.length) return [];
      return slugsOf(s).filter(x => !p.protocol || x.slug.includes(p.protocol.toLowerCase())).map(x => ({ protocol: x.slug, url: x.url, actions }));
    });
    const inputs = Object.fromEntries((await this.loadActions()).filter(a => typeof a.action === "string" && (wanted as string[]).includes(a.action)).map(a => [a.action as string, Object.fromEntries(Object.entries(a.inputs ?? {}).filter(([k]) => !FIXED_INPUTS.has(k)).map(([k, v]) => [k, { type: String(v?.type ?? "").slice(0, 60), optional: v?.optional === true, description: String(v?.description ?? "").slice(0, 160) }]))]));
    return {
      network: p.network, total: matches.length, truncated: matches.length > p.limit, protocols: matches.slice(0, p.limit), inputs,
      excluded: "borrow, repay, harvest and other actions that would act for Enso's contract instead of this account are not offered",
      trust: "Enso catalog data, not verified by this server. Use action_preview with a protocol and action from this list; it checks the built call on-chain.",
    };
  }

  async positions(input: z.input<typeof positionsInput>) {
    const p = positionsInput.parse(input);
    const query: Record<string, string | undefined> = { type: "defi", chainId: String(chainIds[p.network]), includeMetadata: "true", pageSize: "1000", underlyingTokens: p.underlying_token ? getAddress(p.underlying_token) : undefined, protocolSlug: p.protocol, tvlFrom: p.min_tvl_usd?.toString(), apyFrom: p.min_apy?.toString() };
    const key = JSON.stringify(query);
    let hit = this.positionsCache.get(key);
    if (!hit || this.now() - hit.at > 5 * 60_000) {
      const r = await this.api.get("tokens", query) as { data?: unknown };
      hit = { at: this.now(), data: Array.isArray(r?.data) ? r.data as Position[] : [] };
      this.positionsCache.set(key, hit);
      if (this.positionsCache.size > 200) this.positionsCache.delete(this.positionsCache.keys().next().value!);
    }
    const rows = hit.data.filter(x => typeof x?.address === "string" && isAddress(x.address)).sort((a, b) => num(b.tvl) - num(a.tvl));
    return {
      network: p.network, total: rows.length,
      positions: rows.slice(0, p.limit).map(x => ({
        token: getAddress(x.address), symbol: text(x.symbol, 30), name: text(x.name, 80), decimals: Number.isInteger(x.decimals) ? x.decimals : null,
        project: text(x.project, 40), protocol: text(x.protocol ?? x.protocolSlug, 64),
        primary_address: typeof x.primaryAddress === "string" && isAddress(x.primaryAddress) ? getAddress(x.primaryAddress) : null,
        apy: opt(x.apy), apy_base: opt(x.apyBase), apy_reward: opt(x.apyReward), tvl_usd: opt(x.tvl),
        underlying: (Array.isArray(x.underlyingTokens) ? x.underlyingTokens : []).slice(0, 8).filter((u: any) => typeof u?.address === "string" && isAddress(u.address)).map((u: any) => ({ token: getAddress(u.address), symbol: text(u.symbol, 30), decimals: Number.isInteger(u.decimals) ? u.decimals : null })),
      })),
      trust: "Enso data, not verified by this server: APY and TVL are informational, not advice, and can be stale or wrong. To enter a position use action_preview (deposit, token_out = token, primary_address) or route_preview.",
    };
  }

  private async loadStandards() {
    if (!this.standards || this.now() - this.standards.at > 6 * 3600_000) this.standards = { at: this.now(), data: asArray<Standard>(await this.api.get("standards", {})) };
    return this.standards.data;
  }
  private async loadActions() {
    if (!this.actions || this.now() - this.actions.at > 6 * 3600_000) this.actions = { at: this.now(), data: asArray<Action>(await this.api.get("actions", {})) };
    return this.actions.data;
  }
}

function slugsOf(s: Standard) {
  return [s.protocol, ...(Array.isArray(s.forks) ? s.forks : [])].filter((x): x is { slug: string; url?: unknown } => typeof x?.slug === "string").map(x => ({ slug: x.slug, url: typeof x.url === "string" ? x.url.slice(0, 200) : null }));
}
function chainsOf(a: { supportedChains?: { id?: unknown }[] }) { return (Array.isArray(a.supportedChains) ? a.supportedChains : []).map(c => c?.id); }
function asArray<T>(x: unknown): T[] { return Array.isArray(x) ? x as T[] : []; }
function num(x: unknown) { return typeof x === "number" && Number.isFinite(x) ? x : 0; }
function opt(x: unknown) { return typeof x === "number" && Number.isFinite(x) ? x : null; }
function text(x: unknown, max: number) { return typeof x === "string" ? x.slice(0, max) : null; }
