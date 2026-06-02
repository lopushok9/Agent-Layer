#!/usr/bin/env node
// Verify the project version is consistent across every framework manifest and,
// when run on a release tag, that the tag matches the canonical VERSION.
//
// Canonical source: the root VERSION file. All derived manifests (see
// scripts/version_targets.mjs) must equal it — stamp them with
// scripts/sync_version.mjs if this fails. Emits the resolved version and npm
// dist-tag for the publish workflow.

import fs from "node:fs";

import {
  TARGETS,
  VERSION_FILE,
  npmTagFor,
  readCanonicalVersion,
  readTargetVersion,
} from "./version_targets.mjs";

const root = process.cwd();
const errors = [];

let canonical = "";
try {
  canonical = readCanonicalVersion(root);
} catch {
  errors.push(`${VERSION_FILE} is missing`);
}
if (canonical === "") {
  errors.push(`${VERSION_FILE} is empty`);
}

if (canonical) {
  for (const target of TARGETS) {
    let actual = null;
    try {
      actual = readTargetVersion(root, target);
    } catch {
      errors.push(`${target.file} is missing`);
      continue;
    }
    if (!actual) {
      errors.push(`${target.file}: version field not found`);
    } else if (actual !== canonical) {
      errors.push(
        `version mismatch: ${target.file}=${actual}, ${VERSION_FILE}=${canonical} ` +
          `(run: npm run version:sync)`,
      );
    }
  }
}

const refName = process.env.GITHUB_REF_NAME || process.argv[2] || "";
const expectedFromTag = refName.startsWith("v") ? refName.slice(1) : "";
if (expectedFromTag && canonical && canonical !== expectedFromTag) {
  errors.push(`tag/version mismatch: tag=${refName}, ${VERSION_FILE}=${canonical}`);
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(error);
  }
  process.exit(1);
}

const npmTag = npmTagFor(canonical);
console.log(`release_version=${canonical}`);
console.log(`npm_tag=${npmTag}`);

if (process.env.GITHUB_OUTPUT) {
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `release_version=${canonical}\nnpm_tag=${npmTag}\n`);
}
