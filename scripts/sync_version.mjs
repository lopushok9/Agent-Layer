#!/usr/bin/env node
// Stamp the canonical root VERSION into every derived manifest.
//
//   node scripts/sync_version.mjs            # stamp from VERSION
//   node scripts/sync_version.mjs 0.1.34     # bump VERSION first, then stamp
//
// Run this after bumping the version; the derived manifests are generated, not
// hand-edited. scripts/check_release_version.mjs verifies the result in CI.

import fs from "node:fs";
import path from "node:path";

import { TARGETS, VERSION_FILE, readCanonicalVersion, stampTarget } from "./version_targets.mjs";

const root = process.cwd();
const explicit = process.argv[2];

if (explicit) {
  fs.writeFileSync(path.join(root, VERSION_FILE), `${explicit.trim()}\n`);
}

const version = readCanonicalVersion(root);
if (!version) {
  console.error(`${VERSION_FILE} is empty`);
  process.exit(1);
}

for (const target of TARGETS) {
  stampTarget(root, target, version);
}

console.log(`Stamped ${TARGETS.length} manifests to ${version}`);
