import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

const packageSpecs = [
  {
    name: "@agentlayertech/agent-wallet-plugin",
    dir: path.join(repoRoot, ".openclaw/extensions/agent-wallet"),
    copies: [
      { from: "index.ts", to: "dist/index.js" },
    ],
  },
];

function expectedOpenClawBlock(runtimeExtensions) {
  return {
    runtimeExtensions,
    compat: {
      pluginApi: ">=2026.3.24-beta.2",
      minGatewayVersion: "2026.3.24-beta.2",
    },
    build: {
      openclawVersion: "2026.3.24-beta.2",
      pluginSdkVersion: "2026.3.24-beta.2",
    },
  };
}

async function copyRuntimeArtifacts(spec) {
  await fs.mkdir(path.join(spec.dir, "dist"), { recursive: true });
  for (const entry of spec.copies) {
    const sourcePath = path.join(spec.dir, entry.from);
    const targetPath = path.join(spec.dir, entry.to);
    const contents = await fs.readFile(sourcePath, "utf8");
    await fs.writeFile(targetPath, contents, "utf8");
  }
}

function ensure(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function checkPackage(spec) {
  const rawPackage = await fs.readFile(path.join(spec.dir, "package.json"), "utf8");
  const pkg = JSON.parse(rawPackage);
  ensure(pkg.name === spec.name, `${spec.dir}: unexpected package name ${pkg.name}`);
  ensure(typeof pkg.version === "string" && pkg.version.length > 0, `${spec.dir}: missing version`);

  const openclaw = pkg.openclaw || {};
  const expected = expectedOpenClawBlock(spec.copies.filter((entry) => entry.to.endsWith(".js")).map((entry) => `./${entry.to}`));
  ensure(Array.isArray(openclaw.extensions) && openclaw.extensions.length > 0, `${spec.dir}: missing openclaw.extensions`);
  ensure(JSON.stringify(openclaw.runtimeExtensions) === JSON.stringify(expected.runtimeExtensions), `${spec.dir}: runtimeExtensions mismatch`);
  ensure(JSON.stringify(openclaw.compat) === JSON.stringify(expected.compat), `${spec.dir}: compat block mismatch`);
  ensure(JSON.stringify(openclaw.build) === JSON.stringify(expected.build), `${spec.dir}: build block mismatch`);

  for (const entry of spec.copies) {
    const sourcePath = path.join(spec.dir, entry.from);
    const targetPath = path.join(spec.dir, entry.to);
    const [sourceContents, targetContents] = await Promise.all([
      fs.readFile(sourcePath, "utf8"),
      fs.readFile(targetPath, "utf8"),
    ]);
    ensure(sourceContents === targetContents, `${targetPath} is stale. Run build:openclaw-plugins.`);
  }
}

async function main() {
  const mode = process.argv[2] || "build";
  if (!["build", "check"].includes(mode)) {
    throw new Error(`Unsupported mode: ${mode}`);
  }

  if (mode === "build") {
    for (const spec of packageSpecs) {
      await copyRuntimeArtifacts(spec);
    }
    console.log(`Built ${packageSpecs.length} OpenClaw plugin package runtime artifact sets.`);
    return;
  }

  for (const spec of packageSpecs) {
    await checkPackage(spec);
  }
  console.log(`Validated ${packageSpecs.length} OpenClaw plugin package definitions.`);
}

await main();
