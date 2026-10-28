import assert from "node:assert/strict";
import test from "node:test";
import { encodeFunctionData, erc20Abi, parseAbi, type Address } from "viem";
import { annotateCalls, normalizeTransaction, transactionFingerprint } from "../src/transaction-builder.js";
import { TransactionService } from "../src/transactions.js";
import type { ContractMetadata, ResolvedContract } from "../src/contract-metadata.js";

const account = "0x1111111111111111111111111111111111111111";
const token = "0x2222222222222222222222222222222222222222";
const spender = "0x3333333333333333333333333333333333333333";
const implementation = "0x4444444444444444444444444444444444444444";
const vaultAbi = parseAbi(["function deposit(uint256 assets, address receiver) returns (uint256)"]);

function metadata(contracts: Record<string, ResolvedContract | null>, clear = false): ContractMetadata {
  return {
    contract: async (_n, address) => contracts[address.toLowerCase()] ?? null,
    describeCall: async () => clear ? { source: "erc7730_registry", intent: "Deposit", fields: [{ label: "Amount", value: "5 USDC" }], warnings: [] } : null,
    describeTypedData: async () => null,
  };
}

test("raw calldata is decoded with the verified ABI behind a proxy; calldata and fingerprint do not change", async () => {
  const data = encodeFunctionData({ abi: erc20Abi, functionName: "approve", args: [spender, 5n] });
  const p = normalizeTransaction({ network: "base", calls: [{ to: token, data }] }, account);
  const before = transactionFingerprint("base", account, p.calls);
  const [d] = await annotateCalls("base", account, p.calls, p.descriptions, metadata({ [token]: { abi: [...erc20Abi], source: "verified_sourcify", implementation } }, true));
  assert.equal(d!.abi_source, "verified_sourcify");
  assert.equal(d!.function, "approve");
  assert.deepEqual(d!.arguments, [spender, "5"]);
  assert.equal(d!.implementation, implementation);
  assert.ok(d!.warnings.some(w => w.includes("Proxy contract") && w.includes(implementation)));
  assert.equal(d!.warnings.filter(w => w.includes("spender allowance")).length, 1, "approve warning is kept once");
  assert.equal(d!.clear_signing?.intent, "Deposit");
  assert.equal(d!.data, data);
  assert.equal(transactionFingerprint("base", account, p.calls), before);
});

test("opaque calldata becomes a named call only through a verified ABI", async () => {
  const data = encodeFunctionData({ abi: vaultAbi, functionName: "deposit", args: [7n, account] });
  const p = normalizeTransaction({ network: "base", calls: [{ to: token, data }] }, account);
  assert.ok(p.descriptions[0]!.warnings.some(w => w.startsWith("Opaque calldata")));
  const [verified] = await annotateCalls("base", account, p.calls, p.descriptions, metadata({ [token]: { abi: vaultAbi, source: "verified_explorer" } }));
  assert.equal(verified!.function, "deposit");
  assert.ok(!verified!.warnings.some(w => w.startsWith("Opaque calldata")));
  const [guessed] = await annotateCalls("base", account, p.calls, p.descriptions, metadata({ [token]: { abi: vaultAbi, source: "bytecode_selectors" } }));
  assert.equal(guessed!.abi_source, "bytecode_selectors");
  assert.ok(guessed!.warnings.some(w => w.includes("selector databases")));
});

test("a guessed ABI never overrides the caller's decoding, and a verified ABI flags calldata it cannot decode", async () => {
  const p = normalizeTransaction({ network: "base", calls: [{ to: token, abi: [...vaultAbi], function_name: "deposit", args: ["7", account] }, { to: spender, data: "0xdeadbeef" }] }, account);
  const out = await annotateCalls("base", account, p.calls, p.descriptions, metadata({ [token]: { abi: [...erc20Abi], source: "bytecode_selectors" }, [spender]: { abi: vaultAbi, source: "verified_sourcify" } }));
  assert.equal(out[0]!.abi_source, "caller_supplied_unverified");
  assert.equal(out[0]!.function, "deposit");
  assert.ok(out[1]!.warnings.includes("Calldata matches no function in the contract's verified ABI."));
});

test("contract_read without an ABI uses the verified one and reports its source; with none it asks for an ABI", async () => {
  const rpc = { getChainId: async () => 8453, readContract: async (p: { functionName: string; abi: unknown }) => { assert.equal(p.abi, erc20Abi); return 6; } };
  const wallets = { account: async () => ({ address: account as Address }), rpc: () => rpc };
  const service = new TransactionService(wallets as any, {} as any, { withPaymentLock: async (_u, fn) => fn() }, 600, metadata({ [token]: { abi: erc20Abi, source: "verified_sourcify", implementation } }));
  const r = await service.read("alice", { network: "base", to: token, function_name: "decimals" });
  assert.equal(r.abi_source, "verified_sourcify");
  assert.equal(r.implementation, implementation);
  assert.equal(r.result, 6);
  await assert.rejects(service.read("alice", { network: "base", to: spender, function_name: "decimals" }), /supply abi/);
  const bare = new TransactionService(wallets as any, {} as any, { withPaymentLock: async (_u, fn) => fn() }, 600);
  await assert.rejects(bare.read("alice", { network: "base", to: token, function_name: "decimals" }), /supply abi/);
});
