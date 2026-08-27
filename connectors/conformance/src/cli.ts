#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import path from "node:path";

import { assertFixture, runConformance } from "./index.js";

function valueAfter(args: string[], flag: string): string | undefined {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(path.resolve(file), "utf8"));
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const manifestPath = valueAfter(args, "--manifest");
  const fixturePath = valueAfter(args, "--fixture");
  const endpoint = valueAfter(args, "--endpoint");
  if (!manifestPath || !fixturePath) {
    throw new Error("Usage: agentlayer-connector-conformance --manifest connector.json --fixture conformance.json [--endpoint URL]");
  }
  const manifest = await readJson(manifestPath);
  const fixture = await readJson(fixturePath);
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error("Manifest root must be an object.");
  }
  assertFixture(fixture);
  const report = await runConformance({
    manifest: manifest as Record<string, unknown>,
    fixture,
    ...(endpoint ? { endpoint } : {}),
  });
  console.log(JSON.stringify(report, null, 2));
  process.exitCode = report.ok ? 0 : 1;
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, error: String(error instanceof Error ? error.message : error) }));
  process.exitCode = 2;
});
