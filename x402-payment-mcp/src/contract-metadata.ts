import { whatsabi } from "@shazow/whatsabi";
import { fetchPrebuiltRegistryIndex, format, formatTypedData, isFieldGroup, type DisplayField, type DisplayModel, type RegistryIndex, type TypedData } from "@ethereum-sourcify/clear-signing";
import { erc20Abi, getAddress, parseAbiItem, type Abi, type AbiFunction, type Address, type Hex, type PublicClient } from "viem";
import { chainIds, type WalletNetwork } from "./transaction-builder.js";

// Where a call's ABI came from. Only verified sources may name a call without a
// warning; selectors guessed from bytecode come from public signature databases
// whose names can collide (4byte/OpenChain), so they are a hint, never proof.
export type AbiSource = "verified_sourcify" | "verified_explorer" | "bytecode_selectors";
export type ResolvedContract = { abi: Abi; source: AbiSource; implementation?: Address };
// ERC-7730 display from the Ethereum Foundation clear-signing registry. Registry
// inclusion is review, not an audit (ERC-8176 attestations are separate).
export type ClearSigning = { source: "erc7730_registry"; intent?: string | Record<string, string>; interpolated_intent?: string; fields: { label: string; value: string }[]; contract?: { name?: string; owner?: string; url?: string }; warnings: string[] };
export type ContractMetadata = {
  contract(network: WalletNetwork, address: Address): Promise<ResolvedContract | null>;
  describeCall(network: WalletNetwork, call: { to: Address; data: Hex; value: string }, from: Address): Promise<ClearSigning | null>;
  describeTypedData(network: WalletNetwork, typedData: Omit<TypedData, "account">, from: Address): Promise<ClearSigning | null>;
};

type Cached<T> = { value: T; expires: number };
const CONTRACT_TTL_MS = 10 * 60_000, INDEX_TTL_MS = 6 * 60 * 60_000, TOKEN_TTL_MS = 60 * 60_000, MAX_ENTRIES = 5_000;
const NATIVE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";

// Same resolution order as wallets and explorers built on WhatsABI (Otterscan,
// Rivet): follow proxies by bytecode (EIP-1967, EIP-1822, Safe, ...), then
// Sourcify, then Etherscan v2, then selector lookup as a labelled last resort.
export class RegistryContractMetadata implements ContractMetadata {
  private contracts = new Map<string, Cached<ResolvedContract | null>>();
  private tokens = new Map<string, Cached<{ name: string; symbol: string; decimals: number } | null>>();
  private index: Cached<Promise<RegistryIndex>> | undefined;
  constructor(private rpc: (network: WalletNetwork) => PublicClient, private options: { etherscanApiKey?: string; fetchIndex?: () => Promise<RegistryIndex> } = {}) {}

  async contract(network: WalletNetwork, address: Address): Promise<ResolvedContract | null> {
    const key = `${chainIds[network]}:${address.toLowerCase()}`;
    const hit = this.contracts.get(key);
    if (hit && hit.expires > Date.now()) return hit.value;
    let value: ResolvedContract | null = null;
    try { value = await this.load(network, address); } catch (e) { console.error(JSON.stringify({ level: "warn", event: "abi_resolution_failed", network, address, message: e instanceof Error ? e.message : String(e) })); }
    remember(this.contracts, key, value, CONTRACT_TTL_MS);
    return value;
  }

  private async load(network: WalletNetwork, address: Address): Promise<ResolvedContract | null> {
    const chainId = chainIds[network];
    // Loaders are per call: MultiABILoader reports its winner through a mutable
    // onLoad hook that concurrent autoload calls would otherwise overwrite.
    const loaders = [new whatsabi.loaders.SourcifyABILoader({ chainId }), ...(this.options.etherscanApiKey ? [new whatsabi.loaders.EtherscanV2ABILoader({ apiKey: this.options.etherscanApiKey, chainId })] : [])];
    const result = await whatsabi.autoload(address, {
      provider: this.rpc(network), followProxies: true,
      abiLoader: new whatsabi.loaders.MultiABILoader(loaders),
      signatureLookup: new whatsabi.loaders.MultiSignatureLookup([new whatsabi.loaders.OpenChainSignatureLookup(), new whatsabi.loaders.FourByteSignatureLookup()]),
      onError: () => false,
    });
    if (!result.hasCode) return null;
    const loader = result.abiLoadedFrom?.name;
    const source: AbiSource = loader === "SourcifyABILoader" ? "verified_sourcify" : loader?.startsWith("Etherscan") ? "verified_explorer" : "bytecode_selectors";
    const abi = source === "bytecode_selectors" ? guessedAbi(result.abi) : result.abi as Abi;
    if (!abi.some(item => item.type === "function")) return null;
    const implementation = getAddress(result.address);
    return { abi, source, ...(implementation.toLowerCase() !== address.toLowerCase() ? { implementation } : {}) };
  }

  async describeCall(network: WalletNetwork, call: { to: Address; data: Hex; value: string }, from: Address) {
    if (call.data === "0x") return null;
    try { return clearSigning(await format({ chainId: chainIds[network], to: call.to, data: call.data, value: BigInt(call.value), from }, await this.formatOptions(network))); }
    catch (e) { console.error(JSON.stringify({ level: "warn", event: "clear_signing_failed", network, message: e instanceof Error ? e.message : String(e) })); return null; }
  }

  async describeTypedData(network: WalletNetwork, typedData: Omit<TypedData, "account">, from: Address) {
    try { return clearSigning(await formatTypedData({ ...typedData, account: from }, await this.formatOptions(network))); }
    catch (e) { console.error(JSON.stringify({ level: "warn", event: "clear_signing_failed", network, message: e instanceof Error ? e.message : String(e) })); return null; }
  }

  private async formatOptions(network: WalletNetwork) {
    return { descriptorResolverOptions: { type: "github" as const, index: await this.registryIndex() }, externalDataProvider: { resolveToken: (chainId: number, token: string) => this.token(network, chainId, token) } };
  }

  // The library does not cache; fetch the prebuilt index once and refresh it.
  private registryIndex() {
    if (!this.index || this.index.expires <= Date.now()) {
      const pending = (this.options.fetchIndex ?? fetchPrebuiltRegistryIndex)();
      pending.catch(() => { if (this.index?.value === pending) this.index = undefined; });
      this.index = { value: pending, expires: Date.now() + INDEX_TTL_MS };
    }
    return this.index.value;
  }

  // Symbols are read from the token itself and are not verified: any contract can
  // call itself "USDC". Displays always carry the address next to them.
  private async token(network: WalletNetwork, chainId: number, token: string) {
    if (chainId !== chainIds[network]) return null;
    if (token.toLowerCase() === NATIVE) return { name: "Ether", symbol: "ETH", decimals: 18 };
    const key = `${chainId}:${token.toLowerCase()}`;
    const hit = this.tokens.get(key);
    if (hit && hit.expires > Date.now()) return hit.value;
    let value: { name: string; symbol: string; decimals: number } | null = null;
    try {
      const address = getAddress(token), rpc = this.rpc(network);
      const [name, symbol, decimals] = await Promise.all((["name", "symbol", "decimals"] as const).map(functionName => rpc.readContract({ address, abi: erc20Abi, functionName })));
      if (typeof name === "string" && typeof symbol === "string" && typeof decimals === "number") value = { name: name.slice(0, 64), symbol: symbol.slice(0, 16), decimals };
    } catch { /* not an ERC-20: the library falls back to the raw amount */ }
    remember(this.tokens, key, value, TOKEN_TTL_MS);
    return value;
  }
}

function remember<T>(map: Map<string, Cached<T>>, key: string, value: T, ttl: number) {
  if (map.size >= MAX_ENTRIES) map.delete(map.keys().next().value!);
  map.set(key, { value, expires: Date.now() + ttl });
}

// WhatsABI's bytecode result has selectors plus the signature databases' best
// match in `sig`; keep only entries that parse as a function signature.
function guessedAbi(abi: unknown[]): Abi {
  const items: AbiFunction[] = [];
  for (const entry of abi as { type?: string; sig?: string }[]) {
    if (entry.type !== "function" || typeof entry.sig !== "string") continue;
    try { const item = parseAbiItem(`function ${entry.sig}`); if (item.type === "function") items.push(item); } catch { /* unparseable guess */ }
  }
  return items;
}

function clearSigning(model: DisplayModel): ClearSigning | null {
  // No descriptor (or a faulty one) yields raw calldata, which our own decoding covers.
  if (model.rawCalldataFallback || (!model.intent && !model.fields?.length)) return null;
  const fields: { label: string; value: string }[] = [];
  const add = (f: DisplayField, group?: string) => fields.push({ label: [group, f.separator, f.label].filter(Boolean).join(" / "), value: f.value });
  for (const f of model.fields ?? []) if (isFieldGroup(f)) f.fields.forEach(x => add(x, f.label)); else add(f);
  const m = model.metadata;
  return {
    source: "erc7730_registry",
    ...(model.intent ? { intent: model.intent } : {}),
    ...(model.interpolatedIntent ? { interpolated_intent: model.interpolatedIntent } : {}),
    fields,
    ...(m ? { contract: { ...(m.contractName ? { name: m.contractName } : {}), ...(m.owner ? { owner: m.owner } : {}), ...(m.info?.url ? { url: m.info.url } : {}) } } : {}),
    warnings: (model.warnings ?? []).map(w => `${w.code}: ${w.message}`),
  };
}
