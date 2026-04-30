#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const cliPath = fileURLToPath(import.meta.url);
const packageRoot = path.resolve(path.dirname(cliPath), "..");
const setupPath = path.join(packageRoot, "setup.sh");

function printHelp() {
  console.log(`openclaw-agent-wallet

Usage:
  openclaw-agent-wallet install [setup options]
  openclaw-agent-wallet setup [setup options]
  openclaw-agent-wallet doctor
  openclaw-agent-wallet --version

Examples:
  npx openclaw-agent-wallet install
  npx openclaw-agent-wallet install --backend none
  npx openclaw-agent-wallet install --skip-node-setup

The install command runs the bundled setup.sh from the npm package. It keeps
wallet provisioning, sealed secrets, and OpenClaw config patching in the
existing Python installer instead of reimplementing those rules in JavaScript.`);
}

function hasCommand(name) {
  const result = spawnSync("command", ["-v", name], {
    shell: true,
    stdio: "ignore",
  });
  return result.status === 0;
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
    if (!hasCommand(command)) {
      missing.push(`command:${command}`);
    }
  }
  for (const [label, target] of requiredPaths) {
    if (!fs.existsSync(target)) {
      missing.push(`${label}:${target}`);
    }
  }

  console.log(
    JSON.stringify(
      {
        ok: missing.length === 0,
        package_root: packageRoot,
        setup_path: setupPath,
        commands: Object.fromEntries(commands.map((command) => [command, hasCommand(command)])),
        missing,
      },
      null,
      2,
    ),
  );
  return missing.length === 0 ? 0 : 1;
}

function runInstall(args) {
  if (!fs.existsSync(setupPath)) {
    console.error(`Missing bundled setup.sh at ${setupPath}`);
    return 1;
  }

  const result = spawnSync("sh", [setupPath, ...args], {
    cwd: packageRoot,
    stdio: "inherit",
    env: process.env,
  });

  if (result.error) {
    console.error(result.error.message);
    return 1;
  }
  return result.status ?? 1;
}

const args = process.argv.slice(2);
const command = args[0] || "install";

if (command === "--help" || command === "-h" || command === "help") {
  printHelp();
  process.exit(0);
}

if (command === "--version" || command === "-v" || command === "version") {
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(packageRoot, "package.json"), "utf8"),
  );
  console.log(packageJson.version);
  process.exit(0);
}

if (command === "doctor") {
  process.exit(runDoctor());
}

if (command === "install" || command === "setup") {
  process.exit(runInstall(args.slice(1)));
}

if (command.startsWith("-")) {
  process.exit(runInstall(args));
}

console.error(`Unknown command: ${command}`);
console.error("Run `openclaw-agent-wallet --help` for usage.");
process.exit(2);
