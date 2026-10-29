import assert from "node:assert/strict";
import test from "node:test";
import { annotateRecipients, Names } from "../src/names.js";

const jesse = "0x2211d1D0020DAEA8039E46Cf1367962070d77DA9", vitalik = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", liar = "0x3333333333333333333333333333333333333333";
function names(records: Record<string, { base?: string; eth?: string }>, reverse: { ens?: Record<string, string>; base?: Record<string, string> } = {}) {
  const lookups: string[] = [];
  const eth = {
    getEnsAddress: async ({ name, coinType }: { name: string; coinType?: bigint }) => { lookups.push(`${name}:${coinType ?? 60}`); const r = records[name]; return (coinType ? r?.base : r?.eth) ?? null; },
    getEnsName: async ({ address }: { address: string }) => reverse.ens?.[address] ?? null,
  };
  const base = { readContract: async ({ args }: { args: [string] }) => reverse.base?.[args[0]] ?? "" };
  return { n: new Names(network => (network === "ethereum" ? eth : base) as any), lookups };
}

test("a name resolves to its chain record, else its default address, and says which", async () => {
  const { n } = names({ "jesse.base.eth": { base: jesse.toLowerCase(), eth: jesse }, "vitalik.eth": { eth: vitalik } });
  assert.deepEqual(await n.forward("Jesse.Base.eth", "base"), { name: "jesse.base.eth", address: jesse, address_source: "record for chain 8453", warnings: [] });
  assert.equal((await n.forward("vitalik.eth", "base"))!.address_source, "default Ethereum address (no record for this chain)");
  assert.equal(await n.forward("nobody.eth", "base"), null);
  await assert.rejects(n.resolve({ network: "base", name: "nobody.eth" }), /no address for the selected network/);
  await assert.rejects(n.forward("bad name!.eth", "base"), /not a valid ENS name/);
});

test("a primary name is shown only when it resolves back to the address", async () => {
  const { n } = names({ "vitalik.eth": { eth: vitalik } }, { ens: { [liar]: "vitalik.eth", [vitalik]: "vitalik.eth" } });
  assert.equal((await n.resolve({ network: "ethereum", address: liar })).name, null, "a reverse record claiming a famous name");
  assert.equal((await n.resolve({ network: "ethereum", address: vitalik })).name, "vitalik.eth");
});

test("look-alike names carry a warning, and a preview names its transfer recipients", async () => {
  const { n } = names({ "🦊.eth": { eth: liar }, "vitalik.eth": { eth: vitalik } }, { ens: { [vitalik]: "vitalik.eth" } });
  await assert.rejects(n.forward("vіtalik.eth", "ethereum"), /not a valid ENS name/, "ENSIP-15 refuses a mixed-script look-alike");
  assert.match((await n.forward("🦊.eth", "ethereum"))!.warnings[0]!, /non-ASCII/);
  const d = await annotateRecipients([
    { to: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", value_wei: "0", data: "0xa9059cbb", function: "transfer", arguments: [vitalik.toLowerCase(), "1"] },
    { to: vitalik, value_wei: "5", data: "0x" },
    { to: liar, value_wei: "0", data: "0x095ea7b3", function: "approve", arguments: [vitalik, "1"] },
  ], "ethereum", n);
  assert.deepEqual(d.map(x => x.recipient), [{ address: vitalik, name: "vitalik.eth" }, { address: vitalik, name: "vitalik.eth" }, undefined]);
});
