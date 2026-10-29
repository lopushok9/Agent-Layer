import { decodeAbiParameters, getAddress, pad, type Address, type Hex } from "viem";

// viem's traceAssetChanges measures balanceOf(account) on tokens it saw move:
// an ERC-721 shows only as a count (not which token id left), and ERC-1155
// moves are not seen at all because they emit TransferSingle/TransferBatch,
// not Transfer. These per-id changes come from the simulated logs instead.
const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const TRANSFER_SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62";
const TRANSFER_BATCH = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb";

export type NftChange = { token: Address; standard: "erc721" | "erc1155"; token_id: string; diff: string };
type Log = { address?: unknown; topics?: readonly unknown[]; data?: unknown };

export function nftChanges(logs: readonly Log[], account: Address): NftChange[] {
  const me = pad(account.toLowerCase() as Hex, { size: 32 });
  const net = new Map<string, { token: Address; standard: NftChange["standard"]; id: bigint; diff: bigint }>();
  const add = (token: Address, standard: NftChange["standard"], id: bigint, from: string, to: string, amount: bigint) => {
    const delta = (to === me ? amount : 0n) - (from === me ? amount : 0n);
    if (delta === 0n) return;
    const key = `${token.toLowerCase()}:${standard}:${id}`;
    const hit = net.get(key) ?? { token, standard, id, diff: 0n };
    hit.diff += delta;
    net.set(key, hit);
  };
  for (const log of logs) {
    const topics = (log.topics ?? []).map(t => String(t).toLowerCase());
    if (typeof log.address !== "string" || !/^0x[0-9a-fA-F]{40}$/.test(log.address)) continue;
    const token = getAddress(log.address), data = (typeof log.data === "string" ? log.data : "0x") as Hex;
    try {
      // ERC-721 indexes the token id as a fourth topic; ERC-20 has three.
      if (topics[0] === TRANSFER && topics.length === 4) add(token, "erc721", BigInt(topics[3]!), topics[1]!, topics[2]!, 1n);
      else if (topics[0] === TRANSFER_SINGLE && topics.length === 4) {
        const [id, value] = decodeAbiParameters([{ type: "uint256" }, { type: "uint256" }], data);
        add(token, "erc1155", id, topics[2]!, topics[3]!, value);
      } else if (topics[0] === TRANSFER_BATCH && topics.length === 4) {
        const [ids, values] = decodeAbiParameters([{ type: "uint256[]" }, { type: "uint256[]" }], data);
        ids.forEach((id, i) => add(token, "erc1155", id, topics[2]!, topics[3]!, values[i] ?? 0n));
      }
    } catch { /* not a well-formed NFT event */ }
  }
  return [...net.values()].filter(x => x.diff !== 0n).map(x => ({ token: x.token, standard: x.standard, token_id: x.id.toString(), diff: x.diff.toString() }));
}

// null when execution is no worse for the account than the preview: no NFT
// leaves that the preview did not show leaving (by id and amount), and each
// collection still delivers at least as many as previewed (a mint may pick
// another id). Malformed data never passes.
export function nftChangeMismatch(preview: unknown, fresh: unknown): string | null {
  const before = parse(preview ?? []), now = parse(fresh ?? []);
  if (!before || !now) return "simulated NFT changes differ from preview; prepare and confirm a new operation";
  const out = (m: NftChange[]) => new Map(m.filter(x => BigInt(x.diff) < 0n).map(x => [`${x.token.toLowerCase()}:${x.standard}:${x.token_id}`, -BigInt(x.diff)]));
  const allowed = out(before);
  for (const [key, amount] of out(now)) if (amount > (allowed.get(key) ?? 0n)) return `simulated NFT changes differ from preview (${key.split(":")[0]} token ${key.split(":")[2]}: previewed out ${allowed.get(key) ?? 0n}, now out ${amount}); prepare and confirm a new operation`;
  const received = (m: NftChange[]) => m.reduce((acc, x) => { const d = BigInt(x.diff); if (d > 0n) acc.set(x.token.toLowerCase(), (acc.get(x.token.toLowerCase()) ?? 0n) + d); return acc; }, new Map<string, bigint>());
  const want = received(before), got = received(now);
  for (const [token, amount] of want) if ((got.get(token) ?? 0n) < amount) return `simulated NFT changes differ from preview (${token}: previewed in ${amount}, now in ${got.get(token) ?? 0n}); prepare and confirm a new operation`;
  return null;
}

function parse(x: unknown): NftChange[] | null {
  if (!Array.isArray(x)) return null;
  for (const c of x) if (!c || typeof c.token !== "string" || !/^0x[0-9a-fA-F]{40}$/.test(c.token) || !["erc721", "erc1155"].includes(c.standard) || !/^\d{1,78}$/.test(String(c.token_id)) || !/^-?\d{1,78}$/.test(String(c.diff))) return null;
  return x as NftChange[];
}
