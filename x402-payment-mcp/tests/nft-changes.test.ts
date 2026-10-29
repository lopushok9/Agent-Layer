import assert from "node:assert/strict";
import test from "node:test";
import { encodeAbiParameters, encodeEventTopics, parseAbi } from "viem";
import { nftChangeMismatch, nftChanges } from "../src/nft-changes.js";

const me = "0xD09d6F783A9840E5Ca35E134912765dc11C895A1", other = "0x3333333333333333333333333333333333333333";
const punks = "0x4444444444444444444444444444444444444444", items = "0x5555555555555555555555555555555555555555", usdc = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const events = parseAbi([
  "event Transfer(address indexed from, address indexed to, uint256 indexed tokenId)",
  "event TransferSingle(address indexed operator, address indexed from, address indexed to, uint256 id, uint256 value)",
  "event TransferBatch(address indexed operator, address indexed from, address indexed to, uint256[] ids, uint256[] values)",
]);
const erc20Transfer = parseAbi(["event Transfer(address indexed from, address indexed to, uint256 value)"]);
const log721 = (from: string, to: string, id: bigint, address = punks) => ({ address, topics: encodeEventTopics({ abi: events, eventName: "Transfer", args: { from: from as any, to: to as any, tokenId: id } }), data: "0x" });

test("ERC-721 ids and ERC-1155 single and batch moves are read from logs; ERC-20 transfers are not NFTs", () => {
  const logs = [
    log721(me, other, 7n),
    log721(other, me, 9n),
    { address: items, topics: encodeEventTopics({ abi: events, eventName: "TransferSingle", args: { operator: me, from: me, to: other } }), data: encodeAbiParameters([{ type: "uint256" }, { type: "uint256" }], [1n, 5n]) },
    { address: items, topics: encodeEventTopics({ abi: events, eventName: "TransferBatch", args: { operator: other, from: other, to: me } }), data: encodeAbiParameters([{ type: "uint256[]" }, { type: "uint256[]" }], [[1n, 2n], [2n, 3n]]) },
    { address: usdc, topics: encodeEventTopics({ abi: erc20Transfer, eventName: "Transfer", args: { from: me, to: other } }), data: encodeAbiParameters([{ type: "uint256" }], [100n]) },
    log721(other, "0x6666666666666666666666666666666666666666", 1n),
  ];
  assert.deepEqual(nftChanges(logs, me), [
    { token: punks, standard: "erc721", token_id: "7", diff: "-1" },
    { token: punks, standard: "erc721", token_id: "9", diff: "1" },
    { token: items, standard: "erc1155", token_id: "1", diff: "-3" },
    { token: items, standard: "erc1155", token_id: "2", diff: "3" },
  ]);
});

test("execution may not send an NFT the preview did not, nor deliver fewer per collection", () => {
  const preview = [{ token: punks, standard: "erc721", token_id: "7", diff: "-1" }, { token: items, standard: "erc1155", token_id: "2", diff: "3" }];
  assert.equal(nftChangeMismatch(preview, preview), null);
  assert.equal(nftChangeMismatch(preview, [preview[0], { token: items, standard: "erc1155", token_id: "8", diff: "3" }]), null, "a mint may pick another id");
  assert.match(nftChangeMismatch(preview, [{ token: punks, standard: "erc721", token_id: "8", diff: "-1" }, preview[1]])!, /token 8: previewed out 0, now out 1/);
  assert.match(nftChangeMismatch(preview, [preview[0], { ...preview[1], diff: "2" }])!, /previewed in 3, now in 2/);
  assert.match(nftChangeMismatch(undefined, [{ token: punks, standard: "erc721", token_id: "1", diff: "-1" }])!, /previewed out 0/, "an older preview without NFT data allows no NFT to leave");
  assert.equal(nftChangeMismatch(undefined, undefined), null);
  assert.ok(nftChangeMismatch(preview, ["bad"]));
});
