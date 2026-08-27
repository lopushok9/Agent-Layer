import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const workspaceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tempRoot = mkdtempSync(join(tmpdir(), "agentlayer-connector-pack-"));

function run(command, args, cwd = tempRoot) {
  return execFileSync(command, args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

try {
  run("npm", ["pack", join(workspaceRoot, "sdk-typescript"), "--pack-destination", tempRoot]);
  run("npm", ["pack", join(workspaceRoot, "conformance"), "--pack-destination", tempRoot]);
  const archives = readdirSync(tempRoot).filter((name) => name.endsWith(".tgz")).sort();
  if (archives.length !== 2) throw new Error(`Expected two package archives, found ${archives.length}.`);

  const repeatRoot = join(tempRoot, "repeat");
  mkdirSync(repeatRoot);
  run("npm", ["pack", join(workspaceRoot, "sdk-typescript"), "--pack-destination", repeatRoot]);
  run("npm", ["pack", join(workspaceRoot, "conformance"), "--pack-destination", repeatRoot]);
  for (const archive of archives) {
    if (sha256(join(tempRoot, archive)) !== sha256(join(repeatRoot, archive))) {
      throw new Error(`${archive} is not reproducible across consecutive npm pack runs.`);
    }
  }

  for (const archive of archives) {
    const listing = run("tar", ["-tzf", join(tempRoot, archive)]);
    for (const required of ["package/package.json", "package/README.md", "package/LICENSE"]) {
      if (!listing.split("\n").includes(required)) {
        throw new Error(`${archive} is missing ${required}.`);
      }
    }
    if (!listing.split("\n").some((entry) => entry.startsWith("package/dist/") && entry.endsWith(".js"))) {
      throw new Error(`${archive} is missing compiled JavaScript.`);
    }
  }

  run("npm", ["init", "--yes"], tempRoot);
  const packageJsonPath = join(tempRoot, "package.json");
  const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"));
  writeFileSync(packageJsonPath, `${JSON.stringify({ ...packageJson, type: "module" }, null, 2)}\n`);
  run(
    "npm",
    [
      "install",
      "--ignore-scripts",
      ...archives.map((archive) => join(tempRoot, archive)),
      "typescript@7.0.2",
      "@types/node@24.13.3",
    ],
    tempRoot
  );
  writeFileSync(
    join(tempRoot, "consumer.ts"),
    `import { defineReadOnlyConnector } from "@agentlayer.tech/connector-sdk";
import { assertFixture } from "@agentlayer.tech/connector-conformance";

assertFixture({ schema_version: 1, tools: { ping: { arguments: {} } } });
const connector = defineReadOnlyConnector({
  manifest: {
    schema_version: 1,
    id: "com.example.external",
    name: "External Consumer",
    version: "1.0.0",
    publisher: { id: "example", name: "Example" },
    agentlayer: { protocol_version: 1, runtime_range: ">=0.1.101" },
    trust: "community_read_only",
    transport: { type: "https", url: "https://connector.example.com" },
    permissions: { wallet_address: false, transaction_intents: false, network_hosts: [] },
    tools: [{
      name: "ping",
      description: "Return public health data.",
      read_only: true,
      risk_level: "low",
      input_schema: { type: "object" },
      output_schema: { type: "object" },
    }],
  },
  handlers: { ping: () => ({ ok: true }) },
});
if (connector.manifest.id !== "com.example.external") throw new Error("SDK import failed");
`,
    "utf8"
  );
  writeFileSync(
    join(tempRoot, "tsconfig.json"),
    `${JSON.stringify({
      compilerOptions: {
        module: "NodeNext",
        moduleResolution: "NodeNext",
        target: "ES2022",
        strict: true,
        types: ["node"],
        outDir: "dist",
      },
      include: ["consumer.ts"],
    }, null, 2)}\n`,
    "utf8"
  );
  run(join(tempRoot, "node_modules", ".bin", "tsc"), ["-p", "tsconfig.json"]);
  run(process.execPath, [join(tempRoot, "dist", "consumer.js")]);
  console.log("smoke-packed-packages: ok");
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}
