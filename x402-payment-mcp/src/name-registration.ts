import { encodeFunctionData, namehash, parseAbi, toCoinType, type Address, type PublicClient } from "viem";
import { normalize } from "viem/ens";
import { z } from "zod";
import type { TransactionInput, WalletNetwork } from "./transaction-builder.js";

const nameField = z.string().min(3).max(255).describe("A Basename: one label followed by .base.eth");
const yearsField = z.number().int().min(1).max(10);
export const nameRegisterInput = z.strictObject({
  name: nameField,
  years: yearsField,
  set_primary: z.boolean().default(true).describe("Also make it this account's primary name (reverse record)"),
});
export const nameRenewInput = z.strictObject({ name: nameField, years: yearsField });

// base/basenames README (Base mainnet): the upgradeable registrar controller
// and L2 resolver that current registrations use.
const CONTROLLER = "0xa7d2607c6BD39Ae9521e514026CBB078405Ab322";
const RESOLVER = "0x426fA03fB86E510d0Dd9F70335Cf102a98b10875";
const YEAR = 365n * 86_400n;
const resolverAbi = parseAbi(["function setAddr(bytes32 node, address a)", "function setAddr(bytes32 node, uint256 coinType, bytes a)"]);
const controllerAbi = parseAbi([
  "struct RegisterRequest { string name; address owner; uint256 duration; address resolver; bytes[] data; bool reverseRecord; uint256[] coinTypes; uint256 signatureExpiry; bytes signature; }",
  "function valid(string name) pure returns (bool)",
  "function available(string name) view returns (bool)",
  "function registerPrice(string name, uint256 duration) view returns (uint256)",
  "function rentPrice(string name, uint256 duration) view returns ((uint256 base, uint256 premium))",
  "function register(RegisterRequest request) payable",
  "function renew(string name, uint256 duration) payable",
]);

type Prepare = (userId: string, input: TransactionInput) => Promise<Record<string, unknown>>;
type Wallets = { account(userId: string): Promise<{ address: Address }>; rpc(network: WalletNetwork): PublicClient };

// Basename registration and renewal as ordinary transaction previews: the
// server builds the controller call, the user confirms it, transaction_execute
// sends it. The call pays the controller's current price; the controller
// refunds any excess with a call, which a smart account can receive.
export class NameRegistration {
  constructor(private wallets: Wallets, private prepare: Prepare) {}

  async register(userId: string, input: z.input<typeof nameRegisterInput>) {
    const p = nameRegisterInput.parse(input);
    const { label, full } = basename(p.name);
    const { address: owner } = await this.wallets.account(userId);
    const read = this.reader();
    if (!(await read<boolean>("valid", [label]))) throw new Error("this name is not valid for registration");
    if (!(await read<boolean>("available", [label]))) throw new Error("this name is already registered");
    const duration = BigInt(p.years) * YEAR, node = namehash(full);
    const price = await read<bigint>("registerPrice", [label, duration]);
    // Address records for Ethereum and Base, so the name resolves to this
    // account in wallets that read either.
    const data = [encodeFunctionData({ abi: resolverAbi, functionName: "setAddr", args: [node, owner] }), encodeFunctionData({ abi: resolverAbi, functionName: "setAddr", args: [node, toCoinType(8453), owner] })];
    const call = encodeFunctionData({ abi: controllerAbi, functionName: "register", args: [{ name: label, owner, duration, resolver: RESOLVER, data, reverseRecord: p.set_primary, coinTypes: [], signatureExpiry: 0n, signature: "0x" }] });
    const preview = await this.prepare(userId, { network: "base", calls: [{ to: CONTROLLER, value: price.toString(), data: call }] });
    return { ...preview, registration: { name: full, owner, years: p.years, price_wei: price.toString(), primary_name: p.set_primary, records: "address on Ethereum and Base set to this account" } };
  }

  async renew(userId: string, input: z.input<typeof nameRenewInput>) {
    const p = nameRenewInput.parse(input);
    const { label, full } = basename(p.name);
    const read = this.reader();
    if (await read<boolean>("available", [label])) throw new Error("this name is not registered; register it instead");
    const duration = BigInt(p.years) * YEAR;
    const price = await read<{ base: bigint }>("rentPrice", [label, duration]);
    const data = encodeFunctionData({ abi: controllerAbi, functionName: "renew", args: [label, duration] });
    const preview = await this.prepare(userId, { network: "base", calls: [{ to: CONTROLLER, value: price.base.toString(), data }] });
    return { ...preview, renewal: { name: full, years: p.years, price_wei: price.base.toString(), note: "Anyone may renew any name; renewing does not change its owner." } };
  }

  private reader() {
    const rpc = this.wallets.rpc("base");
    return <T>(functionName: "valid" | "available" | "registerPrice" | "rentPrice", args: readonly unknown[]) => rpc.readContract({ address: CONTROLLER, abi: controllerAbi, functionName, args } as any) as Promise<T>;
  }
}

// One normalised label directly under base.eth. ENS .eth names moved to ENS
// v2 in October 2026 (new registry, rent paid in ERC-20), which these tools do
// not build calls for.
function basename(name: string) {
  let full: string;
  try { full = normalize(name.trim()); } catch { throw new Error("not a valid ENS name"); }
  const label = full.endsWith(".base.eth") ? full.slice(0, -".base.eth".length) : "";
  if (!label && full.endsWith(".eth") && full.split(".").length === 2) throw new Error("ENS .eth registration and renewal are not supported; these tools handle Basenames (name.base.eth)");
  if (!label || label.includes(".")) throw new Error("a Basename is one label followed by .base.eth");
  return { label, full };
}
