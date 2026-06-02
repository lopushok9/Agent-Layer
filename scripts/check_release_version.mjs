#!/usr/bin/env node

import fs from "node:fs";

const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));
const pyproject = fs.readFileSync("agent-wallet/pyproject.toml", "utf8");
const pyVersion = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1] || "";
const initPy = fs.readFileSync("agent-wallet/agent_wallet/__init__.py", "utf8");
const initVersion = initPy.match(/^__version__\s*=\s*"([^"]+)"/m)?.[1] || "";
const packageVersion = packageJson.version;
const refName = process.env.GITHUB_REF_NAME || process.argv[2] || "";
const expectedFromTag = refName.startsWith("v") ? refName.slice(1) : "";
const errors = [];

if (!packageVersion) {
  errors.push("package.json version is missing");
}
if (!pyVersion) {
  errors.push("agent-wallet/pyproject.toml version is missing");
}
if (packageVersion && pyVersion && packageVersion !== pyVersion) {
  errors.push(`version mismatch: package.json=${packageVersion}, pyproject=${pyVersion}`);
}
if (!initVersion) {
  errors.push("agent-wallet/agent_wallet/__init__.py __version__ is missing");
}
if (packageVersion && initVersion && packageVersion !== initVersion) {
  errors.push(
    `version mismatch: package.json=${packageVersion}, agent_wallet/__init__.py=${initVersion}`,
  );
}
if (expectedFromTag && packageVersion !== expectedFromTag) {
  errors.push(`tag/version mismatch: tag=${refName}, package.json=${packageVersion}`);
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(error);
  }
  process.exit(1);
}

const npmTag = packageVersion.includes("-") ? "beta" : "latest";
console.log(`release_version=${packageVersion}`);
console.log(`npm_tag=${npmTag}`);

if (process.env.GITHUB_OUTPUT) {
  fs.appendFileSync(
    process.env.GITHUB_OUTPUT,
    `release_version=${packageVersion}\nnpm_tag=${npmTag}\n`,
  );
}
