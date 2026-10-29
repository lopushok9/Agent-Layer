import { getAddress, isAddress, namehash, parseAbi, toCoinType, type Address, type PublicClient } from "viem";
import { normalize } from "viem/ens";
import { z } from "zod";
import { addressInput, chainIds, walletNetwork, type WalletNetwork } from "./transaction-builder.js";

export const nameResolveInput = z.strictObject({
  network: walletNetwork.describe("The network the address will be used on: a name can hold a different address per chain"),
  name: z.string().min(3).max(255).optional().describe("ENS name (vitalik.eth) or Basename (jesse.base.eth)"),
  address: addressInput.optional().describe("Address to look up the verified primary name of"),
}).refine(v => (v.name === undefined) !== (v.address === undefined), "provide name or address, not both");

// Basenames' L2 resolver on Base holds forward and reverse records; on L1
// *.base.eth resolves through ENS's universal resolver and CCIP-read.
const BASE_L2_RESOLVER = "0xC6d566A56A1aFf6508b41f6c90ff131615583BCD";
const l2ResolverAbi = parseAbi(["function name(bytes32 node) view returns (string)"]);

type Rpc = (network: WalletNetwork) => PublicClient;
export type ResolvedName = { name: string; address: Address; address_source: string; warnings: string[] };

// ENS and Basenames, read-only. A name is only ever reported for an address
// when it resolves back to that address on the same records, so a reverse
// record someone set to a famous name is not shown.
export class Names {
  private cache = new Map<string, { at: number; data: unknown }>();
  constructor(private rpc: Rpc, private now: () => number = Date.now) {}

  async resolve(input: z.input<typeof nameResolveInput>) {
    const p = nameResolveInput.parse(input);
    if (p.name !== undefined) {
      const r = await this.forward(p.name, p.network);
      if (!r) throw new Error("this name has no address for the selected network");
      return { network: p.network, ...r, trust: "Resolved through ENS on Ethereum (Basenames via CCIP-read). Show the user both the name and the address before using it." };
    }
    const address = getAddress(p.address!);
    const name = await this.reverse(address, p.network);
    return { network: p.network, address, name: name?.name ?? null, ...(name ? { warnings: name.warnings } : {}), verified: name !== null, trust: "A primary name is shown only when it resolves back to this address." };
  }

  // The address a name holds for this network: its chain-specific record
  // (ENSIP-11) when set, otherwise its default Ethereum address.
  async forward(name: string, network: WalletNetwork): Promise<ResolvedName | null> {
    let normalized: string;
    try { normalized = normalize(name.trim()); } catch { throw new Error("not a valid ENS name"); }
    if (!normalized.includes(".")) throw new Error("not a valid ENS name");
    return this.cached(`fwd:${network}:${normalized}`, async () => {
      const eth = this.rpc("ethereum");
      const chain = network === "ethereum" ? null : await eth.getEnsAddress({ name: normalized, coinType: toCoinType(chainIds[network]) }).catch(() => null);
      const fallback = chain ? null : await eth.getEnsAddress({ name: normalized });
      const address = chain ?? fallback;
      if (!address || !isAddress(address) || /^0x0{40}$/i.test(address)) return null;
      return { name: normalized, address: getAddress(address), address_source: chain ? `record for chain ${chainIds[network]}` : "default Ethereum address (no record for this chain)", warnings: lookalike(normalized) };
    }) as Promise<ResolvedName | null>;
  }

  // The verified primary name of an address: its Basename reverse record on
  // Base, else its ENS primary name; each must resolve forward to the address.
  async reverse(address: Address, network: WalletNetwork): Promise<{ name: string; warnings: string[] } | null> {
    return this.cached(`rev:${network}:${address.toLowerCase()}`, async () => {
      const candidates: string[] = [];
      if (network === "base") {
        const node = namehash(`${address.slice(2).toLowerCase()}.${(0x80000000 + chainIds.base).toString(16)}.reverse`);
        const basename = await this.rpc("base").readContract({ address: BASE_L2_RESOLVER, abi: l2ResolverAbi, functionName: "name", args: [node] }).catch(() => "");
        if (basename) candidates.push(basename);
      }
      const ens = await this.rpc("ethereum").getEnsName({ address }).catch(() => null);
      if (ens) candidates.push(ens);
      for (const name of candidates) {
        const fwd = await this.forward(name, network).catch(() => null);
        if (fwd && fwd.address === address) return { name: fwd.name, warnings: fwd.warnings };
      }
      return null;
    }) as Promise<{ name: string; warnings: string[] } | null>;
  }

  private async cached(key: string, load: () => Promise<unknown>) {
    const hit = this.cache.get(key);
    if (hit && this.now() - hit.at < 300_000) return hit.data;
    const data = await load();
    this.cache.set(key, { at: this.now(), data });
    while (this.cache.size > 5_000) this.cache.delete(this.cache.keys().next().value!);
    return data;
  }
}

function lookalike(name: string) {
  return /[^\x20-\x7e]/.test(name) ? ["name contains non-ASCII characters; it may imitate another name, so compare the address"] : [];
}

// The recipient a call pays: a token transfer's to, or a plain native-value
// call's target. Named so the preview shows "name (address)".
export async function annotateRecipients<T extends { to: Address; value_wei: string; data: string; function?: string; arguments?: unknown }>(descriptions: T[], network: WalletNetwork, names: Names): Promise<(T & { recipient?: { address: Address; name: string | null; warnings?: string[] } })[]> {
  return Promise.all(descriptions.map(async d => {
    const args = Array.isArray(d.arguments) ? d.arguments : [];
    const raw = d.function === "transfer" ? args[0] : d.function === "transferFrom" || d.function === "safeTransferFrom" ? args[1] : d.data === "0x" && d.value_wei !== "0" ? d.to : undefined;
    if (typeof raw !== "string" || !isAddress(raw)) return d;
    const address = getAddress(raw);
    // A name lookup that times out never blocks the preview.
    const name = await Promise.race([names.reverse(address, network).catch(() => null), new Promise<null>(r => setTimeout(() => r(null), 4_000))]);
    return { ...d, recipient: { address, name: name?.name ?? null, ...(name?.warnings.length ? { warnings: name.warnings } : {}) } };
  }));
}
