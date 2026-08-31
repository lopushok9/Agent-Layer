import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

const STORE_FILE = "pending-transactions.json";
const DEFAULT_WINDOW_MS = 30 * 60 * 1000;

export function transactionIdempotencyKey({ to, data, value, chainId }) {
  const canonical = JSON.stringify({
    to: String(to || "").toLowerCase(),
    data: String(data || "").toLowerCase(),
    value: String(value ?? "0"),
    chainId: String(chainId),
  });
  return crypto.createHash("sha256").update(canonical).digest("hex");
}

function storePath(dataDir) {
  return path.join(dataDir, STORE_FILE);
}

function windowMs() {
  const raw = Number(process.env.WDK_EVM_IDEMPOTENCY_WINDOW_MS);
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_WINDOW_MS;
}

async function readEntries(dataDir) {
  try {
    const raw = await fs.readFile(storePath(dataDir), "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed.entries) ? parsed.entries : [];
  } catch {
    return [];
  }
}

async function writeEntries(dataDir, entries) {
  await fs.mkdir(dataDir, { recursive: true, mode: 0o700 });
  const target = storePath(dataDir);
  const tmpPath = `${target}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmpPath, JSON.stringify({ entries }, null, 2), { encoding: "utf8", mode: 0o600 });
  await fs.rename(tmpPath, target);
}

export async function checkTransactionIdempotency(dataDir, key) {
  const cutoff = Date.now() - windowMs();
  const entries = await readEntries(dataDir);
  const match = entries.find(
    (entry) =>
      entry.key === key &&
      entry.confirmation_status !== "reverted" &&
      new Date(entry.broadcast_at).getTime() >= cutoff
  );
  if (!match) return null;
  return {
    duplicate: {
      tx_hash: match.tx_hash,
      status: match.confirmation_status,
      broadcast_at: match.broadcast_at,
    },
  };
}

// A recorded entry keeps the status it had at broadcast ("submitted") until
// the confirmation outcome is known. Without this update the spec's binding
// rule -- a reverted entry is never treated as a duplicate -- could never fire,
// because nothing ever wrote "reverted" into the store. Matching is by
// tx_hash: an unknown hash is a no-op (no throw, no spurious entry).
export async function updateTransactionConfirmationStatus(dataDir, txHash, status) {
  const target = String(txHash || "").trim().toLowerCase();
  if (!target) return false;
  const entries = await readEntries(dataDir);
  const now = new Date().toISOString();
  let changed = false;
  for (const entry of entries) {
    if (String(entry.tx_hash || "").trim().toLowerCase() === target) {
      entry.confirmation_status = status;
      entry.last_checked_at = now;
      changed = true;
    }
  }
  if (!changed) return false;
  await writeEntries(dataDir, entries);
  return true;
}

export async function recordTransactionSent(
  dataDir,
  { key, txHash, network, operation, confirmationStatus = "submitted" }
) {
  const cutoff = Date.now() - windowMs();
  const entries = (await readEntries(dataDir)).filter(
    (entry) => new Date(entry.broadcast_at).getTime() >= cutoff
  );
  const now = new Date().toISOString();
  entries.push({
    key,
    tx_hash: txHash,
    network,
    operation,
    broadcast_at: now,
    confirmation_status: confirmationStatus,
    last_checked_at: now,
  });
  await writeEntries(dataDir, entries);
}
