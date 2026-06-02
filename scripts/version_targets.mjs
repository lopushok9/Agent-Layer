// Single source of truth for the project version.
//
// The root VERSION file is canonical. Every other manifest below is a *derived*
// target that must carry the exact same version. These targets are stamped by
// scripts/sync_version.mjs and verified by scripts/check_release_version.mjs, so
// they should never be edited by hand.

import fs from "node:fs";
import path from "node:path";

export const VERSION_FILE = "VERSION";

// kind -> regex capturing (prefix)(version)(suffix). Non-global on purpose: we
// only ever replace the first (top-level) occurrence in each file.
const PATTERNS = {
  json: /("version"\s*:\s*")([^"]*)(")/,
  toml: /^(version\s*=\s*")([^"]*)(")/m,
  pyinit: /^(__version__\s*=\s*")([^"]*)(")/m,
  yaml: /^(version:\s*)(\S+)(.*)$/m,
};

// Every place the version lives, across all agent frameworks and packages.
export const TARGETS = [
  { file: "package.json", kind: "json" },
  { file: "agent-wallet/pyproject.toml", kind: "toml" },
  { file: "agent-wallet/agent_wallet/__init__.py", kind: "pyinit" },
  { file: ".openclaw/extensions/agent-wallet/package.json", kind: "json" },
  { file: "agent-wallet/openclaw.plugin.json", kind: "json" },
  { file: ".openclaw/extensions/agent-wallet/openclaw.plugin.json", kind: "json" },
  { file: "codex/plugins/agent-wallet/.codex-plugin/plugin.json", kind: "json" },
  { file: "claude-code/plugins/agent-wallet/.claude-plugin/plugin.json", kind: "json" },
  { file: "hermes/plugins/agent_wallet/plugin.yaml", kind: "yaml" },
  { file: "wdk-btc-wallet/package.json", kind: "json" },
  { file: "wdk-evm-wallet/package.json", kind: "json" },
];

export function readCanonicalVersion(root) {
  return fs.readFileSync(path.join(root, VERSION_FILE), "utf8").trim();
}

export function readTargetVersion(root, target) {
  const content = fs.readFileSync(path.join(root, target.file), "utf8");
  const match = content.match(PATTERNS[target.kind]);
  return match ? match[2] : null;
}

export function stampTarget(root, target, version) {
  const filePath = path.join(root, target.file);
  const content = fs.readFileSync(filePath, "utf8");
  const pattern = PATTERNS[target.kind];
  if (!pattern.test(content)) {
    throw new Error(`No version field found in ${target.file}`);
  }
  const updated = content.replace(pattern, (_m, prefix, _old, suffix) => `${prefix}${version}${suffix}`);
  fs.writeFileSync(filePath, updated);
}

export function npmTagFor(version) {
  return version.includes("-") ? "beta" : "latest";
}
