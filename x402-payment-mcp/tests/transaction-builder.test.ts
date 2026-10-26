import assert from "node:assert/strict";
import test from "node:test";
import { decodeFunctionData, erc20Abi } from "viem";
import { normalizeTransaction, transactionFingerprint } from "../src/transaction-builder.js";

const account = "0x1111111111111111111111111111111111111111";
const token = "0x2222222222222222222222222222222222222222";
const recipient = "0x3333333333333333333333333333333333333333";

test("ABI calls preserve uint256 amounts without rounding and compose with raw calls", () => {
  const value = "900719925474099312345";
  const p = normalizeTransaction({ network: "base", calls: [{ to: token, abi: [...erc20Abi], function_name: "transfer", args: [recipient, value] }, { to: recipient, value: "12" }] }, account);
  assert.equal(decodeFunctionData({ abi: erc20Abi, data: p.calls[0]!.data }).args?.[1], BigInt(value));
  assert.equal(p.calls[1]!.value, "12");
  assert.equal(p.descriptions[0]!.abi_source, "caller_supplied_unverified");
});

test("chain, wallet, order, target, data and value are bound to the fingerprint", () => {
  const p = normalizeTransaction({ network: "base", calls: [{ to: recipient, value: "1" }, { to: token, data: "0x12345678" }] }, account);
  const hash = transactionFingerprint("base", account, p.calls);
  assert.notEqual(hash, transactionFingerprint("ethereum", account, p.calls));
  assert.notEqual(hash, transactionFingerprint("base", recipient, p.calls));
  assert.notEqual(hash, transactionFingerprint("base", account, [...p.calls].reverse()));
  for (const change of [{ value: "2" }, { to: token as `0x${string}` }, { data: "0x12" as const }]) assert.notEqual(hash, transactionFingerprint("base", account, [{ ...p.calls[0]!, ...change }, p.calls[1]!]));
});

test("rejects ambiguous encodings, unsupported modes, networks and unsafe amounts", () => {
  for (const calls of [[{ to: account }], [{ to: "0x0000000000000000000000000000000000000000" }], [{ to: recipient, value: "-1" }], [{ to: recipient, value: "1.0" }], [{ to: token, data: "0x1" }], [{ to: token, abi: [...erc20Abi], function_name: "transfer", args: [recipient, 1e30] }], [{ to: token, abi: [...erc20Abi], function_name: "transfer", data: "0x" }], [{ to: token, mode: "delegatecall" }]]) assert.throws(() => normalizeTransaction({ network: "base", calls } as any, account));
  assert.throws(() => normalizeTransaction({ network: "arc", calls: [{ to: token }] } as any, account));
});
