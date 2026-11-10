// Read-only mainnet smoke test of the NEAR stack: no keys, no signing, no funds.
//   NEAR_RPC_URL=https://free.rpc.fastnear.com npx tsx scripts/near-smoke-readonly.ts
import { randomBytes } from "node:crypto";
import { NearRpc } from "../src/near/rpc.js";
import { secp256k1KeyToAddress, DERIVATION_PATH } from "../src/near/chain-signatures.js";
import { generateSealedKey, implicitAccountId } from "../src/near/keys.js";
import { buildNearTransaction, normalizeNearTransaction } from "../src/near/transaction.js";

const rpc = new NearRpc(process.env.NEAR_RPC_URL ?? "https://free.rpc.fastnear.com", "mainnet");
await rpc.assertNetwork();
console.log("network: mainnet ✓");
console.log("gas price:", (await rpc.call<{ gas_price: string }>("gas_price", [null])).gas_price);
const block = await rpc.finalBlock();
console.log("final block:", block.height);
console.log("wrap.near ft_metadata:", JSON.stringify((await rpc.callFunction("wrap.near", "ft_metadata", {})).result).slice(0, 120));
const { publicKey } = generateSealedKey(randomBytes(32).toString("base64"), "smoke");
const account = implicitAccountId(publicKey);
console.log("fresh implicit account:", account, "on chain:", Boolean(await rpc.viewAccount(account)));
const derived = await rpc.callFunction("v1.signer", "derived_public_key", { path: DERIVATION_PATH, predecessor: account, domain_id: 0 });
console.log("derived EVM address:", secp256k1KeyToAddress(derived.result));
const tx = buildNearTransaction(account, publicKey, 1n, block.hash, normalizeNearTransaction({ receiver_id: "wrap.near", actions: [{ type: "transfer", amount_yocto: "1" }] }));
console.log("unsigned tx builds against a live block hash:", tx.encode().length, "bytes");
