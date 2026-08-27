import { cp, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = path.resolve(packageRoot, "..", "spec");
const destination = path.join(packageRoot, "spec");

await mkdir(destination, { recursive: true });
for (const name of [
  "connector-manifest.schema.json",
  "connector-protocol.md",
  "transaction-intent.schema.json",
]) {
  await cp(path.join(source, name), path.join(destination, name));
}
