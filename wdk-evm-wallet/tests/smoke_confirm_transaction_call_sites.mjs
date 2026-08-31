import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const sourcePath = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "src", "wdk_evm_wallet.js");
const source = readFileSync(sourcePath, "utf8");

assert.equal(
  source.includes("#waitForTransactionReceipt"),
  false,
  "#waitForTransactionReceipt should be fully removed -- every call site must use confirmTransaction instead"
);

const confirmCallCount = (source.match(/confirmTransaction\(/g) || []).length;
// One is the function's own definition line ("async function confirmTransaction(").
// Every other occurrence is a call site. This count only needs to grow if a new
// send operation is added later -- it is a floor, not a fragile exact match on
// today's operation count, so update it deliberately if that ever happens.
assert.ok(
  confirmCallCount >= 20,
  `expected at least 20 confirmTransaction call sites (definition + real call sites), found ${confirmCallCount}`
);

console.log("smoke_confirm_transaction_call_sites: ok");
