#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createBootKeyManager } from "./lib/boot-key.mjs";
import { createHostIntegrationManager, createIntegrationManager } from "./lib/integrations.mjs";
import { createUpdateTransactionManager } from "./lib/update-transaction.mjs";

const cliPath = fileURLToPath(import.meta.url);
const packageRoot = path.resolve(path.dirname(cliPath), "..");
const setupPath = path.join(packageRoot, "setup.sh");
const packageJsonPath = path.join(packageRoot, "package.json");
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const packageVersion = packageJson.version;
const UPDATE_CLI_PATH_ENV = "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH";
const UPDATE_PACKAGE_SPEC_ENV = "OPENCLAW_AGENT_WALLET_UPDATE_PACKAGE_SPEC";
const DEFAULT_PROVIDER_GATEWAY_URL = "https://agent-layer-production.up.railway.app";
const TELEMETRY_SPOOL_NAME = "telemetry_spool.jsonl";
const TELEMETRY_ID_NAME = "telemetry_id";
const TELEMETRY_LAST_FLUSH_NAME = "telemetry_last_flush";
const TELEMETRY_FLUSH_THROTTLE_SECONDS = 20;
const TELEMETRY_FORCE_LINES = 25;
const TELEMETRY_MAX_EVENTS_PER_FLUSH = 100;
const TELEMETRY_HTTP_TIMEOUT_MS = 1500;
const KEYSTORE_BRIDGE_TIMEOUT_MS = 30000;

function printHelp() {
  console.log(`openclaw-agent-wallet

Usage:
  openclaw-agent-wallet install [options]
  openclaw-agent-wallet hermes install [options]
  openclaw-agent-wallet codex install [options]
  openclaw-agent-wallet claude-code install [options]
  openclaw-agent-wallet update [options]
  openclaw-agent-wallet status
  openclaw-agent-wallet rollback [--to <version>]
  openclaw-agent-wallet doctor
  openclaw-agent-wallet --version

Common install options:
  --yes                 Generate local runtime secrets when missing.
  --no-auto-secrets     Do not generate runtime secrets automatically.
  --backend <backend>   solana_local, wdk_btc_local, wdk_evm_local, or none.
  --network <network>   devnet, mainnet, base, ethereum, bitcoin, etc.

Examples:
  npx @agentlayer.tech/wallet install --yes
  npx @agentlayer.tech/wallet hermes install --yes
  npx @agentlayer.tech/wallet codex install --yes
  npx @agentlayer.tech/wallet claude-code install --yes
  npx @agentlayer.tech/wallet install --backend none
  npx @agentlayer.tech/wallet update --yes
  npx @agentlayer.tech/wallet update --yes --dry-run
  npx @agentlayer.tech/wallet status

The installer writes a versioned runtime under:
  ~/.openclaw/agent-wallet-runtime/releases/<version>

After a successful install it switches:
  ~/.openclaw/agent-wallet-runtime/current

Wallet files and sealed secrets remain under OPENCLAW_HOME and are not replaced
by updates. The update command fetches the latest published npm package and
reuses shared dependency snapshots when possible.

The runtime checks the npm registry in the background (at most once/day) and
surfaces a notice when a newer version is published — to the agent via the MCP
server instructions and to you via 'status' / 'doctor'. The check never blocks
startup. Disable it with AGENT_WALLET_DISABLE_UPDATE_CHECK=1.`);
}

function primaryBinCommand(pkg = packageJson) {
  const bin = pkg?.bin;
  if (!bin) return "wallet";
  if (typeof bin === "string") {
    const packageName = String(pkg?.name || "").trim();
    if (packageName) {
      const parts = packageName.split("/");
      return parts[parts.length - 1] || "wallet";
    }
    return "wallet";
  }
  const names = Object.keys(bin);
  return names[0] || "wallet";
}

function expandHome(value) {
  if (!value) return value;
  if (value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.join(os.homedir(), value.slice(2));
  return value;
}

function resolveOpenclawHome(env = process.env) {
  return path.resolve(expandHome(env.OPENCLAW_HOME || "~/.openclaw"));
}

function resolveRuntimeBase(env = process.env) {
  if (env.OPENCLAW_INSTALL_ROOT) {
    return path.resolve(expandHome(env.OPENCLAW_INSTALL_ROOT));
  }
  return path.join(resolveOpenclawHome(env), "agent-wallet-runtime");
}

function updateCheckDisabled(env = process.env) {
  const raw = String(env.AGENT_WALLET_DISABLE_UPDATE_CHECK || "").trim().toLowerCase();
  return ["1", "true", "yes", "on"].includes(raw);
}

function telemetryDisabled(env = process.env) {
  const raw = String(env.AGENT_WALLET_NO_TELEMETRY || "").trim().toLowerCase();
  return ["1", "true", "yes", "on"].includes(raw);
}

function telemetryPath(name, env = process.env) {
  return path.join(resolveOpenclawHome(env), name);
}

function telemetryInstallId(env = process.env) {
  const idPath = telemetryPath(TELEMETRY_ID_NAME, env);
  try {
    const existing = fs.readFileSync(idPath, "utf8").trim();
    if (existing) return existing;
  } catch {
    // Create below.
  }
  const next = crypto.randomUUID ? crypto.randomUUID().replaceAll("-", "") : crypto.randomBytes(16).toString("hex");
  try {
    fs.mkdirSync(path.dirname(idPath), { recursive: true });
    fs.writeFileSync(idPath, next, { mode: 0o600 });
  } catch {
    // Telemetry must not affect install flow.
  }
  return next;
}

function telemetryHost(host = "", env = process.env) {
  const raw = String(host || env.AGENT_WALLET_HOST || "").trim().toLowerCase();
  return ["claude-code", "codex", "hermes", "openclaw"].includes(raw) ? raw : "unknown";
}

function telemetrySource(env = process.env) {
  const explicit = String(env.AGENT_WALLET_INSTALL_SOURCE || "").trim().toLowerCase();
  if (explicit) return explicit.replace(/[^a-z0-9_]/g, "_").slice(0, 48);
  return env.npm_execpath || String(env.npm_config_user_agent || "").includes("npm")
    ? "npx"
    : "global_cli";
}

function positiveIntEnv(name, fallback, env = process.env) {
  const parsed = Number.parseInt(String(env[name] || ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function telemetryGatewayUrl(env = process.env) {
  return String(env.PROVIDER_GATEWAY_URL || DEFAULT_PROVIDER_GATEWAY_URL).trim().replace(/\/+$/, "");
}

function telemetryAppend(payload, env = process.env) {
  const spool = telemetryPath(TELEMETRY_SPOOL_NAME, env);
  fs.mkdirSync(path.dirname(spool), { recursive: true });
  fs.appendFileSync(spool, `${JSON.stringify(payload)}\n`, { encoding: "utf8" });
}

function telemetrySpoolLineCount(env = process.env) {
  try {
    const spool = telemetryPath(TELEMETRY_SPOOL_NAME, env);
    return fs.readFileSync(spool, "utf8").split(/\r?\n/).filter(Boolean).length;
  } catch {
    return 0;
  }
}

function telemetryShouldFlush(env = process.env) {
  const count = telemetrySpoolLineCount(env);
  if (count === 0) return false;
  if (count >= TELEMETRY_FORCE_LINES) return true;
  try {
    const last = Number(fs.readFileSync(telemetryPath(TELEMETRY_LAST_FLUSH_NAME, env), "utf8").trim() || "0");
    return Date.now() / 1000 - last >= TELEMETRY_FLUSH_THROTTLE_SECONDS;
  } catch {
    return true;
  }
}

function telemetryMarkFlush(env = process.env) {
  try {
    fs.writeFileSync(telemetryPath(TELEMETRY_LAST_FLUSH_NAME, env), String(Date.now() / 1000));
  } catch {
    // ignored
  }
}

function telemetrySpawnFlush(env = process.env, force = false) {
  if (!force && !telemetryShouldFlush(env)) return;
  telemetryMarkFlush(env);
  try {
    const child = spawn(process.execPath, [cliPath, "--telemetry-flush"], {
      detached: true,
      stdio: "ignore",
      env,
    });
    child.unref();
  } catch {
    // ignored
  }
}

function recordCliTelemetry(event, { commandName, host = "", ok = true, args = [], flush = true } = {}) {
  try {
    if (telemetryDisabled()) return;
    if (args && hasFlag(args, "--dry-run")) return;
    const payload = {
      event,
      install_id: telemetryInstallId(),
      host: telemetryHost(host),
      tool: "",
      backend: "",
      plugin_version: packageVersion,
      ok: Boolean(ok),
      ts: Math.floor(Date.now() / 1000),
      source: telemetrySource(),
      command: String(commandName || "").trim().toLowerCase().replace(/-/g, "_").slice(0, 48),
    };
    telemetryAppend(payload);
    if (flush) telemetrySpawnFlush(process.env, true);
  } catch {
    // Telemetry must never affect CLI behavior.
  }
}

async function telemetryPost(url, line) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TELEMETRY_HTTP_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      method: "POST",
      body: line,
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function telemetryFlushMain(env = process.env) {
  if (telemetryDisabled(env)) return 0;
  const spool = telemetryPath(TELEMETRY_SPOOL_NAME, env);
  const claim = `${spool}.flushing.${process.pid}`;
  try {
    fs.renameSync(spool, claim);
  } catch {
    return 0;
  }

  let lines = [];
  try {
    lines = fs.readFileSync(claim, "utf8").split(/\r?\n/).filter(Boolean);
  } catch {
    lines = [];
  }

  const url = `${telemetryGatewayUrl(env)}/v1/telemetry`;
  const failed = [];
  let sent = 0;
  for (const line of lines) {
    if (sent >= TELEMETRY_MAX_EVENTS_PER_FLUSH) {
      failed.push(line);
      continue;
    }
    if (await telemetryPost(url, line)) {
      sent += 1;
    } else {
      failed.push(line);
    }
  }

  if (failed.length) {
    try {
      fs.appendFileSync(spool, `${failed.join("\n")}\n`, { encoding: "utf8" });
    } catch {
      // ignored
    }
  }
  try {
    fs.unlinkSync(claim);
  } catch {
    // ignored
  }
  return 0;
}

function runWithCliTelemetry(fn, { startEvent, successEvent, failedEvent, commandName, host = "", args = [] }) {
  recordCliTelemetry(startEvent, { commandName, host, ok: true, args, flush: false });
  let code;
  try {
    code = fn();
  } catch (error) {
    recordCliTelemetry(failedEvent, {
      commandName,
      host,
      ok: false,
      args,
    });
    throw error;
  }
  recordCliTelemetry(code === 0 ? successEvent : failedEvent, {
    commandName,
    host,
    ok: code === 0,
    args,
  });
  return code;
}

// Shared with the Python runtime (agent_wallet/update_check.py): the cache lives
// under OPENCLAW_HOME/agent-wallet-runtime regardless of OPENCLAW_INSTALL_ROOT.
function updateCheckCachePath(env = process.env) {
  return path.join(resolveOpenclawHome(env), "agent-wallet-runtime", "update-check.json");
}

function isNewerVersion(latest, current) {
  const parse = (v) =>
    String(v)
      .trim()
      .split(".")
      .map((chunk) => parseInt((chunk.match(/^\d+/) || ["0"])[0], 10) || 0);
  const a = parse(latest);
  const b = parse(current);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0;
    const y = b[i] || 0;
    if (x !== y) return x > y;
  }
  return false;
}

function computeUpdateAvailability(env = process.env) {
  const current = activeVersion(env) || packageVersion;
  if (updateCheckDisabled(env)) {
    return { available: false, latest: null, current };
  }
  try {
    const cache = readJsonFile(updateCheckCachePath(env)) || {};
    const latest = cache.latest_version || null;
    const available = Boolean(latest && isNewerVersion(latest, current));
    return { available, latest, current };
  } catch {
    // Fail-open: a malformed cache never breaks status/doctor.
    return { available: false, latest: null, current };
  }
}

// Compare the active installed runtime (what all editors exec via current/)
// against the version of the CLI being run (the repo/canonical version during
// local development). A mismatch means a local bump was not reinstalled with
// release:local. in_sync is null when no runtime is installed yet.
function computeRuntimeInSync(env = process.env) {
  const active = activeVersion(env);
  const cli = packageVersion;
  const in_sync = active === null ? null : active === cli;
  return { in_sync, active_version: active, cli_version: cli };
}

function resolveHermesHome(env = process.env) {
  return path.resolve(expandHome(env.HERMES_HOME || "~/.hermes"));
}

function resolveCodexHome(env = process.env) {
  return path.resolve(expandHome(env.CODEX_HOME || "~/.codex"));
}

function releaseRootFor(version, env = process.env) {
  return path.join(resolveRuntimeBase(env), "releases", version);
}

function stagingRootFor(version, env = process.env) {
  return path.join(
    resolveRuntimeBase(env),
    "releases",
    `.staging-${version}-${process.pid}-${Date.now()}`,
  );
}

function updateTransactions(env = process.env) {
  return createUpdateTransactionManager({
    runtimeBase: resolveRuntimeBase(env),
    packageVersion,
    env,
  });
}

function acquireUpdateLock(env = process.env) {
  return updateTransactions(env).acquireLock();
}

function releaseUpdateLock(lock) {
  return createUpdateTransactionManager({
    runtimeBase: path.dirname(lock.path),
    packageVersion,
  }).releaseLock(lock);
}

function holdUpdateLockForTest(env = process.env) {
  updateTransactions(env).holdLockForTest();
}

function readUpdateJournal(env = process.env) {
  return updateTransactions(env).readJournal();
}

function integrations(env = process.env) {
  return createIntegrationManager({
    runtimeBase: resolveRuntimeBase(env),
    packageVersion,
    activeVersion: () => activeVersion(env),
  });
}

function recordManagedIntegration(name, details = {}, env = process.env) {
  return integrations(env).record(name, details);
}

function integrationSyncStatus(env = process.env) {
  return integrations(env).status();
}

function hostIntegrations(env = process.env) {
  return createHostIntegrationManager({
    env,
    packageRoot,
    registry: integrations(env),
    currentRuntimePath: currentRuntimePath(env),
    openclawHome: resolveOpenclawHome(env),
    hermesHome: resolveHermesHome(env),
    codexHome: resolveCodexHome(env),
    codexPluginRoot: resolveCodexPluginInstallRoot(env),
    codexMarketplacePath: resolveCodexMarketplacePath(env),
    claudeMarketplaceDir: resolveClaudeCodeMarketplaceDir(env),
    claudeMarketplaceName: CLAUDE_CODE_MARKETPLACE_NAME,
    expandHome,
    resolveVenvPython,
    commandPath,
    repairRuntimeSymlink,
    repairHermesEnv,
    ensureCodexMarketplaceEntry,
    ensureClaudeCodeMarketplace,
    pinClaudeCacheCopies,
  });
}

function writeUpdateJournal(state, details = {}, env = process.env) {
  updateTransactions(env).writeJournal(state, details);
}

function recoverInterruptedUpdate(env = process.env) {
  return updateTransactions(env).recover();
}

function updateRecoveryStatus(env = process.env) {
  return updateTransactions(env).status();
}

function writeReleaseState(runtimeRoot, state, details = {}) {
  writeJsonFile(path.join(runtimeRoot, ".agent-wallet-release.json"), {
    schema_version: 1,
    version: packageVersion,
    state,
    updated_at: new Date().toISOString(),
    ...details,
  });
}

function failStagingRuntime(stagingRoot, error) {
  if (!stagingRoot || !fs.existsSync(stagingRoot)) return null;
  writeReleaseState(stagingRoot, "failed", { error: String(error || "install failed") });
  const failedRoot = path.join(
    path.dirname(stagingRoot),
    `.failed-${packageVersion}-${Date.now()}`,
  );
  fs.renameSync(stagingRoot, failedRoot);
  return failedRoot;
}

function commitStagedRuntime(stagingRoot, releaseRoot, replacedRoot = null, env = process.env) {
  if (!stagingRoot) return null;
  if (fs.existsSync(releaseRoot)) {
    replacedRoot ||= uniquePathWithSuffix(
      path.join(path.dirname(releaseRoot), `${path.basename(releaseRoot)}-replaced`),
    );
    fs.renameSync(releaseRoot, replacedRoot);
    if (env.AGENT_WALLET_TEST_EXIT_AFTER_RELEASE_RENAME === "1") process.exit(86);
  }
  try {
    fs.renameSync(stagingRoot, releaseRoot);
  } catch (error) {
    if (replacedRoot && !fs.existsSync(releaseRoot)) {
      fs.renameSync(replacedRoot, releaseRoot);
    }
    throw error;
  }
  return replacedRoot;
}

function currentRuntimePath(env = process.env) {
  return path.join(resolveRuntimeBase(env), "current");
}

function logicalCurrentRuntimeRoot(env = process.env) {
  const currentPath = currentRuntimePath(env);
  try {
    const stat = fs.lstatSync(currentPath);
    if (stat.isSymbolicLink() || stat.isDirectory()) return currentPath;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  return "";
}

function resolvedCurrentRuntimeRoot(env = process.env) {
  const currentPath = currentRuntimePath(env);
  const currentTarget = readLinkOrNull(currentPath);
  if (currentTarget) {
    return path.resolve(path.dirname(currentPath), currentTarget);
  }
  try {
    const stat = fs.statSync(currentPath);
    if (stat.isDirectory()) return currentPath;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  return "";
}

function previousRuntimePath(env = process.env) {
  return path.join(resolveRuntimeBase(env), "previous");
}

function hasCommand(name) {
  const result = spawnSync("command", ["-v", name], {
    shell: true,
    stdio: "ignore",
  });
  return result.status === 0;
}

function commandPath(name) {
  const result = spawnSync("command", ["-v", name], {
    shell: true,
    encoding: "utf8",
  });
  if (result.status !== 0) return "";
  return result.stdout.trim();
}

function pythonVersion(pythonBin) {
  if (!pythonBin) return null;
  const result = spawnSync(
    pythonBin,
    ["-c", "import sys,json; print(json.dumps({'version': sys.version.split()[0], 'major': sys.version_info[0], 'minor': sys.version_info[1]}))"],
    { encoding: "utf8" },
  );
  if (result.status !== 0) return null;
  try {
    return JSON.parse(result.stdout);
  } catch {
    return null;
  }
}

function pythonOk(version) {
  return Boolean(version && (version.major > 3 || (version.major === 3 && version.minor >= 10)));
}

function pythonVenvOk(pythonBin) {
  if (!pythonBin) return false;
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "openclaw-python-check-"));
  try {
    const result = spawnSync(pythonBin, ["-m", "venv", path.join(tempRoot, "venv")], {
      stdio: "ignore",
    });
    return result.status === 0;
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

function pythonProbe(pythonBin) {
  const version = pythonVersion(pythonBin);
  const version_ok = pythonOk(version);
  const venv_ok = version_ok ? pythonVenvOk(pythonBin) : false;
  return {
    path: pythonBin || "",
    version: version?.version || null,
    version_ok,
    venv_ok,
    ok: version_ok && venv_ok,
  };
}

function selectedPythonProbe() {
  const candidates = [];
  if (process.env.OPENCLAW_AGENT_WALLET_PYTHON) {
    candidates.push(process.env.OPENCLAW_AGENT_WALLET_PYTHON);
  } else {
    for (const name of ["python3.14", "python3.13", "python3.12", "python3.11", "python3.10", "python3"]) {
      const found = commandPath(name);
      if (found && !candidates.includes(found)) candidates.push(found);
    }
  }

  const probes = candidates.map((candidate) => pythonProbe(candidate));
  return probes.find((probe) => probe.ok) || probes[0] || pythonProbe("");
}

function readLinkOrNull(target) {
  try {
    const stat = fs.lstatSync(target);
    if (!stat.isSymbolicLink()) return null;
    return fs.readlinkSync(target);
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function listReleases(env = process.env) {
  const releasesDir = path.join(resolveRuntimeBase(env), "releases");
  try {
    return fs
      .readdirSync(releasesDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .map((entry) => entry.name)
      .sort();
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
}

function listFailedReleases(env = process.env) {
  const releasesDir = path.join(resolveRuntimeBase(env), "releases");
  try {
    return fs
      .readdirSync(releasesDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && entry.name.startsWith(".failed-"))
      .map((entry) => entry.name)
      .sort();
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
}

function activeVersion(env = process.env) {
  const current = currentRuntimePath(env);
  const link = readLinkOrNull(current);
  if (!link) return null;
  return path.basename(path.resolve(path.dirname(current), link));
}

function detectRuntimeVersion(runtimeRoot) {
  try {
    const packageJsonText = fs.readFileSync(path.join(runtimeRoot, "package.json"), "utf8");
    const pkg = JSON.parse(packageJsonText);
    return String(pkg.version || "").trim() || null;
  } catch {
    // ignored
  }
  try {
    const pyprojectText = fs.readFileSync(path.join(runtimeRoot, "agent-wallet", "pyproject.toml"), "utf8");
    const match = pyprojectText.match(/^version = "([^"]+)"/m);
    return match?.[1] || null;
  } catch {
    return null;
  }
}

function uniquePathWithSuffix(targetPath) {
  if (!fs.existsSync(targetPath)) return targetPath;
  let counter = 2;
  while (true) {
    const candidate = `${targetPath}-${counter}`;
    if (!fs.existsSync(candidate)) return candidate;
    counter += 1;
  }
}

function migrateDirectoryRuntimePointer(linkPath) {
  const stat = fs.lstatSync(linkPath);
  if (!stat.isDirectory()) return null;
  const runtimeBase = path.dirname(linkPath);
  const releasesDir = path.join(runtimeBase, "releases");
  fs.mkdirSync(releasesDir, { recursive: true });
  const detectedVersion = detectRuntimeVersion(linkPath);
  const baseName = detectedVersion ? `${detectedVersion}-migrated` : `legacy-current-${Date.now()}`;
  const destination = uniquePathWithSuffix(path.join(releasesDir, baseName));
  fs.renameSync(linkPath, destination);
  return destination;
}

function existingRuntimePointerTarget(linkPath) {
  const link = readLinkOrNull(linkPath);
  if (link) {
    return path.resolve(path.dirname(linkPath), link);
  }
  try {
    const stat = fs.lstatSync(linkPath);
    if (stat.isDirectory()) {
      return migrateDirectoryRuntimePointer(linkPath);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  return null;
}

function listDirectories(rootPath) {
  try {
    return fs
      .readdirSync(rootPath, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort();
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
}

function activePythonRuntimeInfo(env = process.env) {
  const currentRoot = resolvedCurrentRuntimeRoot(env);
  if (!currentRoot) return null;
  const linkPath = path.join(currentRoot, "agent-wallet", ".runtime-venv");
  const exists = fs.existsSync(linkPath);
  const symlinkTarget = readLinkOrNull(linkPath);
  const resolvedTarget = exists ? path.resolve(path.dirname(linkPath), symlinkTarget || ".") : null;
  return {
    link_path: linkPath,
    exists,
    symlink: Boolean(symlinkTarget),
    target: symlinkTarget || null,
    resolved_target: resolvedTarget,
    shared: Boolean(resolvedTarget && resolvedTarget.includes(`${path.sep}shared${path.sep}python${path.sep}`)),
  };
}

function activeNodeRuntimeInfo(env = process.env) {
  const currentRoot = resolvedCurrentRuntimeRoot(env);
  if (!currentRoot) return [];
  const projects = [
    path.join(currentRoot, "wdk-btc-wallet"),
    path.join(currentRoot, "wdk-evm-wallet"),
    path.join(currentRoot, "agent-wallet", "scripts", "flash-sdk-bridge"),
  ];
  return projects
    .filter((projectRoot) => fs.existsSync(path.join(projectRoot, "package.json")))
    .map((projectRoot) => {
      const linkPath = path.join(projectRoot, "node_modules");
      const exists = fs.existsSync(linkPath);
      const symlinkTarget = readLinkOrNull(linkPath);
      const resolvedTarget = exists ? path.resolve(path.dirname(linkPath), symlinkTarget || ".") : null;
      return {
        project_root: projectRoot,
        project_name: path.basename(projectRoot),
        link_path: linkPath,
        exists,
        symlink: Boolean(symlinkTarget),
        target: symlinkTarget || null,
        resolved_target: resolvedTarget,
        shared: Boolean(resolvedTarget && resolvedTarget.includes(`${path.sep}shared${path.sep}node${path.sep}`)),
      };
    });
}

function sharedSnapshotInventory(env = process.env) {
  const runtimeBase = resolveRuntimeBase(env);
  const sharedRoot = path.join(runtimeBase, "shared");
  const pythonRoot = path.join(sharedRoot, "python");
  const nodeRoot = path.join(sharedRoot, "node");
  const nodeProjects = listDirectories(nodeRoot).map((projectName) => ({
    project_name: projectName,
    snapshots: listDirectories(path.join(nodeRoot, projectName)),
  }));
  return {
    shared_root: sharedRoot,
    python_snapshots: listDirectories(pythonRoot),
    node_projects: nodeProjects,
  };
}

function switchSymlink(linkPath, targetPath) {
  const absoluteTarget = path.resolve(targetPath);
  if (!fs.existsSync(absoluteTarget)) {
    throw new Error(`Cannot switch runtime: target does not exist: ${absoluteTarget}`);
  }

  fs.mkdirSync(path.dirname(linkPath), { recursive: true });
  const tempLink = `${linkPath}.tmp-${process.pid}`;
  try {
    fs.rmSync(tempLink, { force: true, recursive: true });
  } catch {
    // ignored
  }
  fs.symlinkSync(absoluteTarget, tempLink, "dir");

  try {
    const existing = fs.lstatSync(linkPath);
    if (!existing.isSymbolicLink()) {
      fs.rmSync(tempLink, { force: true, recursive: true });
      throw new Error(`${linkPath} exists and is not a symlink. Refusing to replace it.`);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }

  fs.renameSync(tempLink, linkPath);
}

// Remove a runtime pointer symlink (current/previous). recursive+force tolerate
// a stray directory in that slot; on a symlink this unlinks the pointer only and
// never deletes the release directory it targets.
function removeRuntimePointer(pointerPath) {
  try {
    fs.rmSync(pointerPath, { recursive: true, force: true });
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function parseFlagValue(args, name) {
  const prefix = `${name}=`;
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (value === name) return args[index + 1] || "";
    if (value.startsWith(prefix)) return value.slice(prefix.length);
  }
  return "";
}

function hasFlag(args, name) {
  return args.includes(name) || args.some((value) => value.startsWith(`${name}=`));
}

function withoutCliOnlyArgs(args) {
  const output = [];
  for (let index = 0; index < args.length; index += 1) {
    const value = args[index];
    if (value === "--yes" || value === "--auto-secrets" || value === "--no-auto-secrets") {
      continue;
    }
    if (value === "--to") {
      index += 1;
      continue;
    }
    if (value.startsWith("--to=")) {
      continue;
    }
    output.push(value);
  }
  return output;
}

function extractTrailingJson(text) {
  const raw = String(text || "");
  const newlineStart = raw.lastIndexOf("\n{");
  const start = newlineStart >= 0 ? newlineStart + 1 : raw.indexOf("{");
  if (start < 0) {
    throw new Error("Could not find JSON payload in command output.");
  }
  return JSON.parse(raw.slice(start));
}

function pathVersionFromRuntimeRoot(runtimeRoot) {
  if (!runtimeRoot) return null;
  const normalized = path.resolve(String(runtimeRoot));
  if (path.basename(path.dirname(normalized)) !== "releases") return null;
  return path.basename(normalized);
}

function resolveCliPackageMeta(cliPath) {
  try {
    const root = path.resolve(path.dirname(cliPath), "..");
    const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
    return {
      name: String(pkg.name || packageJson.name),
      version: String(pkg.version || ""),
      root,
    };
  } catch {
    return {
      name: packageJson.name,
      version: "",
      root: "",
    };
  }
}

function summarizeDependencyPlan(payload) {
  const python = payload?.python_runtime && typeof payload.python_runtime === "object"
    ? {
        action: payload.python_runtime.action || "unknown",
        shared: Boolean(payload.python_runtime.shared),
        fingerprint: payload.python_runtime.fingerprint || null,
      }
    : null;
  const nodeProjects = Array.isArray(payload?.node_runtime?.projects)
    ? payload.node_runtime.projects.map((project) => ({
        project_root: project.project_root,
        action: project.action || "unknown",
        shared: Boolean(project.shared),
        fingerprint: project.fingerprint || null,
      }))
    : [];
  return { python, node_projects: nodeProjects };
}

function token() {
  return crypto.randomBytes(32).toString("base64url");
}

function envFileSet(pathname, updates) {
  fs.mkdirSync(path.dirname(pathname), { recursive: true });
  let lines = [];
  try {
    lines = fs.readFileSync(pathname, "utf8").split(/\r?\n/);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }

  const pending = new Map(Object.entries(updates));
  const next = [];
  for (const line of lines) {
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=/);
    if (!match || !pending.has(match[1])) {
      if (line.length > 0) next.push(line);
      continue;
    }
    next.push(`${match[1]}=${pending.get(match[1])}`);
    pending.delete(match[1]);
  }
  for (const [key, value] of pending) {
    next.push(`${key}=${value}`);
  }
  fs.writeFileSync(pathname, `${next.join("\n")}\n`, { mode: 0o600 });
  try {
    fs.chmodSync(pathname, 0o600);
  } catch {
    // chmod can fail on some filesystems; the write mode above is the primary path.
  }
}

function envFileUnset(pathname, keys) {
  let lines = [];
  try {
    lines = fs.readFileSync(pathname, "utf8").split(/\r?\n/);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
  const blocked = new Set(keys);
  const next = [];
  for (const line of lines) {
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=/);
    if (match && blocked.has(match[1])) {
      continue;
    }
    if (line.length > 0) next.push(line);
  }
  fs.writeFileSync(pathname, `${next.join("\n")}\n`, { mode: 0o600 });
  try {
    fs.chmodSync(pathname, 0o600);
  } catch {
    // ignored
  }
}

function readEnvFile(pathname) {
  try {
    const result = {};
    for (const line of fs.readFileSync(pathname, "utf8").split(/\r?\n/)) {
      const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
      if (match) result[match[1]] = match[2];
    }
    return result;
  } catch (error) {
    if (error?.code === "ENOENT") return {};
    throw error;
  }
}

function readJsonFile(pathname) {
  try {
    return JSON.parse(fs.readFileSync(pathname, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function writeJsonFile(pathname, value) {
  fs.mkdirSync(path.dirname(pathname), { recursive: true });
  fs.writeFileSync(pathname, `${JSON.stringify(value, null, 2)}\n`);
}

function writeJsonFileAtomic(pathname, value, mode = 0o600) {
  fs.mkdirSync(path.dirname(pathname), { recursive: true });
  const tempPath = `${pathname}.tmp-${process.pid}-${Date.now()}`;
  try {
    fs.writeFileSync(tempPath, `${JSON.stringify(value, null, 2)}\n`, { mode });
    fs.renameSync(tempPath, pathname);
    fs.chmodSync(pathname, mode);
  } finally {
    try {
      fs.rmSync(tempPath, { force: true });
    } catch {
      // ignored
    }
  }
}

function bootKeys(env = process.env) {
  return createBootKeyManager({
    runtimeBase: resolveRuntimeBase(env),
    openclawHome: resolveOpenclawHome(env),
    currentRuntimeRoot: () => resolvedCurrentRuntimeRoot(env),
    resolveVenvPython,
    expandHome,
    bridgeTimeoutMs: positiveIntEnv(
      "AGENT_WALLET_KEYSTORE_BRIDGE_TIMEOUT_MS",
      KEYSTORE_BRIDGE_TIMEOUT_MS,
      env,
    ),
    env,
  });
}

function ensureBootKeyFile(env = process.env) {
  return bootKeys(env).ensureFile();
}

function readBootKeyFromRuntimeResolver(env = process.env) {
  return bootKeys(env).resolveFromRuntime();
}

function resolveLegacyInstallerBootKey(env = process.env) {
  return bootKeys(env).resolveLegacy();
}

function provisionBootKeyToKeystore(releaseRoot, env, bootKey) {
  return bootKeys(env).provision(releaseRoot, bootKey);
}

function resolveVenvPython(releaseRoot) {
  const candidates = [
    path.join(releaseRoot, "agent-wallet", ".venv", "bin", "python"),
    path.join(releaseRoot, "agent-wallet", ".runtime-venv", "bin", "python"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

// Classify a verification failure so the caller can route the right guidance:
//   broken_release -> our shipped code is bad; user cannot fix, stay on previous.
//   local_env      -> user's machine/runtime is fixable (python/venv/corrupt unpack).
//   unknown        -> fall back to generic guidance.
function classifyVerifyError(detail) {
  const text = String(detail || "");
  if (/SyntaxError|IndentationError|ImportError|ModuleNotFoundError|TabError|NameError/.test(text)) {
    return "broken_release";
  }
  if (/ENOENT|python|venv|ensurepip|not found|No such file|Permission denied|spawn/i.test(text)) {
    return "local_env";
  }
  return "unknown";
}

function verifyRuntime(releaseRoot, env = process.env) {
  if (String(env.AGENT_WALLET_VERIFY_DISABLE || "") === "1") {
    return { ok: true, skipped: true };
  }
  if (String(env.AGENT_WALLET_VERIFY_FORCE_FAIL || "") === "1") {
    return { ok: false, error: "verify forced to fail (AGENT_WALLET_VERIFY_FORCE_FAIL)", category: "broken_release" };
  }
  const serverPy = path.join(releaseRoot, "codex", "plugins", "agent-wallet", "server.py");
  if (!fs.existsSync(serverPy)) {
    return { ok: false, error: `server.py missing at ${serverPy}`, category: "local_env" };
  }
  const python =
    env.AGENT_WALLET_PYTHON ||
    env.OPENCLAW_AGENT_WALLET_PYTHON ||
    resolveVenvPython(releaseRoot) ||
    commandPath("python3") ||
    "python3";
  const initLine = JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "verify", version: "0" } },
  });
  const probe = spawnSync(python, [serverPy], {
    input: initLine + "\n",
    encoding: "utf8",
    timeout: Number(env.AGENT_WALLET_VERIFY_TIMEOUT_MS || 25000),
    env: { ...env, FASTMCP_SHOW_SERVER_BANNER: "false", FASTMCP_LOG_LEVEL: "ERROR" },
  });
  if (probe.error) {
    const isTimeout = String(probe.error.message || "").includes("ETIMEDOUT");
    return {
      ok: false,
      error: `handshake ${isTimeout ? "timed out (server did not respond)" : "spawn failed"}: ${probe.error.message}`,
      category: isTimeout ? "broken_release" : "local_env",
    };
  }
  const out = String(probe.stdout || "");
  if (out.includes('"serverInfo"')) {
    return { ok: true };
  }
  const detail = (probe.stderr || out || "").trim().split("\n").slice(-3).join(" ");
  return {
    ok: false,
    error: `MCP initialize handshake failed: ${detail || "no serverInfo in response"}`,
    category: classifyVerifyError(detail),
  };
}

function verifyBootKeyWithRuntime(releaseRoot, env = process.env) {
  return bootKeys(env).verifyWithRuntime(releaseRoot);
}

function resolveEditorServerChecks(env = process.env) {
  const checks = [];
  // Claude Code's launcher (run_mcp.sh) falls back to the runtime codex
  // server.py when its own plugin-cache copy lacks one, so a present runtime
  // server.py is exactly what that launcher will exec. We check its presence
  // as the proxy for "Claude can resolve a server" (we do not inspect the
  // version-specific cache copy directly).
  const root = resolvedCurrentRuntimeRoot(env);
  const runtimeCodex = root ? path.join(root, "codex", "plugins", "agent-wallet", "server.py") : null;
  const claudeCacheRoot = expandHome("~/.claude/plugins/cache");
  if (fs.existsSync(claudeCacheRoot)) {
    const reachable = Boolean(runtimeCodex && fs.existsSync(runtimeCodex));
    checks.push({
      name: "editor:claude-code",
      ok: reachable,
      error: reachable ? "" : "Claude cache copy cannot resolve server.py from runtime",
      fix: reachable ? "" : "npx @agentlayer.tech/wallet claude-code install --yes",
    });
  }
  // Codex: plugin symlink target under the codex plugin install root.
  const codexInstallRoot = resolveCodexPluginInstallRoot(env);
  const codexTarget = path.join(codexInstallRoot, "agent-wallet", "server.py");
  if (fs.existsSync(codexInstallRoot)) {
    const ok = fs.existsSync(codexTarget);
    checks.push({
      name: "editor:codex",
      ok,
      error: ok ? "" : `codex plugin server.py missing at ${codexTarget}`,
      fix: ok ? "" : "npx @agentlayer.tech/wallet codex install --yes",
    });
  }
  return checks;
}

function runDoctor(args = []) {
  const deep = hasFlag(args, "--deep");
  const env = process.env;
  const checks = [];
  const fixInstall = "npx @agentlayer.tech/wallet install --yes";

  for (const command of ["node", "npm"]) {
    const ok = hasCommand(command);
    checks.push({
      name: `command:${command}`,
      ok,
      error: ok ? "" : `${command} not found on PATH`,
      fix: ok ? "" : `install ${command}`,
    });
  }
  const python = selectedPythonProbe();
  const pythonOk = Boolean(python.path && python.version_ok && python.venv_ok);
  checks.push({
    name: "python_version",
    ok: pythonOk,
    error: !python.path ? "python3 not found"
      : !python.version_ok ? `selected python ${python.version} < 3.10`
      : !python.venv_ok ? `python ${python.version} lacks venv/ensurepip` : "",
    fix: pythonOk ? "" : "install python>=3.10 with venv",
  });

  const currentPath = currentRuntimePath(env);
  const currentRoot = resolvedCurrentRuntimeRoot(env);
  const symlinkOk = Boolean(currentRoot && fs.existsSync(currentRoot));
  checks.push({
    name: "current_symlink",
    ok: symlinkOk,
    target: readLinkOrNull(currentPath),
    error: symlinkOk ? "" : `current does not resolve to an existing release (${currentPath})`,
    fix: symlinkOk ? "" : fixInstall,
  });

  const venvPython = currentRoot ? resolveVenvPython(currentRoot) : null;
  checks.push({
    name: "runtime_venv_python",
    ok: Boolean(venvPython),
    path: venvPython,
    error: venvPython ? "" : "runtime .runtime-venv/bin/python missing",
    fix: venvPython ? "" : fixInstall,
  });

  const serverPy = currentRoot
    ? path.join(currentRoot, "codex", "plugins", "agent-wallet", "server.py")
    : null;
  const serverExists = Boolean(serverPy && fs.existsSync(serverPy));
  let parseOk = false;
  if (serverExists && venvPython) {
    const compiled = spawnSync(venvPython, ["-m", "py_compile", serverPy], { encoding: "utf8" });
    parseOk = compiled.status === 0;
  }
  checks.push({
    name: "server_py_parses",
    ok: parseOk,
    error: !serverExists ? "runtime codex server.py missing"
      : !venvPython ? "server.py parse skipped (runtime venv missing)"
      : parseOk ? "" : "server.py present but failed to parse",
    fix: parseOk ? "" : fixInstall,
  });

  if (deep) {
    const verify = currentRoot
      ? verifyRuntime(currentRoot, env)
      : { ok: false, error: "no runtime to handshake", category: "local_env" };
    checks.push({
      name: "mcp_initialize_handshake",
      ok: verify.ok,
      error: verify.ok ? "" : verify.error,
      fix: verify.ok ? "" : `${fixInstall} (or: npx @agentlayer.tech/wallet rollback)`,
    });
  }

  for (const editorCheck of resolveEditorServerChecks(env)) {
    checks.push(editorCheck);
  }

  // Informational only: never flips doctor's overall ok. Surfaces a newer
  // published version when the background runtime check has cached one.
  const update = computeUpdateAvailability(env);
  checks.push({
    name: "update_available",
    ok: true,
    available: update.available,
    latest: update.latest,
    current: update.current,
    error: "",
    fix: update.available ? "npx @agentlayer.tech/wallet update --yes" : "",
  });

  // Informational only: flags when the installed runtime lags the CLI/repo
  // version (a local bump that was not reinstalled into the frameworks).
  const rsync = computeRuntimeInSync(env);
  checks.push({
    name: "runtime_in_sync",
    ok: true,
    in_sync: rsync.in_sync,
    active_version: rsync.active_version,
    cli_version: rsync.cli_version,
    error: "",
    fix: rsync.in_sync === false ? "npm run release:local" : "",
  });

  const integrationSync = integrationSyncStatus(env);
  checks.push({
    name: "framework_integrations_in_sync",
    ok: true,
    in_sync: integrationSync.in_sync,
    integrations: integrationSync.integrations,
    error: "",
    fix: integrationSync.in_sync ? "" : "wallet update --yes",
  });

  const recoveryStatus = updateRecoveryStatus(env);
  checks.push({
    name: "update_recovery_state",
    ok: true,
    ...recoveryStatus,
    error: "",
    fix: recoveryStatus.needs_recovery ? "wallet install --yes" : "",
  });

  const ok = checks.every((c) => c.ok);
  console.log(
    JSON.stringify(
      {
        schema_version: 1,
        ok,
        package_name: packageJson.name,
        package_version: packageVersion,
        openclaw_home: resolveOpenclawHome(),
        current_runtime: currentPath,
        active_version: activeVersion(),
        releases: listReleases(),
        deep,
        checks,
      },
      null,
      2,
    ),
  );
  return ok ? 0 : 1;
}

function runStatus(args = []) {
  const payload = {
    schema_version: 1,
    ok: true,
    package_name: packageJson.name,
    package_version: packageVersion,
    openclaw_home: resolveOpenclawHome(),
    runtime_base: resolveRuntimeBase(),
    current_runtime: currentRuntimePath(),
    previous_runtime: readLinkOrNull(previousRuntimePath()),
    active_version: activeVersion(),
    available_releases: listReleases(),
    failed_releases: listFailedReleases(),
    update_available: computeUpdateAvailability(),
    runtime_in_sync: computeRuntimeInSync(),
    framework_integrations: integrationSyncStatus(),
    update_recovery: updateRecoveryStatus(),
  };
  if (hasFlag(args, "--verbose")) {
    payload.verbose = true;
    payload.active_python_runtime = activePythonRuntimeInfo();
    payload.active_node_runtimes = activeNodeRuntimeInfo();
    payload.shared_snapshot_inventory = sharedSnapshotInventory();
  }
  console.log(JSON.stringify(payload, null, 2));
  return 0;
}

function buildInstallerEnv(args) {
  const env = { ...process.env };
  const sealedKeysPath = path.join(resolveOpenclawHome(env), "sealed_keys.json");
  const sealedKeysExist = fs.existsSync(sealedKeysPath);
  const dryRun = hasFlag(args, "--dry-run");
  let bootKeySource = env.AGENT_WALLET_BOOT_KEY ? "environment" : "none";
  const runtimeResolution = readBootKeyFromRuntimeResolver(env);
  if (runtimeResolution.supported) {
    bootKeySource = runtimeResolution.key ? "runtime_verified" : "runtime_rejected";
    if (runtimeResolution.key) {
      env.AGENT_WALLET_BOOT_KEY = runtimeResolution.key;
    } else {
      delete env.AGENT_WALLET_BOOT_KEY;
    }
  } else if (!env.AGENT_WALLET_BOOT_KEY) {
    const fallback = resolveLegacyInstallerBootKey(env);
    bootKeySource = fallback.source;
    if (fallback.key) env.AGENT_WALLET_BOOT_KEY = fallback.key;
  }

  const shouldGenerateSecrets =
    !dryRun &&
    !hasFlag(args, "--no-auto-secrets") &&
    (hasFlag(args, "--yes") || !env.AGENT_WALLET_BOOT_KEY);

  const generated = {};
  if (sealedKeysExist && shouldGenerateSecrets && !env.AGENT_WALLET_BOOT_KEY) {
    throw new Error(
      `Found ${sealedKeysPath}, but no AGENT_WALLET_BOOT_KEY was provided and no current runtime .env contains one. Refusing to generate a new boot key for existing sealed secrets.`,
    );
  }
  if (!sealedKeysExist && shouldGenerateSecrets && !env.AGENT_WALLET_BOOT_KEY) {
    generated.AGENT_WALLET_BOOT_KEY = token();
    env.AGENT_WALLET_BOOT_KEY = generated.AGENT_WALLET_BOOT_KEY;
    bootKeySource = "generated";
  }
  if (!sealedKeysExist && shouldGenerateSecrets && !env.AGENT_WALLET_MASTER_KEY) {
    generated.AGENT_WALLET_MASTER_KEY = token();
    env.AGENT_WALLET_MASTER_KEY = generated.AGENT_WALLET_MASTER_KEY;
  }
  if (!sealedKeysExist && shouldGenerateSecrets && !env.AGENT_WALLET_APPROVAL_SECRET) {
    generated.AGENT_WALLET_APPROVAL_SECRET = token();
    env.AGENT_WALLET_APPROVAL_SECRET = generated.AGENT_WALLET_APPROVAL_SECRET;
  }
  return { env, generated, bootKeySource };
}

function runInstallUnlocked(args, { commandName = "install" } = {}) {
  if (!fs.existsSync(setupPath)) {
    console.error(`Missing bundled setup.sh at ${setupPath}`);
    return 1;
  }

  const explicitRuntimeRoot = parseFlagValue(args, "--runtime-root");
  const releaseRoot = explicitRuntimeRoot
    ? path.resolve(expandHome(explicitRuntimeRoot))
    : releaseRootFor(packageVersion);
  const currentPath = currentRuntimePath();
  const previousPath = previousRuntimePath();
  const installerArgs = withoutCliOnlyArgs(args);
  const dryRun = hasFlag(args, "--dry-run");
  const recovery = dryRun
    ? { attempted: false, ok: true, reason: "dry run" }
    : recoverInterruptedUpdate(process.env);
  if (!recovery.ok) {
    console.error(`Could not recover interrupted update: ${recovery.reason || recovery.error}`);
    return 1;
  }
  const stagingRoot = !explicitRuntimeRoot && !dryRun ? stagingRootFor(packageVersion) : null;
  const installRoot = stagingRoot || releaseRoot;

  if (!hasFlag(installerArgs, "--runtime-root")) {
    installerArgs.push("--runtime-root", installRoot);
  }
  if (!hasFlag(installerArgs, "--install-from-runtime")) {
    installerArgs.push("--install-from-runtime");
  }

  let installerEnv;
  try {
    installerEnv = buildInstallerEnv(args);
  } catch (error) {
    console.error(error.message);
    return 1;
  }
  const { env, generated, bootKeySource } = installerEnv;
  if (stagingRoot) {
    env.OPENCLAW_INSTALL_FINAL_ROOT = releaseRoot;
    writeUpdateJournal(
      "preparing",
      {
        transaction_id: crypto.randomUUID(),
        staging_root: stagingRoot,
        release_root: releaseRoot,
        current_target_before: readLinkOrNull(currentPath),
        previous_target_before: readLinkOrNull(previousPath),
      },
      env,
    );
  }
  const result = spawnSync("sh", [setupPath, ...installerArgs], {
    cwd: packageRoot,
    stdio: "inherit",
    env,
  });

  if (result.error) {
    const failedRoot = failStagingRuntime(stagingRoot, result.error.message);
    if (!dryRun) {
      writeUpdateJournal("failed", { failed_runtime: failedRoot, error: result.error.message }, env);
    }
    console.error(result.error.message);
    return 1;
  }
  if ((result.status ?? 1) !== 0) {
    const failedRoot = failStagingRuntime(stagingRoot, `installer exited with ${result.status ?? 1}`);
    if (!dryRun) {
      writeUpdateJournal(
        "failed",
        { failed_runtime: failedRoot, error: `installer exited with ${result.status ?? 1}` },
        env,
      );
    }
    return result.status ?? 1;
  }

  if (dryRun) {
    return 0;
  }

  // Installs that pass --skip-python-setup may have no venv, so this handshake
  // would fail and trigger a spurious rollback; such flows must set
  // AGENT_WALLET_VERIFY_DISABLE=1 (verifyRuntime then skips).
  const currentTarget = existingRuntimePointerTarget(currentPath);
  const verification = verifyRuntime(installRoot, env);
  if (!verification.ok && !verification.skipped) {
    const failedRoot = failStagingRuntime(stagingRoot, verification.error);
    const rolledBack = Boolean(currentTarget);
    const previousVersion = rolledBack
      ? path.basename(currentTarget)
      : null;

    let human;
    let fix;
    if (!rolledBack) {
      human =
        verification.category === "broken_release"
          ? `Release ${packageVersion} is broken and there is no previous working version to fall back to. Nothing is active. This is a bad release — please report it; a patched version will follow.`
          : `Release ${packageVersion} failed to verify and there is no previous version. Your local environment looks incomplete: ${verification.error}.`;
      fix =
        verification.category === "local_env"
          ? "Ensure python>=3.10 with venv is installed, then: npx @agentlayer.tech/wallet install --yes"
          : "npx @agentlayer.tech/wallet install --version <known-good-version> --yes";
    } else if (verification.category === "broken_release") {
      human = `Release ${packageVersion} is broken; kept you on the working version ${previousVersion}. This is on our side — you are safe. Re-run update when a patched release ships.`;
      fix = "npx @agentlayer.tech/wallet update --yes";
    } else if (verification.category === "local_env") {
      human = `Release ${packageVersion} could not start on this machine; kept you on ${previousVersion}. This looks fixable locally: ${verification.error}.`;
      fix = "Fix python>=3.10/venv, then: npx @agentlayer.tech/wallet install --yes";
    } else {
      human = `Release ${packageVersion} failed verification; kept you on ${previousVersion}.`;
      fix = "npx @agentlayer.tech/wallet doctor --deep  (then install --yes once resolved)";
    }

    console.error(
      JSON.stringify(
        {
          ok: false,
          command: commandName,
          version: packageVersion,
          category: verification.category || "unknown",
          error: `runtime verification failed: ${verification.error}`,
          rolled_back: rolledBack,
          switched_current: false,
          kept_version: previousVersion,
          failed_runtime: failedRoot,
          current_runtime_target: readLinkOrNull(currentPath),
          message: human,
          fix,
        },
        null,
        2,
      ),
    );
    writeUpdateJournal(
      "failed",
      { failed_runtime: failedRoot, error: verification.error, kept_version: previousVersion },
      env,
    );
    return 1;
  }

  const bootKeyVerification = verifyBootKeyWithRuntime(installRoot, env);
  if (!bootKeyVerification.ok) {
    const failedRoot = failStagingRuntime(stagingRoot, bootKeyVerification.error);
    writeUpdateJournal(
      "failed",
      { failed_runtime: failedRoot, error: bootKeyVerification.error },
      env,
    );
    console.error(
      JSON.stringify(
        {
          ok: false,
          command: commandName,
          version: packageVersion,
          category: "boot_key_rejected",
          error: bootKeyVerification.error,
          switched_current: false,
          failed_runtime: failedRoot,
          current_runtime_target: readLinkOrNull(currentPath),
          fix: "Remove stale AGENT_WALLET_BOOT_KEY overrides and retry the update.",
        },
        null,
        2,
      ),
    );
    return 1;
  }

  if (env.AGENT_WALLET_BOOT_KEY) {
    const envPath = path.join(installRoot, "agent-wallet", ".env");
    // Prefer the OS keystore: provision the boot key there and keep the plaintext
    // out of the release .env entirely. Only fall back to the legacy .env write when
    // no keystore round-trip is possible, so the runtime can still resolve the key.
    if (provisionBootKeyToKeystore(installRoot, env, env.AGENT_WALLET_BOOT_KEY)) {
      envFileUnset(envPath, ["AGENT_WALLET_BOOT_KEY"]);
    } else {
      envFileSet(envPath, {
        AGENT_WALLET_BOOT_KEY: env.AGENT_WALLET_BOOT_KEY,
      });
    }
  }

  writeReleaseState(installRoot, "verified", {
    verification_skipped: Boolean(verification.skipped),
  });
  writeUpdateJournal(
    "verified",
    { ...readUpdateJournal(env), staging_root: stagingRoot, release_root: releaseRoot },
    env,
  );

  let replacedRoot = null;
  try {
    replacedRoot = fs.existsSync(releaseRoot)
      ? uniquePathWithSuffix(
          path.join(path.dirname(releaseRoot), `${path.basename(releaseRoot)}-replaced`),
        )
      : null;
    writeUpdateJournal(
      "committing",
      {
        ...readUpdateJournal(env),
        staging_root: stagingRoot,
        release_root: releaseRoot,
        replaced_root: replacedRoot,
        current_target_before: readLinkOrNull(currentPath),
        previous_target_before: readLinkOrNull(previousPath),
      },
      env,
    );
    replacedRoot = commitStagedRuntime(stagingRoot, releaseRoot, replacedRoot, env);
  } catch (error) {
    const failedRoot = failStagingRuntime(stagingRoot, error.message);
    writeUpdateJournal("failed", { failed_runtime: failedRoot, error: error.message }, env);
    console.error(`Could not commit staged runtime: ${error.message}`);
    return 1;
  }

  const previousTarget =
    currentTarget && path.resolve(currentTarget) === path.resolve(releaseRoot) && replacedRoot
      ? replacedRoot
      : currentTarget;
  if (previousTarget) {
    switchSymlink(previousPath, previousTarget);
  }
  switchSymlink(currentPath, releaseRoot);
  writeUpdateJournal(
    "committed",
    { ...readUpdateJournal(env), release_root: releaseRoot, previous_runtime: previousTarget },
    env,
  );

  recordManagedIntegration(
    "openclaw",
    {
      config_path: path.resolve(
        expandHome(parseFlagValue(args, "--config-path") || path.join(resolveOpenclawHome(env), "openclaw.json")),
      ),
      extension_path: path.join(currentPath, ".openclaw", "extensions", "agent-wallet"),
      package_root: path.join(currentPath, "agent-wallet"),
    },
    env,
  );

  const integrationRefresh = repairInstalledEditorIntegrations(env);
  const globalCliRefresh = safelyRefreshIntegration(
    "global-cli",
    () => refreshGlobalCliIfNeeded(env),
  );

  const pythonInfo = activePythonRuntimeInfo(env);
  const nodeInfo = activeNodeRuntimeInfo(env)
    .map((item) => `${item.project_name}:${item.shared ? "shared" : item.exists ? "local" : "missing"}`)
    .join(", ");
  console.error(
    `Update summary: version=${packageVersion} active=${activeVersion(env) || packageVersion} python=${pythonInfo?.shared ? "shared" : pythonInfo?.exists ? "local" : "missing"} node=[${nodeInfo}]`,
  );

  console.error(
    JSON.stringify(
      {
        ok: true,
        command: commandName,
        version: packageVersion,
        runtime_root: releaseRoot,
        current_runtime: currentPath,
        previous_runtime: readLinkOrNull(previousPath),
        generated_runtime_secrets: Object.keys(generated),
        boot_key_source: bootKeySource,
        staged: Boolean(stagingRoot),
        release_state: "verified",
        recovery,
        integration_refresh: integrationRefresh,
        global_cli_refresh: globalCliRefresh,
      },
      null,
      2,
    ),
  );
  return 0;
}

function runInstall(args, options = {}) {
  if (hasFlag(args, "--dry-run")) return runInstallUnlocked(args, options);
  const lock = acquireUpdateLock(process.env);
  if (!lock.ok) {
    console.error(
      JSON.stringify(
        {
          ok: false,
          category: "update_locked",
          error: "Another wallet install or update is already running.",
          lock_path: lock.path,
          lock_owner: lock.owner,
          fix: "Wait for the active update to finish, then retry.",
        },
        null,
        2,
      ),
    );
    return 1;
  }
  try {
    holdUpdateLockForTest(process.env);
    return runInstallUnlocked(args, options);
  } finally {
    releaseUpdateLock(lock);
  }
}

function resolveUpdatePackageSpec(env = process.env) {
  const explicit = String(env[UPDATE_PACKAGE_SPEC_ENV] || "").trim();
  if (explicit) return explicit;
  return `${packageJson.name}@latest`;
}

function runDelegatedInstallForUpdate(args, { captureOutput = false } = {}) {
  const localCliPath = String(process.env[UPDATE_CLI_PATH_ENV] || "").trim();
  if (localCliPath) {
    const meta = resolveCliPackageMeta(localCliPath);
    const result = spawnSync("node", [localCliPath, "install", ...args], {
      cwd: packageRoot,
      stdio: captureOutput ? "pipe" : "inherit",
      encoding: captureOutput ? "utf8" : undefined,
      env: process.env,
    });
    return {
      result,
      delegated_via: "cli_path",
      target_package_spec: meta.name || packageJson.name,
      target_version_hint: meta.version || null,
    };
  }

  const npmBin = commandPath("npm");
  if (!npmBin) {
    throw new Error("npm is required for `wallet update`. Install npm or run `npx @agentlayer.tech/wallet install --yes`.");
  }

  const packageSpec = resolveUpdatePackageSpec();
  const binCommand = primaryBinCommand();
  const result = spawnSync(
    npmBin,
    ["exec", "--yes", `--package=${packageSpec}`, binCommand, "--", "install", ...args],
    {
      cwd: packageRoot,
      stdio: captureOutput ? "pipe" : "inherit",
      encoding: captureOutput ? "utf8" : undefined,
      env: process.env,
    },
  );
  return {
    result,
    delegated_via: "npm_exec",
    target_package_spec: packageSpec,
    target_version_hint: null,
  };
}

function runUpdate(args) {
  const dryRun = hasFlag(args, "--dry-run");
  if (dryRun) {
    try {
      const delegated = runDelegatedInstallForUpdate(args, { captureOutput: true });
      const { result } = delegated;
      if (result.error) {
        console.error(result.error.message);
        return 1;
      }
      if ((result.status ?? 1) !== 0) {
        const stderr = String(result.stderr || "").trim();
        const stdout = String(result.stdout || "").trim();
        if (stderr) process.stderr.write(`${stderr}\n`);
        if (stdout) process.stdout.write(`${stdout}\n`);
        return result.status ?? 1;
      }
      const payload = extractTrailingJson(result.stdout || "");
      const targetVersion =
        delegated.target_version_hint ||
        pathVersionFromRuntimeRoot(payload.runtime_root) ||
        null;
      console.log(
        JSON.stringify(
          {
            ok: true,
            command: "update",
            dry_run: true,
            current_version: activeVersion(),
            installed_cli_version: packageVersion,
            target_package_spec: delegated.target_package_spec,
            target_version: targetVersion,
            delegated_via: delegated.delegated_via,
            runtime_base: resolveRuntimeBase(),
            current_runtime: currentRuntimePath(),
            target_runtime_root: payload.runtime_root,
            dependency_plan: summarizeDependencyPlan(payload),
            install_plan: payload,
          },
          null,
          2,
        ),
      );
      return 0;
    } catch (error) {
      console.error(error.message);
      return 1;
    }
  }

  const currentVersionBefore = activeVersion();
  let delegated;
  try {
    delegated = runDelegatedInstallForUpdate(args, { captureOutput: true });
  } catch (error) {
    console.error(error.message);
    return 1;
  }
  if (delegated.result.error) {
    console.error(delegated.result.error.message);
    return 1;
  }
  const { result } = delegated;
  if ((result.status ?? 1) !== 0) {
    const stderr = String(result.stderr || "").trim();
    const stdout = String(result.stdout || "").trim();
    if (stderr) process.stderr.write(`${stderr}\n`);
    if (stdout) process.stderr.write(`${stdout}\n`);
    return result.status ?? 1;
  }

  let installPayload;
  try {
    installPayload = extractTrailingJson(result.stderr || "") || extractTrailingJson(result.stdout || "");
  } catch {
    try {
      installPayload = extractTrailingJson(result.stdout || "");
    } catch (error) {
      const stderr = String(result.stderr || "").trim();
      const stdout = String(result.stdout || "").trim();
      if (stderr) process.stderr.write(`${stderr}\n`);
      if (stdout) process.stderr.write(`${stdout}\n`);
      console.error(error.message);
      return 1;
    }
  }

  const stderr = String(result.stderr || "");
  const summaryLine = stderr
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .find((line) => line.startsWith("Update summary:"));
  if (summaryLine) {
    console.error(summaryLine);
  }

  console.log(
    JSON.stringify(
      {
        ...installPayload,
        command: "update",
        delegated_via: delegated.delegated_via,
        target_package_spec: delegated.target_package_spec,
        target_version:
          delegated.target_version_hint ||
          pathVersionFromRuntimeRoot(installPayload?.runtime_root) ||
          installPayload?.version ||
          null,
        previous_version: currentVersionBefore,
        active_version: activeVersion(),
      },
      null,
      2,
    ),
  );
  return 0;
}

function runRollback(args) {
  const requested = parseFlagValue(args, "--to");
  const current = activeVersion();
  let target = "";
  if (requested) {
    target = releaseRootFor(requested);
  } else {
    const previous = readLinkOrNull(previousRuntimePath());
    if (previous) target = path.resolve(path.dirname(previousRuntimePath()), previous);
  }

  if (!target) {
    console.error("No previous runtime is recorded. Pass --to <version> to choose a release.");
    return 1;
  }
  if (!fs.existsSync(target)) {
    console.error(`Rollback target does not exist: ${target}`);
    return 1;
  }

  const currentPath = currentRuntimePath();
  if (current) {
    switchSymlink(previousRuntimePath(), releaseRootFor(current));
  }
  switchSymlink(currentPath, target);
  console.log(
    JSON.stringify(
      {
        ok: true,
        active_version: activeVersion(),
        current_runtime: currentPath,
      },
      null,
      2,
    ),
  );
  return 0;
}

function resolveHermesPluginSource() {
  const currentRoot = logicalCurrentRuntimeRoot();
  const candidates = [];
  if (currentRoot) {
    candidates.push(path.join(currentRoot, "hermes", "plugins", "agent_wallet"));
  }
  candidates.push(path.join(packageRoot, "hermes", "plugins", "agent_wallet"));
  for (const source of candidates) {
    if (fs.existsSync(path.join(source, "plugin.yaml"))) {
      return source;
    }
  }
  throw new Error(`Missing Hermes plugin bundle. Checked: ${candidates.join(", ")}`);
}

function resolveCodexPluginSource() {
  // test/CI override: inject a staged bundle dir
  const override = String(process.env.AGENT_WALLET_CODEX_PLUGIN_SOURCE || "").trim();
  if (override) return path.resolve(expandHome(override));
  const currentRoot = logicalCurrentRuntimeRoot();
  const candidates = [];
  if (currentRoot) {
    candidates.push(path.join(currentRoot, "codex", "plugins", "agent-wallet"));
  }
  candidates.push(path.join(packageRoot, "codex", "plugins", "agent-wallet"));
  for (const source of candidates) {
    if (fs.existsSync(path.join(source, ".codex-plugin", "plugin.json"))) {
      return source;
    }
  }
  throw new Error(`Missing Codex plugin bundle. Checked: ${candidates.join(", ")}`);
}

function resolveClaudeCodePluginSource() {
  // test/CI override: inject a staged bundle dir
  const override = String(process.env.AGENT_WALLET_CLAUDE_CODE_PLUGIN_SOURCE || "").trim();
  if (override) return path.resolve(expandHome(override));
  const currentRoot = logicalCurrentRuntimeRoot();
  const candidates = [];
  if (currentRoot) {
    candidates.push(path.join(currentRoot, "claude-code", "plugins", "agent-wallet"));
  }
  candidates.push(path.join(packageRoot, "claude-code", "plugins", "agent-wallet"));
  for (const source of candidates) {
    if (fs.existsSync(path.join(source, ".claude-plugin", "plugin.json"))) {
      return source;
    }
  }
  throw new Error(`Missing Claude Code plugin bundle. Checked: ${candidates.join(", ")}`);
}

function resolveCodexPluginInstallRoot(env = process.env) {
  return path.resolve(expandHome(env.AGENT_WALLET_CODEX_PLUGIN_ROOT || "~/plugins"));
}

function resolveCodexMarketplacePath(env = process.env) {
  return path.resolve(
    expandHome(env.AGENT_WALLET_CODEX_MARKETPLACE_PATH || "~/.agents/plugins/marketplace.json"),
  );
}

function ensureCodexMarketplaceEntry({ marketplacePath, pluginName }) {
  const existing = readJsonFile(marketplacePath);
  const payload = existing && typeof existing === "object"
    ? existing
    : {
        name: "local",
        interface: {
          displayName: "Local Plugins",
        },
        plugins: [],
      };

  if (typeof payload.name !== "string" || !payload.name.trim()) {
    payload.name = "local";
  }
  if (!payload.interface || typeof payload.interface !== "object") {
    payload.interface = { displayName: "Local Plugins" };
  }
  if (typeof payload.interface.displayName !== "string" || !payload.interface.displayName.trim()) {
    payload.interface.displayName = "Local Plugins";
  }
  if (!Array.isArray(payload.plugins)) {
    payload.plugins = [];
  }

  const entry = {
    name: pluginName,
    source: {
      source: "local",
      path: `./plugins/${pluginName}`,
    },
    policy: {
      installation: "AVAILABLE",
      authentication: "ON_INSTALL",
    },
    category: "Coding",
  };
  const index = payload.plugins.findIndex((item) => item && item.name === pluginName);
  if (index >= 0) {
    payload.plugins[index] = entry;
  } else {
    payload.plugins.push(entry);
  }
  writeJsonFile(marketplacePath, payload);
  return {
    marketplace_name: payload.name,
    marketplace_path: marketplacePath,
    entry,
  };
}

function resolveAgentWalletPackageRoot(env = process.env) {
  const currentRoot = logicalCurrentRuntimeRoot(env);
  if (currentRoot) {
    const runtimePackage = path.join(currentRoot, "agent-wallet");
    if (fs.existsSync(path.join(runtimePackage, "agent_wallet", "__init__.py"))) {
      return runtimePackage;
    }
  }
  return path.join(packageRoot, "agent-wallet");
}

function resolveAgentWalletPython(packageRootPath) {
  for (const candidate of [
    process.env.AGENT_WALLET_PYTHON,
    process.env.OPENCLAW_AGENT_WALLET_PYTHON,
    path.join(packageRootPath, ".venv", "bin", "python"),
    path.join(packageRootPath, ".runtime-venv", "bin", "python"),
    commandPath("python3"),
  ]) {
    if (!candidate) continue;
    if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) continue;
    return candidate;
  }
  return "python3";
}

function runHermesInstall(args) {
  const hermesHome = resolveHermesHome();
  const userPluginsDir = path.join(hermesHome, "plugins");
  const pluginSource = resolveHermesPluginSource();
  const pluginTarget = path.join(userPluginsDir, "agent_wallet");
  const force = hasFlag(args, "--force");
  const skipEnable = hasFlag(args, "--skip-enable");
  const hermesBin = commandPath("hermes");
  const agentWalletPackageRoot = resolveAgentWalletPackageRoot();
  const agentWalletPython = resolveAgentWalletPython(agentWalletPackageRoot);
  const hermesEnvPath = path.join(hermesHome, ".env");
  const existingHermesEnv = readEnvFile(hermesEnvPath);
  const bootKeyFile = ensureBootKeyFile({ ...process.env, ...existingHermesEnv });

  fs.mkdirSync(userPluginsDir, { recursive: true });
  try {
    const existing = fs.lstatSync(pluginTarget);
    if (!existing.isSymbolicLink()) {
      if (!force) {
        throw new Error(`${pluginTarget} exists and is not a symlink. Pass --force to replace it.`);
      }
      fs.rmSync(pluginTarget, { recursive: true, force: true });
    } else {
      fs.unlinkSync(pluginTarget);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  fs.symlinkSync(pluginSource, pluginTarget, "dir");

  envFileSet(hermesEnvPath, {
    AGENT_WALLET_PACKAGE_ROOT: agentWalletPackageRoot,
    AGENT_WALLET_PYTHON: agentWalletPython,
    AGENT_WALLET_BOOT_KEY_FILE: bootKeyFile.path,
  });
  if (bootKeyFile.status !== "missing") {
    envFileUnset(hermesEnvPath, ["AGENT_WALLET_BOOT_KEY"]);
  }

  let enable = { attempted: false, ok: false, skipped: skipEnable, error: "" };
  if (!skipEnable) {
    if (!hermesBin) {
      enable = {
        attempted: false,
        ok: false,
        skipped: false,
        error: "Hermes CLI was not found on PATH. Run `hermes plugins enable agent-wallet` after installing Hermes.",
      };
    } else {
      const result = spawnSync(hermesBin, ["plugins", "enable", "agent-wallet"], {
        cwd: packageRoot,
        encoding: "utf8",
        env: { ...process.env, HERMES_HOME: hermesHome },
      });
      enable = {
        attempted: true,
        ok: result.status === 0,
        skipped: false,
        error: result.status === 0 ? "" : (result.stderr || result.stdout || "").trim(),
      };
    }
  }

  recordManagedIntegration("hermes", {
    hermes_home: hermesHome,
    plugin_target: pluginTarget,
    env_path: hermesEnvPath,
    restart_required: true,
    ...(enable.skipped ? {} : { registration_ok: enable.ok }),
  });

  console.log(
    JSON.stringify(
      {
        ok: enable.skipped || enable.ok,
        hermes_home: hermesHome,
        plugin_source: pluginSource,
        plugin_target: pluginTarget,
        env_path: hermesEnvPath,
        agent_wallet_package_root: agentWalletPackageRoot,
        agent_wallet_python: agentWalletPython,
        boot_key_file: bootKeyFile.path,
        boot_key_file_status: bootKeyFile.status,
        hermes_enable: enable,
        restart_required: true,
      },
      null,
      2,
    ),
  );
  return enable.skipped || enable.ok ? 0 : 1;
}

function runCodexInstall(args) {
  const codexHome = resolveCodexHome();
  const pluginSource = resolveCodexPluginSource();
  const pinnedEnv = { pinned: false, reason: "plugin source is immutable" };
  const pluginRoot = resolveCodexPluginInstallRoot();
  const pluginTarget = path.join(pluginRoot, "agent-wallet");
  const marketplacePath = resolveCodexMarketplacePath();
  const force = hasFlag(args, "--force");
  const skipEnable = hasFlag(args, "--skip-enable");
  const codexBin = commandPath("codex");

  fs.mkdirSync(pluginRoot, { recursive: true });
  try {
    const existing = fs.lstatSync(pluginTarget);
    if (!existing.isSymbolicLink()) {
      if (!force) {
        throw new Error(`${pluginTarget} exists and is not a symlink. Pass --force to replace it.`);
      }
      fs.rmSync(pluginTarget, { recursive: true, force: true });
    } else {
      fs.unlinkSync(pluginTarget);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  fs.symlinkSync(pluginSource, pluginTarget, "dir");

  const marketplace = ensureCodexMarketplaceEntry({
    marketplacePath,
    pluginName: "agent-wallet",
  });

  let add = { attempted: false, ok: false, skipped: skipEnable, error: "" };
  if (!skipEnable) {
    if (!codexBin) {
      add = {
        attempted: false,
        ok: false,
        skipped: false,
        error: "Codex CLI was not found on PATH. Run `codex plugin add agent-wallet@local` after installing Codex.",
      };
    } else {
      const result = spawnSync(
        codexBin,
        ["plugin", "add", `agent-wallet@${marketplace.marketplace_name}`],
        {
          cwd: packageRoot,
          encoding: "utf8",
          env: {
            ...process.env,
            CODEX_HOME: codexHome,
          },
        },
      );
      add = {
        attempted: true,
        ok: result.status === 0,
        skipped: false,
        error: result.status === 0 ? "" : (result.stderr || result.stdout || "").trim(),
      };
    }
  }

  recordManagedIntegration("codex", {
    codex_home: codexHome,
    plugin_target: pluginTarget,
    marketplace_path: marketplace.marketplace_path,
    marketplace_name: marketplace.marketplace_name,
    restart_required: true,
    ...(add.skipped ? {} : { registration_ok: add.ok }),
  });

  console.log(
    JSON.stringify(
      {
        ok: add.skipped || add.ok,
        codex_home: codexHome,
        plugin_source: pluginSource,
        plugin_target: pluginTarget,
        marketplace_path: marketplace.marketplace_path,
        marketplace_name: marketplace.marketplace_name,
        codex_add: add,
        restart_required: true,
        pinned_env: pinnedEnv,
      },
      null,
      2,
    ),
  );
  return add.skipped || add.ok ? 0 : 1;
}

const CLAUDE_CODE_MARKETPLACE_NAME = "agentlayer-local";

function resolveClaudeCodeMarketplaceDir(env = process.env) {
  return path.resolve(
    expandHome(env.AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR || "~/.claude/agentlayer-local"),
  );
}

// Pin OPENCLAW_HOME into one .mcp.json so run_mcp.sh uses the install-time home
// instead of re-deriving the ~/.openclaw default. We deliberately do NOT pin
// AGENT_WALLET_PYTHON: the launcher resolves the venv from OPENCLAW_HOME->current
// dynamically, so a pinned python would go stale (and wrongly win) after upgrade.
function pinHomeIntoMcpFile(mcpPath, env = process.env) {
  if (!fs.existsSync(mcpPath)) return { pinned: false, reason: "no .mcp.json", path: mcpPath };
  let doc;
  try {
    doc = JSON.parse(fs.readFileSync(mcpPath, "utf8"));
  } catch (error) {
    return { pinned: false, reason: `unreadable .mcp.json: ${error.message}`, path: mcpPath };
  }
  const entry = (doc.mcpServers || {})["agent-wallet"];
  if (!entry) return { pinned: false, reason: "no agent-wallet server entry", path: mcpPath };
  const home = resolveOpenclawHome(env);
  // When the install home is the default ~/.openclaw, run_mcp.sh already derives
  // it (`${OPENCLAW_HOME:-"$HOME/.openclaw"}`), so pinning is redundant and would
  // dirty version-controlled bundle files. Skip it — and drop any stale pin so the
  // file self-heals back to a clean, distributable state.
  const defaultHome = path.resolve(expandHome("~/.openclaw"));
  if (home === defaultHome) {
    if (entry.env && "OPENCLAW_HOME" in entry.env) {
      delete entry.env.OPENCLAW_HOME;
      if (Object.keys(entry.env).length === 0) delete entry.env;
      writeJsonFile(mcpPath, doc);
      return { pinned: false, reason: "home is default; removed redundant pin", path: mcpPath };
    }
    return { pinned: false, reason: "home is default; run_mcp.sh derives it", path: mcpPath };
  }
  entry.env = { ...(entry.env || {}), OPENCLAW_HOME: home };
  writeJsonFile(mcpPath, doc);
  return { pinned: true, openclaw_home: home, path: mcpPath };
}

// Claude Code copies the plugin into a version-keyed cache and reads THAT copy,
// so the bundle pin alone is ineffective once a cache exists. Pin every cached
// copy too. Cache root is overridable for tests.
function pinClaudeCacheCopies(env = process.env) {
  const cacheRoot = path.resolve(
    expandHome(env.AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT || "~/.claude/plugins/cache"),
  );
  const pluginCacheDir = path.join(cacheRoot, CLAUDE_CODE_MARKETPLACE_NAME, "agent-wallet");
  const results = [];
  if (!fs.existsSync(pluginCacheDir)) return results;
  let versions;
  try {
    versions = fs.readdirSync(pluginCacheDir);
  } catch {
    return results;
  }
  for (const version of versions) {
    const mcpPath = path.join(pluginCacheDir, version, ".mcp.json");
    if (fs.existsSync(mcpPath)) results.push(pinHomeIntoMcpFile(mcpPath, env));
  }
  return results;
}

function ensureClaudeCodeMarketplace(marketplaceDir, pluginSource, force) {
  const pluginsDir = path.join(marketplaceDir, "plugins");
  const pluginLink = path.join(pluginsDir, "agent-wallet");
  const manifestDir = path.join(marketplaceDir, ".claude-plugin");
  const manifestPath = path.join(manifestDir, "marketplace.json");

  fs.mkdirSync(pluginsDir, { recursive: true });
  fs.mkdirSync(manifestDir, { recursive: true });

  // Symlink plugin source into marketplace plugins dir.
  try {
    const existing = fs.lstatSync(pluginLink);
    if (!existing.isSymbolicLink()) {
      if (!force) {
        throw new Error(
          `${pluginLink} exists and is not a symlink. Pass --force to replace it.`,
        );
      }
      fs.rmSync(pluginLink, { recursive: true, force: true });
    } else {
      fs.unlinkSync(pluginLink);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  fs.symlinkSync(pluginSource, pluginLink, "dir");

  // Write marketplace manifest (Claude Code requires owner + plugins[].source as relative path).
  const manifest = {
    name: CLAUDE_CODE_MARKETPLACE_NAME,
    description: "Local AgentLayer plugins",
    owner: { name: "AgentLayer" },
    plugins: [
      {
        name: "agent-wallet",
        displayName: "Agent Wallet",
        description:
          "Bridge to the existing local AgentLayer wallet runtime (Solana, Bitcoin, EVM).",
        category: "development",
        source: "./plugins/agent-wallet",
      },
    ],
  };
  writeJsonFile(manifestPath, manifest);
  return { pluginLink, manifestPath };
}

function runClaudeCodeInstall(args) {
  const pluginSource = resolveClaudeCodePluginSource();
  const pinnedEnv = { pinned: false, reason: "plugin source is immutable" };
  const force = hasFlag(args, "--force");
  const skipEnable = hasFlag(args, "--skip-enable");
  const claudeBin = commandPath("claude");
  const marketplaceDir = resolveClaudeCodeMarketplaceDir();

  const { pluginLink } = ensureClaudeCodeMarketplace(marketplaceDir, pluginSource, force);

  const pluginDirFlag = `claude --plugin-dir ${pluginLink}`;

  // Without the Claude CLI we can only set up the files; the user must register manually.
  let marketplaceAdd = { attempted: false, ok: false, skipped: skipEnable, error: "" };
  let enable = { attempted: false, ok: false, skipped: skipEnable, error: "" };

  if (!skipEnable) {
    if (!claudeBin) {
      const msg =
        "Claude Code CLI was not found on PATH. Load the plugin manually with: " + pluginDirFlag;
      marketplaceAdd = { attempted: false, ok: false, skipped: false, error: msg };
      enable = { attempted: false, ok: false, skipped: false, error: msg };
    } else {
      // Register the local marketplace (idempotent — safe to re-run).
      const addResult = spawnSync(
        claudeBin,
        ["plugin", "marketplace", "add", marketplaceDir, "--scope", "user"],
        { encoding: "utf8", stdio: "pipe" },
      );
      marketplaceAdd = {
        attempted: true,
        ok: addResult.status === 0,
        skipped: false,
        error: addResult.status === 0 ? "" : (addResult.stderr || addResult.stdout || "").trim(),
      };

      if (marketplaceAdd.ok) {
        // Install plugin from the now-registered local marketplace.
        const installResult = spawnSync(
          claudeBin,
          ["plugin", "install", `agent-wallet@${CLAUDE_CODE_MARKETPLACE_NAME}`, "--scope", "user"],
          { encoding: "utf8", stdio: "pipe" },
        );
        enable = {
          attempted: true,
          ok: installResult.status === 0,
          skipped: false,
          error:
            installResult.status === 0
              ? ""
              : (installResult.stderr || installResult.stdout || "").trim(),
        };
      } else {
        enable = {
          attempted: false,
          ok: false,
          skipped: false,
          error: "Skipped plugin install because marketplace registration failed.",
        };
      }
    }
  }

  recordManagedIntegration("claude-code", {
    marketplace_dir: marketplaceDir,
    plugin_target: pluginLink,
    cache_root: path.resolve(
      expandHome(process.env.AGENT_WALLET_CLAUDE_CODE_CACHE_ROOT || "~/.claude/plugins/cache"),
    ),
    restart_required: true,
    ...(enable.skipped ? {} : { registration_ok: enable.ok }),
  });

  const ok = enable.skipped || enable.ok;
  const pinnedCache = pinClaudeCacheCopies();
  const pluginDirFlagFull = `claude --plugin-dir ${pluginSource}`;
  console.log(
    JSON.stringify(
      {
        ok,
        plugin_source: pluginSource,
        marketplace_dir: marketplaceDir,
        marketplace_add: marketplaceAdd,
        claude_code_install: enable,
        manual_load: pluginDirFlagFull,
        restart_required: true,
        pinned_env: pinnedEnv,
        pinned_cache: pinnedCache,
        note: ok
          ? "Plugin registered. Restart Claude Code to activate."
          : `If automatic registration failed, load the plugin with: ${pluginDirFlagFull}`,
      },
      null,
      2,
    ),
  );
  return enable.skipped || enable.ok ? 0 : 1;
}

function runtimeReleasePath(value, env = process.env) {
  if (!value) return false;
  try {
    const releasesRoot = path.join(resolveRuntimeBase(env), "releases");
    const relative = path.relative(releasesRoot, path.resolve(expandHome(String(value))));
    return Boolean(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`);
  } catch {
    return false;
  }
}

function pathEntryExists(pathname) {
  try {
    fs.lstatSync(pathname);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

function repairRuntimeSymlink(name, linkPath, desiredTarget, env = process.env, { allowExternal = false } = {}) {
  let rawTarget;
  try {
    const stat = fs.lstatSync(linkPath);
    if (!stat.isSymbolicLink()) {
      return { name, attempted: false, ok: true, repaired: false, reason: "not a symlink" };
    }
    rawTarget = fs.readlinkSync(linkPath);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return { name, attempted: false, ok: true, repaired: false, reason: "not installed" };
    }
    return { name, attempted: true, ok: false, repaired: false, error: error.message };
  }

  const absoluteTarget = path.resolve(path.dirname(linkPath), rawTarget);
  const logicalCurrent = currentRuntimePath(env);
  if (absoluteTarget === path.resolve(desiredTarget) || absoluteTarget.startsWith(`${logicalCurrent}${path.sep}`)) {
    return { name, attempted: true, ok: true, repaired: false, reason: "already current" };
  }
  if (!allowExternal && !runtimeReleasePath(absoluteTarget, env)) {
    return { name, attempted: false, ok: true, repaired: false, reason: "external target preserved" };
  }
  if (!fs.existsSync(desiredTarget)) {
    return { name, attempted: true, ok: false, repaired: false, error: `missing ${desiredTarget}` };
  }
  switchSymlink(linkPath, desiredTarget);
  return { name, attempted: true, ok: true, repaired: true, target: desiredTarget };
}

function repairHermesEnv(envPath, env = process.env) {
  const existing = readEnvFile(envPath);
  const repaired = [];
  const currentPackage = path.join(currentRuntimePath(env), "agent-wallet");
  if (runtimeReleasePath(existing.AGENT_WALLET_PACKAGE_ROOT, env)) {
    envFileSet(envPath, { AGENT_WALLET_PACKAGE_ROOT: currentPackage });
    repaired.push("AGENT_WALLET_PACKAGE_ROOT");
  }
  if (runtimeReleasePath(existing.AGENT_WALLET_PYTHON, env)) {
    const currentPython = resolveVenvPython(currentRuntimePath(env));
    if (currentPython) {
      envFileSet(envPath, { AGENT_WALLET_PYTHON: currentPython });
    } else {
      envFileUnset(envPath, ["AGENT_WALLET_PYTHON"]);
    }
    repaired.push("AGENT_WALLET_PYTHON");
  }
  return repaired;
}

function globalNpmPackageInfo(env = process.env) {
  const npmBin = commandPath("npm");
  if (!npmBin) return null;
  const rootResult = spawnSync(npmBin, ["root", "--global"], { encoding: "utf8", env });
  if (rootResult.status !== 0) return null;
  const packageRoot = path.join(rootResult.stdout.trim(), ...packageJson.name.split("/"));
  try {
    const manifest = readJsonFile(path.join(packageRoot, "package.json"));
    if (manifest?.name !== packageJson.name) return null;
    return { npm_bin: npmBin, package_root: packageRoot, version: manifest.version || null };
  } catch {
    return null;
  }
}

function refreshGlobalCliIfNeeded(env = process.env) {
  const installed = globalNpmPackageInfo(env);
  if (!installed) {
    return { attempted: false, ok: true, reason: "global package is not installed" };
  }
  if (installed.version === packageVersion) {
    return { attempted: false, ok: true, reason: "already current", version: packageVersion };
  }
  const fromNpmCache = path.resolve(packageRoot).split(path.sep).includes("_npx");
  const forced = env.AGENT_WALLET_FORCE_GLOBAL_CLI_REFRESH === "1";
  if (!fromNpmCache && !forced) {
    return {
      attempted: false,
      ok: false,
      reason: "installer is not running from npm exec",
      installed_version: installed.version,
      target_version: packageVersion,
      fix: `npm install --global ${packageJson.name}@${packageVersion}`,
    };
  }
  const packageSpec = `${packageJson.name}@${packageVersion}`;
  const result = spawnSync(
    installed.npm_bin,
    ["install", "--global", "--no-audit", "--no-fund", packageSpec],
    { encoding: "utf8", env },
  );
  return {
    attempted: true,
    ok: result.status === 0,
    previous_version: installed.version,
    target_version: packageVersion,
    error: result.status === 0 ? "" : (result.stderr || result.stdout || "").trim(),
    fix: result.status === 0 ? "" : `npm install --global ${packageSpec}`,
  };
}

function safelyRefreshIntegration(name, callback) {
  return integrations().safelyRefresh(name, callback);
}

function repairInstalledEditorIntegrations(env = process.env) {
  return hostIntegrations(env).refreshAll();
}

const args = process.argv.slice(2);
const command = args[0] || "install";

if (command === "--telemetry-flush") {
  process.exit(await telemetryFlushMain());
}

if (command === "--help" || command === "-h" || command === "help") {
  printHelp();
  process.exit(0);
}

if (command === "--version" || command === "-v" || command === "version") {
  console.log(packageVersion);
  process.exit(0);
}

if (command === "doctor") {
  process.exit(runDoctor(args.slice(1)));
}

if (command === "--self-verify") {
  const releaseRoot = args[1] ? path.resolve(expandHome(args[1])) : resolvedCurrentRuntimeRoot();
  const result = releaseRoot
    ? verifyRuntime(releaseRoot)
    : { ok: false, error: "no runtime to verify", category: "local_env" };
  console.log(JSON.stringify(result));
  process.exit(result.ok ? 0 : 1);
}

if (command === "status") {
  process.exit(runStatus(args.slice(1)));
}

if (command === "install" || command === "setup") {
  const commandArgs = args.slice(1);
  process.exit(
    runWithCliTelemetry(
      () => runInstall(commandArgs, { commandName: "install" }),
      {
        startEvent: "install_start",
        successEvent: "install_success",
        failedEvent: "install_failed",
        commandName: "install",
        args: commandArgs,
      },
    ),
  );
}

if (command === "update") {
  const commandArgs = args.slice(1);
  process.exit(
    runWithCliTelemetry(
      () => runUpdate(commandArgs),
      {
        startEvent: "update_start",
        successEvent: "update_success",
        failedEvent: "update_failed",
        commandName: "update",
        args: commandArgs,
      },
    ),
  );
}

if (command === "rollback") {
  process.exit(runRollback(args.slice(1)));
}

if (command === "hermes") {
  const subcommand = args[1] || "install";
  if (subcommand === "install" || subcommand === "setup") {
    const commandArgs = args.slice(2);
    process.exit(
      runWithCliTelemetry(
        () => runHermesInstall(commandArgs),
        {
          startEvent: "plugin_install_start",
          successEvent: "plugin_install_success",
          failedEvent: "plugin_install_failed",
          commandName: "hermes_install",
          host: "hermes",
          args: commandArgs,
        },
      ),
    );
  }
  console.error(`Unknown hermes command: ${subcommand}`);
  console.error("Run `openclaw-agent-wallet hermes install --yes` to connect Hermes Agent.");
  process.exit(2);
}

if (command === "codex") {
  const subcommand = args[1] || "install";
  if (subcommand === "install" || subcommand === "setup") {
    const commandArgs = args.slice(2);
    process.exit(
      runWithCliTelemetry(
        () => runCodexInstall(commandArgs),
        {
          startEvent: "plugin_install_start",
          successEvent: "plugin_install_success",
          failedEvent: "plugin_install_failed",
          commandName: "codex_install",
          host: "codex",
          args: commandArgs,
        },
      ),
    );
  }
  console.error(`Unknown codex command: ${subcommand}`);
  console.error("Run `openclaw-agent-wallet codex install --yes` to connect Codex.");
  process.exit(2);
}

if (command === "claude-code") {
  const subcommand = args[1] || "install";
  if (subcommand === "install" || subcommand === "setup") {
    const commandArgs = args.slice(2);
    process.exit(
      runWithCliTelemetry(
        () => runClaudeCodeInstall(commandArgs),
        {
          startEvent: "plugin_install_start",
          successEvent: "plugin_install_success",
          failedEvent: "plugin_install_failed",
          commandName: "claude_code_install",
          host: "claude-code",
          args: commandArgs,
        },
      ),
    );
  }
  console.error(`Unknown claude-code command: ${subcommand}`);
  console.error("Run `openclaw-agent-wallet claude-code install --yes` to connect Claude Code.");
  process.exit(2);
}

if (command.startsWith("-")) {
  process.exit(
    runWithCliTelemetry(
      () => runInstall(args, { commandName: "install" }),
      {
        startEvent: "install_start",
        successEvent: "install_success",
        failedEvent: "install_failed",
        commandName: "install",
        args,
      },
    ),
  );
}

console.error(`Unknown command: ${command}`);
console.error("Run `openclaw-agent-wallet --help` for usage.");
process.exit(2);
