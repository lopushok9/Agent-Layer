#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const cliPath = fileURLToPath(import.meta.url);
const packageRoot = path.resolve(path.dirname(cliPath), "..");
const setupPath = path.join(packageRoot, "setup.sh");
const packageJsonPath = path.join(packageRoot, "package.json");
const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
const packageVersion = packageJson.version;
const UPDATE_CLI_PATH_ENV = "OPENCLAW_AGENT_WALLET_UPDATE_CLI_PATH";
const UPDATE_PACKAGE_SPEC_ENV = "OPENCLAW_AGENT_WALLET_UPDATE_PACKAGE_SPEC";

function printHelp() {
  console.log(`openclaw-agent-wallet

Usage:
  openclaw-agent-wallet install [options]
  openclaw-agent-wallet hermes install [options]
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
reuses shared dependency snapshots when possible.`);
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

function resolveHermesHome(env = process.env) {
  return path.resolve(expandHome(env.HERMES_HOME || "~/.hermes"));
}

function releaseRootFor(version, env = process.env) {
  return path.join(resolveRuntimeBase(env), "releases", version);
}

function currentRuntimePath(env = process.env) {
  return path.join(resolveRuntimeBase(env), "current");
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
      .filter((entry) => entry.isDirectory())
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

function currentBootKey(env = process.env) {
  const currentRoot = resolvedCurrentRuntimeRoot(env);
  if (!currentRoot) return "";
  return readEnvFile(path.join(currentRoot, "agent-wallet", ".env")).AGENT_WALLET_BOOT_KEY || "";
}

function readTextIfExists(pathname) {
  try {
    return fs.readFileSync(pathname, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") return "";
    throw error;
  }
}

function writeSecretFile(pathname, value) {
  fs.mkdirSync(path.dirname(pathname), { recursive: true });
  fs.writeFileSync(pathname, `${String(value || "").trim()}\n`, { mode: 0o600 });
  try {
    fs.chmodSync(pathname, 0o600);
  } catch {
    // ignored
  }
}

function resolveBootKeyFromFile(env = process.env) {
  const keyFile = String(env.AGENT_WALLET_BOOT_KEY_FILE || "").trim();
  if (!keyFile) return "";
  return readTextIfExists(path.resolve(expandHome(keyFile))).trim();
}

function defaultBootKeyFile(env = process.env) {
  return path.join(resolveRuntimeBase(env), "boot-key");
}

function ensureBootKeyFile(env = process.env) {
  const configuredFile = String(env.AGENT_WALLET_BOOT_KEY_FILE || "").trim();
  const keyFile = configuredFile ? path.resolve(expandHome(configuredFile)) : defaultBootKeyFile(env);
  const existing = readTextIfExists(keyFile).trim();
  if (existing) {
    return { path: keyFile, status: "existing" };
  }
  const bootKey = String(env.AGENT_WALLET_BOOT_KEY || "").trim() || resolveBootKeyFromFile(env) || currentBootKey(env);
  if (!bootKey) {
    return { path: keyFile, status: "missing" };
  }
  writeSecretFile(keyFile, bootKey);
  return { path: keyFile, status: "created" };
}

function runDoctor() {
  const requiredPaths = [
    ["setup.sh", setupPath],
    ["agent-wallet", path.join(packageRoot, "agent-wallet")],
    ["OpenClaw extension", path.join(packageRoot, ".openclaw", "extensions", "agent-wallet")],
    ["wdk-btc-wallet", path.join(packageRoot, "wdk-btc-wallet", "package.json")],
    ["wdk-evm-wallet", path.join(packageRoot, "wdk-evm-wallet", "package.json")],
  ];
  const commands = ["node", "npm"];
  const missing = [];
  const python = selectedPythonProbe();

  for (const command of commands) {
    if (!hasCommand(command)) missing.push(`command:${command}`);
  }
  if (!python.path) {
    missing.push("command:python3.10-or-python3");
  } else if (!python.version_ok) {
    missing.push(`python>=3.10:selected:${python.version || "unknown"}`);
  } else if (!python.venv_ok) {
    missing.push(`python-venv-ensurepip:selected:${python.version || "unknown"}`);
  }
  for (const [label, target] of requiredPaths) {
    if (!fs.existsSync(target)) missing.push(`${label}:${target}`);
  }

  console.log(
    JSON.stringify(
      {
        ok: missing.length === 0,
        package_name: packageJson.name,
        package_version: packageVersion,
        package_root: packageRoot,
        setup_path: setupPath,
        openclaw_home: resolveOpenclawHome(),
        runtime_base: resolveRuntimeBase(),
        current_runtime: currentRuntimePath(),
        active_version: activeVersion(),
        releases: listReleases(),
        python,
        commands: Object.fromEntries(commands.map((command) => [command, hasCommand(command)])),
        missing,
      },
      null,
      2,
    ),
  );
  return missing.length === 0 ? 0 : 1;
}

function runStatus(args = []) {
  const payload = {
    ok: true,
    package_name: packageJson.name,
    package_version: packageVersion,
    openclaw_home: resolveOpenclawHome(),
    runtime_base: resolveRuntimeBase(),
    current_runtime: currentRuntimePath(),
    previous_runtime: readLinkOrNull(previousRuntimePath()),
    active_version: activeVersion(),
    available_releases: listReleases(),
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
  if (!env.AGENT_WALLET_BOOT_KEY) {
    const existingBootKey =
      resolveBootKeyFromFile(env) ||
      readTextIfExists(defaultBootKeyFile(env)).trim() ||
      currentBootKey(env);
    if (existingBootKey) {
      env.AGENT_WALLET_BOOT_KEY = existingBootKey;
    }
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
  }
  if (!sealedKeysExist && shouldGenerateSecrets && !env.AGENT_WALLET_MASTER_KEY) {
    generated.AGENT_WALLET_MASTER_KEY = token();
    env.AGENT_WALLET_MASTER_KEY = generated.AGENT_WALLET_MASTER_KEY;
  }
  if (!sealedKeysExist && shouldGenerateSecrets && !env.AGENT_WALLET_APPROVAL_SECRET) {
    generated.AGENT_WALLET_APPROVAL_SECRET = token();
    env.AGENT_WALLET_APPROVAL_SECRET = generated.AGENT_WALLET_APPROVAL_SECRET;
  }
  return { env, generated };
}

function runInstall(args, { commandName = "install" } = {}) {
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

  if (!hasFlag(installerArgs, "--runtime-root")) {
    installerArgs.push("--runtime-root", releaseRoot);
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
  const { env, generated } = installerEnv;
  const result = spawnSync("sh", [setupPath, ...installerArgs], {
    cwd: packageRoot,
    stdio: "inherit",
    env,
  });

  if (result.error) {
    console.error(result.error.message);
    return 1;
  }
  if ((result.status ?? 1) !== 0) {
    return result.status ?? 1;
  }

  const currentTarget = readLinkOrNull(currentPath);
  if (currentTarget) {
    switchSymlink(previousPath, path.resolve(path.dirname(currentPath), currentTarget));
  }
  switchSymlink(currentPath, releaseRoot);

  if (env.AGENT_WALLET_BOOT_KEY) {
    envFileSet(path.join(releaseRoot, "agent-wallet", ".env"), {
      AGENT_WALLET_BOOT_KEY: env.AGENT_WALLET_BOOT_KEY,
    });
  }

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
      },
      null,
      2,
    ),
  );
  return 0;
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

  let delegated;
  try {
    delegated = runDelegatedInstallForUpdate(args, { captureOutput: false });
  } catch (error) {
    console.error(error.message);
    return 1;
  }
  if (delegated.result.error) {
    console.error(delegated.result.error.message);
    return 1;
  }
  return delegated.result.status ?? 1;
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
  const currentRoot = resolvedCurrentRuntimeRoot();
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

function resolveAgentWalletPackageRoot(env = process.env) {
  const currentRoot = resolvedCurrentRuntimeRoot(env);
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

const args = process.argv.slice(2);
const command = args[0] || "install";

if (command === "--help" || command === "-h" || command === "help") {
  printHelp();
  process.exit(0);
}

if (command === "--version" || command === "-v" || command === "version") {
  console.log(packageVersion);
  process.exit(0);
}

if (command === "doctor") {
  process.exit(runDoctor());
}

if (command === "status") {
  process.exit(runStatus(args.slice(1)));
}

if (command === "install" || command === "setup") {
  process.exit(runInstall(args.slice(1), { commandName: "install" }));
}

if (command === "update") {
  process.exit(runUpdate(args.slice(1)));
}

if (command === "rollback") {
  process.exit(runRollback(args.slice(1)));
}

if (command === "hermes") {
  const subcommand = args[1] || "install";
  if (subcommand === "install" || subcommand === "setup") {
    process.exit(runHermesInstall(args.slice(2)));
  }
  console.error(`Unknown hermes command: ${subcommand}`);
  console.error("Run `openclaw-agent-wallet hermes install --yes` to connect Hermes Agent.");
  process.exit(2);
}

if (command.startsWith("-")) {
  process.exit(runInstall(args, { commandName: "install" }));
}

console.error(`Unknown command: ${command}`);
console.error("Run `openclaw-agent-wallet --help` for usage.");
process.exit(2);
