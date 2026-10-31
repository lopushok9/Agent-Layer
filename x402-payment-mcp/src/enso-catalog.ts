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
  sort_by: z.enum(["tvl", "apy", "apy_base"]).default("tvl").describe("Descending; missing values last. Applies to the fetched sample only when incomplete"),
  offset: z.number().int().min(0).max(4999).default(0).describe("Offset within the cached sorted sample"),
  limit: z.number().int().min(1).max(50).default(20),
});

// Enso's protocol catalog and position data. Both are third-party data, not
// verified by this server; an action taken from them still goes through
// action_preview's on-chain checks.
export class EnsoCatalog {
  private standards: { at: number; data: Standard[] } | null = null;
  private actions: { at: number; data: Action[] } | null = null;
  private positionsCache = new Map<string, { at: number; data: Position[]; complete: boolean; pages: number }>();
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
      const data: Position[] = [];
      let complete = false, pages = 0;
      // Bound latency and memory. Never imply a global ranking if more pages exist.
      for (let page = 1; page <= 5; page++) {
        const r = await this.api.get("tokens", { ...query, page: String(page) }) as { data?: unknown; meta?: { next?: unknown } };
        if (!r || !Array.isArray(r.data)) throw new Error("Enso returned an invalid positions response");
        data.push(...r.data as Position[]);
        pages++;
        if (r.meta && Object.hasOwn(r.meta, "next")) {
          if (r.meta.next === null) { complete = true; break; }
          if (r.meta.next !== page + 1) throw new Error("Enso returned invalid positions pagination");
        } else if (r.data.length < 1000) { complete = true; break; }
      }
      hit = { at: this.now(), data, complete, pages };
      this.positionsCache.set(key, hit);
      if (this.positionsCache.size > 200) this.positionsCache.delete(this.positionsCache.keys().next().value!);
    }
    const field = { tvl: "tvl", apy: "apy", apy_base: "apyBase" }[p.sort_by];
    const rows = hit.data.filter(x => typeof x?.address === "string" && isAddress(x.address)).sort((a, b) => {
      const av = opt(a[field]), bv = opt(b[field]);
      return av === null ? (bv === null ? 0 : 1) : bv === null ? -1 : bv - av;
    });
    return {
      network: p.network, total: rows.length, total_scope: "valid rows in fetched sample", source: "enso",
      fetched_at: new Date(hit.at).toISOString(), cache_age_seconds: Math.max(0, Math.floor((this.now() - hit.at) / 1000)),
      source_complete: hit.complete, source_pages_fetched: hit.pages, sort_by: p.sort_by,
      truncated: !hit.complete || p.offset + p.limit < rows.length,
      next_offset: p.offset + p.limit < rows.length ? p.offset + p.limit : null,
      positions: rows.slice(p.offset, p.offset + p.limit).map(x => ({
        token: getAddress(x.address), symbol: text(x.symbol, 30), name: text(x.name, 80), decimals: Number.isInteger(x.decimals) ? x.decimals : null,
        project: text(x.project, 40), protocol: text(x.protocol ?? x.protocolSlug, 64),
        primary_address: typeof x.primaryAddress === "string" && isAddress(x.primaryAddress) ? getAddress(x.primaryAddress) : null,
        apy: opt(x.apy), apy_base: opt(x.apyBase), apy_reward: opt(x.apyReward), tvl_usd: opt(x.tvl),
        underlying: (Array.isArray(x.underlyingTokens) ? x.underlyingTokens : []).slice(0, 8).filter((u: any) => typeof u?.address === "string" && isAddress(u.address)).map((u: any) => ({ token: getAddress(u.address), symbol: text(u.symbol, 30), decimals: Number.isInteger(u.decimals) ? u.decimals : null })),
      })),
      trust: "Enso data is unverified and may be stale; fetched_at is our fetch time, not the source's update time. Missing APY is not zero. Rewards may require staking and can be inactive. Empty results do not establish that a market does not exist. A catalog entry does not confirm a position can be entered or exited; check previews.",
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
function opt(x: unknown) { return typeof x === "number" && Number.isFinite(x) ? x : null; }
function text(x: unknown, max: number) { return typeof x === "string" ? x.slice(0, max) : null; }
