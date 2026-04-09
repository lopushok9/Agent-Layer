import { Buffer } from "node:buffer";
import process from "node:process";
import { Connection, Keypair, Transaction, VersionedTransaction } from "@solana/web3.js";
import { swapFromSolana } from "@mayanfinance/swap-sdk";

const originalStdoutWrite = process.stdout.write.bind(process.stdout);
console.log = (...args) => console.error(...args);

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  return raw ? JSON.parse(raw) : {};
}

function writeJson(payload) {
  originalStdoutWrite(`${JSON.stringify(payload)}\n`);
}

function fail(message, details = undefined) {
  writeJson({ ok: false, error: message, details });
  process.exit(1);
}

async function executeSolanaSwap() {
  const payload = await readStdinJson();
  const quote = payload?.quote;
  if (!quote || typeof quote !== "object") {
    fail("quote is required");
  }
  const swapperWalletAddress = String(payload?.swapperWalletAddress || "").trim();
  const destinationAddress = String(payload?.destinationAddress || "").trim();
  const rpcUrl = String(payload?.rpcUrl || "").trim();
  const solanaKeypairBase64 = String(payload?.solanaKeypairBase64 || "").trim();
  const extraRpcUrls = Array.isArray(payload?.extraRpcUrls)
    ? payload.extraRpcUrls.filter((item) => typeof item === "string" && item.trim())
    : [];
  const apiKey = typeof payload?.apiKey === "string" && payload.apiKey.trim() ? payload.apiKey.trim() : undefined;

  if (!swapperWalletAddress) fail("swapperWalletAddress is required");
  if (!destinationAddress) fail("destinationAddress is required");
  if (!rpcUrl) fail("rpcUrl is required");
  if (!solanaKeypairBase64) fail("solanaKeypairBase64 is required");

  const secretKey = new Uint8Array(Buffer.from(solanaKeypairBase64, "base64"));
  const keypair = Keypair.fromSecretKey(secretKey);
  const connection = new Connection(rpcUrl, "confirmed");

  const signTransaction = async (transaction) => {
    if (transaction instanceof Transaction || transaction instanceof VersionedTransaction) {
      transaction.sign([keypair]);
      return transaction;
    }
    throw new Error("Unsupported Solana transaction type");
  };

  const result = await swapFromSolana(
    quote,
    swapperWalletAddress,
    destinationAddress,
    connection,
    signTransaction,
    undefined,
    extraRpcUrls.length ? extraRpcUrls : undefined,
    undefined,
    undefined,
    apiKey ? { apiKey } : undefined,
  );

  writeJson({
    ok: true,
    data: {
      signature: result?.signature || null,
      serializedTransactionBase64: result?.serializedTrx
        ? Buffer.from(result.serializedTrx).toString("base64")
        : null,
    },
  });
}

async function main() {
  const command = process.argv[2];
  if (command !== "execute-solana-swap") {
    fail(`Unsupported command: ${command || "<empty>"}`);
  }
  await executeSolanaSwap();
}

main().catch((error) => {
  fail(error instanceof Error ? error.message : String(error), error && typeof error === "object" ? error : undefined);
});
