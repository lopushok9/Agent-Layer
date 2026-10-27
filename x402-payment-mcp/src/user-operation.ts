import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { getUserOperationHash, entryPoint06Address, type UserOperation } from "viem/account-abstraction";
import type { Address, Hex } from "viem";
import { chainIds, type WalletNetwork } from "./transaction-builder.js";

export type PreparedOperation = { chainId: number; entryPoint: Address; blockNumber: string; operation: UserOperation<"0.6"> };
export type OperationProof = { executor: "viem-alchemy"; nonce: string; entryPoint: Address; blockNumber: string };
export function operationHash(p: PreparedOperation): Hex {
  return getUserOperationHash({ chainId: p.chainId, entryPointAddress: p.entryPoint, entryPointVersion: "0.6", userOperation: p.operation });
}
export function validateOperation(p: PreparedOperation, network: WalletNetwork, address: Address, hash: Hex): OperationProof {
  if (p.operation.signature !== "0x" || p.chainId !== chainIds[network] || p.entryPoint.toLowerCase() !== entryPoint06Address.toLowerCase() || p.operation.sender.toLowerCase() !== address.toLowerCase() || p.operation.nonce < 0n || p.operation.nonce >= 2n ** 256n || !/^\d+$/.test(p.blockNumber) || operationHash(p).toLowerCase() !== hash.toLowerCase()) throw new Error("UserOperation proof does not match this wallet and network");
  return { executor: "viem-alchemy", nonce: p.operation.nonce.toString(), entryPoint: p.entryPoint, blockNumber: p.blockNumber };
}
// The operation has no owner signature, but swap calldata can contain a Permit2
// authorization. Encrypt it, bind it to the ledger row, never expose it via MCP.
export function sealOperation(p: PreparedOperation, key: string | undefined, id: string): string {
  if (!key || Buffer.from(key, "base64").length !== 32) throw new Error("UserOperation encryption key is not configured");
  const iv = randomBytes(12), cipher = createCipheriv("aes-256-gcm", Buffer.from(key, "base64"), iv);
  cipher.setAAD(Buffer.from(`user-operation:v1:${id}`));
  const raw = JSON.stringify(p, (_k, v) => typeof v === "bigint" ? { bigint: v.toString() } : v);
  return ["v1", iv.toString("base64"), Buffer.concat([cipher.update(raw, "utf8"), cipher.final()]).toString("base64"), cipher.getAuthTag().toString("base64")].join(".");
}
export function openOperation(value: string, key: string | undefined, id: string): PreparedOperation {
  if (!key || Buffer.from(key, "base64").length !== 32) throw new Error("UserOperation encryption key is not configured");
  const [v, iv, body, tag] = value.split(".");
  if (v !== "v1" || !iv || !body || !tag) throw new Error("Invalid encrypted UserOperation");
  const decipher = createDecipheriv("aes-256-gcm", Buffer.from(key, "base64"), Buffer.from(iv, "base64"));
  decipher.setAAD(Buffer.from(`user-operation:v1:${id}`)); decipher.setAuthTag(Buffer.from(tag, "base64"));
  return JSON.parse(Buffer.concat([decipher.update(Buffer.from(body, "base64")), decipher.final()]).toString("utf8"), (_k, v) => v && typeof v === "object" && Object.keys(v).length === 1 && typeof v.bigint === "string" ? BigInt(v.bigint) : v);
}
