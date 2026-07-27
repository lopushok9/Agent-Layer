import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const HOST_NAMES = Object.freeze([
  "openclaw",
  "codex",
  "claude-code",
  "hermes",
]);

const HOST_ALIASES = Object.freeze({
  openclaw: "openclaw",
  codex: "codex",
  claude: "claude-code",
  "claude-code": "claude-code",
  claudecode: "claude-code",
  hermes: "hermes",
});

function expandHome(value, env) {
  const home = env.HOME || os.homedir();
  if (value === "~") return home;
  if (value.startsWith("~/")) return path.join(home, value.slice(2));
  return value;
}

function existingEvidence(candidates, exists = fs.existsSync) {
  return candidates.filter((candidate) => {
    try {
      return exists(candidate);
    } catch {
      return false;
    }
  });
}

function detectedHost(name, displayName, binary, configCandidates, commandPath, exists) {
  const binaryPath = commandPath(binary);
  const configPaths = existingEvidence(configCandidates, exists);
  const evidence = [
    ...(binaryPath ? [{ type: "cli", path: binaryPath }] : []),
    ...configPaths.map((configPath) => ({ type: "config", path: configPath })),
  ];
  return {
    name,
    display_name: displayName,
    detected: evidence.length > 0,
    confidence: evidence.length > 0 ? "high" : "none",
    evidence,
  };
}

export function detectHosts({
  env = process.env,
  commandPath,
  exists = fs.existsSync,
} = {}) {
  if (typeof commandPath !== "function") {
    throw new TypeError("detectHosts requires commandPath(name)");
  }
  const home = env.HOME || os.homedir();
  const openclawHome = path.resolve(expandHome(env.OPENCLAW_HOME || "~/.openclaw", env));
  const codexHome = path.resolve(expandHome(env.CODEX_HOME || "~/.codex", env));
  const hermesHome = path.resolve(expandHome(env.HERMES_HOME || "~/.hermes", env));
  const claudeHome = path.resolve(expandHome(env.CLAUDE_CONFIG_DIR || "~/.claude", env));

  return [
    detectedHost(
      "openclaw",
      "OpenClaw",
      "openclaw",
      [path.join(openclawHome, "openclaw.json")],
      commandPath,
      exists,
    ),
    detectedHost(
      "codex",
      "Codex",
      "codex",
      [path.join(codexHome, "config.toml")],
      commandPath,
      exists,
    ),
    detectedHost(
      "claude-code",
      "Claude Code",
      "claude",
      [
        path.join(claudeHome, "settings.json"),
        path.join(home, ".claude.json"),
      ],
      commandPath,
      exists,
    ),
    detectedHost(
      "hermes",
      "Hermes",
      "hermes",
      [
        path.join(hermesHome, "config.yaml"),
        path.join(hermesHome, "config.yml"),
        path.join(hermesHome, "settings.json"),
      ],
      commandPath,
      exists,
    ),
  ];
}

function flagValues(args, name) {
  const values = [];
  const prefix = `${name}=`;
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (value === name) {
      const next = args[index + 1] || "";
      if (!next || next.startsWith("--")) {
        throw new Error(`${name} requires a value.`);
      }
      values.push(next);
      index += 1;
    } else if (value.startsWith(prefix)) {
      values.push(value.slice(prefix.length));
    }
  }
  return values;
}

function normalizeHostToken(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return HOST_ALIASES[normalized] || normalized;
}

function parseHostSet(values, { detected, managed }) {
  const selected = new Set();
  for (const rawValue of values) {
    for (const rawToken of String(rawValue).split(",")) {
      const token = normalizeHostToken(rawToken);
      if (!token) continue;
      if (token === "none" || token === "runtime-only") {
        selected.clear();
        continue;
      }
      if (token === "all") {
        HOST_NAMES.forEach((name) => selected.add(name));
        continue;
      }
      if (token === "detected") {
        detected.forEach((name) => selected.add(name));
        continue;
      }
      if (token === "managed") {
        managed.forEach((name) => selected.add(name));
        continue;
      }
      if (!HOST_NAMES.includes(token)) {
        throw new Error(
          `Unknown host '${rawToken}'. Expected: ${HOST_NAMES.join(", ")}, detected, managed, all, or none.`,
        );
      }
      selected.add(token);
    }
  }
  return selected;
}

export function buildInstallPlan({
  args,
  detections,
  managedHosts = [],
  runtimeInstalled,
}) {
  const detected = detections.filter((entry) => entry.detected).map((entry) => entry.name);
  const managed = managedHosts.filter((name) => HOST_NAMES.includes(name));
  const hostValues = flagValues(args, "--hosts");
  const explicitHosts = hostValues.length > 0;
  const runtimeOnly = args.includes("--runtime-only");
  const managedOnly = args.includes("--managed-only");

  let selected;
  let selectionReason;
  if (runtimeOnly) {
    selected = new Set();
    selectionReason = "runtime_only";
  } else if (managedOnly) {
    selected = new Set(managed);
    selectionReason = "managed_only";
  } else if (explicitHosts) {
    selected = parseHostSet(hostValues, { detected, managed });
    selectionReason = "explicit";
  } else if (runtimeInstalled) {
    selected = new Set(managed);
    selectionReason = "existing_runtime_managed_only";
  } else {
    selected = new Set(detected);
    selectionReason = "fresh_install_detected";
  }

  const excluded = parseHostSet(flagValues(args, "--exclude"), { detected, managed });
  excluded.forEach((name) => selected.delete(name));

  return {
    schema_version: 1,
    runtime_installed_before: Boolean(runtimeInstalled),
    selection_reason: selectionReason,
    explicit_hosts: explicitHosts,
    detected_hosts: detected,
    managed_hosts: managed,
    selected_hosts: HOST_NAMES.filter((name) => selected.has(name)),
    excluded_hosts: HOST_NAMES.filter((name) => excluded.has(name)),
    detections,
  };
}

export function stripUniversalInstallerArgs(args) {
  const output = [];
  const valueFlags = new Set(["--hosts", "--exclude"]);
  const booleanFlags = new Set([
    "--runtime-only",
    "--managed-only",
    "--no-prompt",
    "--json",
  ]);
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (booleanFlags.has(value)) continue;
    if (valueFlags.has(value)) {
      index += 1;
      continue;
    }
    if ([...valueFlags].some((name) => value.startsWith(`${name}=`))) continue;
    output.push(value);
  }
  return output;
}
