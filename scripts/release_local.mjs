#!/usr/bin/env node
// One-shot local release: bump the canonical version, stamp every manifest,
// verify consistency, and reinstall the runtime into all local agent frameworks
// (OpenClaw, Codex, Claude Code) so they all run the new version from the
// working tree — the same files that get published to npm/ClawHub.
//
//   node scripts/release_local.mjs 0.1.34          # bump + stamp + install all
//   node scripts/release_local.mjs --dry-run       # show the plan, change nothing
//   node scripts/release_local.mjs 0.1.34 --dry-run
//
// Without a version argument, the current VERSION is reused.

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";

import { VERSION_FILE, readCanonicalVersion } from "./version_targets.mjs";

const root = process.cwd();
const args = process.argv.slice(2);
const dryRun = args.includes("--dry-run");
const passThrough = args.includes("--yes") ? ["--yes"] : ["--yes"]; // installs always auto-confirm secrets
const explicitVersion = args.find((a) => !a.startsWith("-")) || null;

const version = explicitVersion || readCanonicalVersion(root);
const cli = "bin/openclaw-agent-wallet.mjs";

const steps = [
  { name: "sync_version", command: `node scripts/sync_version.mjs ${version}`, argv: ["node", "scripts/sync_version.mjs", version] },
  { name: "check_version", command: "node scripts/check_release_version.mjs", argv: ["node", "scripts/check_release_version.mjs"] },
  { name: "install_openclaw", command: `node ${cli} install ${passThrough.join(" ")}`, argv: ["node", cli, "install", ...passThrough] },
  { name: "install_codex", command: `node ${cli} codex install ${passThrough.join(" ")}`, argv: ["node", cli, "codex", "install", ...passThrough] },
  { name: "install_claude_code", command: `node ${cli} claude-code install ${passThrough.join(" ")}`, argv: ["node", cli, "claude-code", "install", ...passThrough] },
];

if (dryRun) {
  console.log(
    JSON.stringify(
      { ok: true, dry_run: true, version, steps: steps.map((s) => ({ name: s.name, command: s.command })) },
      null,
      2,
    ),
  );
  process.exit(0);
}

const results = [];
for (const step of steps) {
  const [bin, ...rest] = step.argv;
  const res = spawnSync(bin, rest, { cwd: root, stdio: "inherit" });
  const ok = res.status === 0;
  results.push({ name: step.name, command: step.command, ok, status: res.status });
  if (!ok) {
    console.error(
      JSON.stringify({ ok: false, dry_run: false, version, failed_step: step.name, steps: results }, null, 2),
    );
    process.exit(1);
  }
}

console.log(JSON.stringify({ ok: true, dry_run: false, version, steps: results }, null, 2));
