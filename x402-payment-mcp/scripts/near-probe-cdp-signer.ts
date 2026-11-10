// Probe: can a CDP-managed Solana (ed25519) account sign the raw 32-byte
// digest a NEAR transaction needs? Uses a dedicated probe account, signs random
// bytes only, moves no funds and broadcasts nothing.
//
//   CDP_API_KEY_ID=… CDP_API_KEY_SECRET=… CDP_WALLET_SECRET=… npx tsx scripts/near-probe-cdp-signer.ts
import { randomBytes } from "node:crypto";
import { CdpClient } from "@coinbase/cdp-sdk";
import { decodeCdpSignature, encodeCdpMessage, implicitAccountId, verifyEd25519, type CdpMessageEncoding } from "../src/near/keys.js";
import { baseDecode } from "@near-js/utils";

const cdp = new CdpClient({ apiKeyId: process.env.CDP_API_KEY_ID!, apiKeySecret: process.env.CDP_API_KEY_SECRET!, walletSecret: process.env.CDP_WALLET_SECRET! });
const account = await cdp.solana.getOrCreateAccount({ name: "near-probe-v1" });
const publicKey = new Uint8Array(baseDecode(account.address));
console.log(`probe account ${account.address} → NEAR implicit ${implicitAccountId(publicKey)}`);
const digest = new Uint8Array(randomBytes(32));
for (const encoding of ["base64", "hex", "utf8"] as CdpMessageEncoding[]) {
  try {
    const { signature } = await cdp.solana.signMessage({ address: account.address, message: encodeCdpMessage(digest, encoding) });
    const sig = decodeCdpSignature(signature);
    const raw = verifyEd25519(publicKey, digest, sig);
    const text = verifyEd25519(publicKey, Buffer.from(encodeCdpMessage(digest, encoding), "utf8"), sig);
    console.log(`${encoding.padEnd(6)} raw-digest=${raw ? "VERIFIES ✅" : "no"}  signed-as-text=${text ? "yes" : "no"}`);
  } catch (e) {
    console.log(`${encoding.padEnd(6)} error: ${e instanceof Error ? e.message : String(e)}`);
  }
}
console.log("Set NEAR_SIGNER=cdp_solana and NEAR_CDP_MESSAGE_ENCODING=<encoding> only for an encoding whose raw-digest VERIFIES; otherwise use NEAR_SIGNER=sealed_key.");
