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

function printHelp() {
  console.log(`openclaw-agent-wallet

Usage:
  openclaw-agent-wallet install [options]
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
  npx openclaw-agent-wallet install --yes
  npx openclaw-agent-wallet install --backend none
  npx openclaw-agent-wallet update --yes
  npx openclaw-agent-wallet status

The installer writes a versioned runtime under:
  ~/.openclaw/agent-wallet-runtime/releases/<version>

After a successful install it switches:
  ~/.openclaw/agent-wallet-runtime/current

Wallet files and sealed secrets remain under OPENCLAW_HOME and are not replaced
by updates.`);
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

function releaseRootFor(version, env = process.env) {
  return path.join(resolveRuntimeBase(env), "releases", version);
}

function currentRuntimePath(env = process.env) {
  return path.join(resolveRuntimeBase(env), "current");
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

function switchSymlink(linkPath, targetPath) {
  const absoluteTarget = path.resolve(targetPath);
  if (!fs.existsSync(absoluteTarget)) {
    throw new Error(`Cannot switch runtime: target does not exist: ${absoluteTarget}`);
  }

  fs.mkdirSync(path.dirname(linkPath), { recursive: true });
  const tempLink = `${linkPath}.tmp-${process.pid}`;
  try {
    fs.rmSync(tempLink, { force: true, recursive: false });
  } catch {
    // ignored
  }
  fs.symlinkSync(absoluteTarget, tempLink, "dir");

  try {
    const existing = fs.lstatSync(linkPath);
    if (!existing.isSymbolicLink()) {
      fs.rmSync(tempLink, { force: true });
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
  const currentPath = currentRuntimePath(env);
  const currentTarget = readLinkOrNull(currentPath);
  if (!currentTarget) return "";
  const currentRoot = path.resolve(path.dirname(currentPath), currentTarget);
  return readEnvFile(path.join(currentRoot, "agent-wallet", ".env")).AGENT_WALLET_BOOT_KEY || "";
}

function runDoctor() {
  const requiredPaths = [
    ["setup.sh", setupPath],
    ["agent-wallet", path.join(packageRoot, "agent-wallet")],
    ["OpenClaw extension", path.join(packageRoot, ".openclaw", "extensions", "agent-wallet")],
    ["wdk-btc-wallet", path.join(packageRoot, "wdk-btc-wallet", "package.json")],
    ["wdk-evm-wallet", path.join(packageRoot, "wdk-evm-wallet", "package.json")],
  ];
  const commands = ["python3", "node", "npm"];
  const missing = [];

  for (const command of commands) {
    if (!hasCommand(command)) missing.push(`command:${command}`);
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
        commands: Object.fromEntries(commands.map((command) => [command, hasCommand(command)])),
        missing,
      },
      null,
      2,
    ),
  );
  return missing.length === 0 ? 0 : 1;
}

function runStatus() {
  console.log(
    JSON.stringify(
      {
        ok: true,
        package_name: packageJson.name,
        package_version: packageVersion,
        openclaw_home: resolveOpenclawHome(),
        runtime_base: resolveRuntimeBase(),
        current_runtime: currentRuntimePath(),
        previous_runtime: readLinkOrNull(previousRuntimePath()),
        active_version: activeVersion(),
        available_releases: listReleases(),
      },
      null,
      2,
    ),
  );
  return 0;
}

function buildInstallerEnv(args) {
  const env = { ...process.env };
  const sealedKeysPath = path.join(resolveOpenclawHome(env), "sealed_keys.json");
  const sealedKeysExist = fs.existsSync(sealedKeysPath);
  if (!env.AGENT_WALLET_BOOT_KEY) {
    const existingBootKey = currentBootKey(env);
    if (existingBootKey) {
      env.AGENT_WALLET_BOOT_KEY = existingBootKey;
    }
  }

  const shouldGenerateSecrets =
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
  process.exit(runStatus());
}

if (command === "install" || command === "setup") {
  process.exit(runInstall(args.slice(1), { commandName: "install" }));
}

if (command === "update") {
  process.exit(runInstall(args.slice(1), { commandName: "update" }));
}

if (command === "rollback") {
  process.exit(runRollback(args.slice(1)));
}

if (command.startsWith("-")) {
  process.exit(runInstall(args, { commandName: "install" }));
}

console.error(`Unknown command: ${command}`);
console.error("Run `openclaw-agent-wallet --help` for usage.");
process.exit(2);
