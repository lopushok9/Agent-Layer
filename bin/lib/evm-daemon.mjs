// Best-effort stop of the wdk-evm-wallet daemon that belongs to the wallet
// home being updated. The installer never trusts /health alone: the reported
// PID must also own the local listening socket and run from a wdk-evm-wallet
// working directory. Every failure is advisory and leaves the process alone.
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const DEFAULT_SERVICE_URL = "http://127.0.0.1:8081";
const STOP_TIMEOUT_MS = 10000;
const KILL_TIMEOUT_MS = 5000;
const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

function healthUrl(serviceUrl) {
  return `${String(serviceUrl).replace(/\/+$/, "")}/health`;
}

function expandHome(value, env = process.env) {
  const raw = String(value || "").trim();
  const home = String(env.HOME || os.homedir()).trim() || os.homedir();
  if (raw === "~") return home;
  if (raw.startsWith("~/")) return path.join(home, raw.slice(2));
  return raw;
}

export function daemonTakeoverDisabled(env = process.env) {
  return ["1", "true", "yes", "on"].includes(
    String(env.OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER || "").trim().toLowerCase(),
  );
}

export function isLoopbackServiceUrl(serviceUrl) {
  try {
    const parsed = new URL(serviceUrl);
    return parsed.protocol === "http:" && LOCAL_HOSTS.has(parsed.hostname);
  } catch {
    return false;
  }
}

export function expectedDataDirFor(env = process.env) {
  const configured = String(env.WDK_EVM_DATA_DIR || "").trim();
  if (configured) return path.resolve(expandHome(configured, env));
  const home = expandHome(env.OPENCLAW_HOME || path.join(env.HOME || os.homedir(), ".openclaw"), env);
  return path.resolve(home, "wdk-evm-wallet");
}

function samePath(left, right) {
  if (!left || !right) return false;
  try {
    return path.resolve(expandHome(left)) === path.resolve(expandHome(right));
  } catch {
    return false;
  }
}

function readJsonFile(pathname) {
  try {
    return { present: true, valid: true, value: JSON.parse(fs.readFileSync(pathname, "utf8")) };
  } catch (error) {
    if (error?.code === "ENOENT") return { present: false, valid: true, value: null };
    return { present: true, valid: false, value: null };
  }
}

function readServiceOwner(dataDir) {
  return readJsonFile(path.join(dataDir, "service-owner.json"));
}

function runLsof(args, env = process.env) {
  const result = spawnSync("lsof", args, {
    encoding: "utf8",
    timeout: 5000,
    env,
  });
  if (result.error) return null;
  // lsof uses status 1 when no rows match. That is a valid empty result.
  if (![0, 1].includes(result.status)) return null;
  return String(result.stdout || "");
}

function parsePids(raw) {
  return [...new Set(
    String(raw || "")
      .split(/\s+/)
      .filter((token) => /^\d+$/.test(token))
      .map((token) => Number(token))
      .filter((pid) => Number.isInteger(pid) && pid > 0),
  )];
}

export function inspectDaemonProcess(pid, port, env = process.env) {
  const listenerOutput = runLsof(
    ["-nP", "-t", "-iTCP:" + String(port), "-sTCP:LISTEN"],
    env,
  );
  const cwdOutput = runLsof(["-a", "-p", String(pid), "-d", "cwd", "-Fn"], env);
  if (listenerOutput === null || cwdOutput === null) {
    return { available: false, listenerPids: [], cwd: "" };
  }
  const cwd = cwdOutput
    .split(/\r?\n/)
    .find((line) => line.startsWith("n"))
    ?.slice(1)
    .trim() || "";
  return {
    available: true,
    listenerPids: parsePids(listenerOutput),
    cwd,
  };
}

function cwdLooksLikeEvmDaemon(cwd) {
  if (!cwd) return false;
  try {
    return path.basename(path.resolve(cwd)) === "wdk-evm-wallet";
  } catch {
    return false;
  }
}

function ownerMatches({ ownerState, health, pid, port, expectedDataDir }) {
  if (!ownerState.valid) return false;
  if (!ownerState.present) return true;
  const owner = ownerState.value;
  if (!owner || typeof owner !== "object") return false;
  return (
    Number(owner.pid) === pid &&
    Number(owner.port) === port &&
    samePath(owner.data_dir, expectedDataDir) &&
    String(owner.instance_id || "") === String(health.instanceId || "")
  );
}

export function classifyDaemonHealth(
  health,
  {
    expectedDataDir,
    port,
    inspection = { available: false, listenerPids: [], cwd: "" },
    ownerState = { present: false, valid: true, value: null },
  } = {},
) {
  if (!health || typeof health !== "object") {
    return { stoppable: false, reason: "not_running", pid: 0 };
  }
  if (health.service !== "wdk-evm-wallet") {
    return { stoppable: false, reason: "foreign_service", pid: 0 };
  }
  const reportedDataDir = String(health.dataDir || "").trim();
  if (!reportedDataDir || !samePath(reportedDataDir, expectedDataDir)) {
    return { stoppable: false, reason: "foreign_vault", pid: 0 };
  }
  const pid = typeof health.pid === "number" ? health.pid : Number.NaN;
  if (!Number.isInteger(pid) || pid <= 0) {
    return { stoppable: false, reason: "no_pid", pid: 0 };
  }
  if (!inspection.available) {
    return { stoppable: false, reason: "process_inspection_unavailable", pid };
  }
  if (!inspection.listenerPids.includes(pid)) {
    return { stoppable: false, reason: "pid_not_listener", pid };
  }
  if (!cwdLooksLikeEvmDaemon(inspection.cwd)) {
    return { stoppable: false, reason: "foreign_process", pid };
  }
  if (!ownerMatches({ ownerState, health, pid, port, expectedDataDir })) {
    return { stoppable: false, reason: "owner_mismatch", pid };
  }
  return { stoppable: true, reason: "stoppable", pid };
}

export function readDaemonHealth(serviceUrl, timeoutMs = 1500) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (value) => {
      if (!settled) {
        settled = true;
        resolve(value);
      }
    };
    const request = http.get(healthUrl(serviceUrl), { timeout: timeoutMs }, (response) => {
      if (response.statusCode !== 200) {
        response.resume();
        done(null);
        return;
      }
      let raw = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        raw += chunk;
      });
      response.on("end", () => {
        try {
          done(JSON.parse(raw));
        } catch {
          done(null);
        }
      });
    });
    request.on("timeout", () => {
      request.destroy();
      done(null);
    });
    request.on("error", () => done(null));
  });
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== "ESRCH";
  }
}

function processIsSignalable(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function processStillMatches(pid, port, expectedDataDir, ownerState, env) {
  const inspection = inspectDaemonProcess(pid, port, env);
  if (
    !inspection.available ||
    !inspection.listenerPids.includes(pid) ||
    !cwdLooksLikeEvmDaemon(inspection.cwd)
  ) {
    return false;
  }
  if (!ownerState.valid || !ownerState.present) return false;
  const owner = ownerState.value;
  return (
    Number(owner?.pid) === pid &&
    Number(owner?.port) === port &&
    samePath(owner?.data_dir, expectedDataDir)
  );
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForExit(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!processExists(pid)) return true;
    await sleep(300);
  }
  return !processExists(pid);
}

export async function stopLocalEvmDaemon({ serviceUrl, env = process.env } = {}) {
  if (daemonTakeoverDisabled(env)) {
    return { attempted: false, stopped: false, reason: "takeover_disabled", pid: 0 };
  }
  const url =
    String(env.WDK_EVM_SERVICE_URL || serviceUrl || DEFAULT_SERVICE_URL).trim() ||
    DEFAULT_SERVICE_URL;
  if (!isLoopbackServiceUrl(url)) {
    return { attempted: false, stopped: false, reason: "non_local_service_url", pid: 0 };
  }

  const parsed = new URL(url);
  const port = Number(parsed.port || 80);
  const expectedDataDir = expectedDataDirFor(env);
  const health = await readDaemonHealth(url);
  const reportedPid = Number(health?.pid || 0);
  const inspection =
    Number.isInteger(reportedPid) && reportedPid > 0
      ? inspectDaemonProcess(reportedPid, port, env)
      : { available: false, listenerPids: [], cwd: "" };
  const ownerState = readServiceOwner(expectedDataDir);
  const verdict = classifyDaemonHealth(health, {
    expectedDataDir,
    port,
    inspection,
    ownerState,
  });
  if (!verdict.stoppable) {
    return { attempted: false, stopped: false, reason: verdict.reason, pid: verdict.pid };
  }
  if (!processIsSignalable(verdict.pid)) {
    return { attempted: false, stopped: false, reason: "pid_not_signalable", pid: verdict.pid };
  }
  // Close the remaining PID-reuse window as much as portable macOS/Linux APIs
  // allow by rechecking the listener immediately before the signal.
  const finalInspection = inspectDaemonProcess(verdict.pid, port, env);
  if (
    !finalInspection.available ||
    !finalInspection.listenerPids.includes(verdict.pid) ||
    !cwdLooksLikeEvmDaemon(finalInspection.cwd)
  ) {
    return { attempted: false, stopped: false, reason: "identity_changed", pid: verdict.pid };
  }
  try {
    process.kill(verdict.pid, "SIGTERM");
  } catch (error) {
    return {
      attempted: true,
      stopped: false,
      reason: `signal_failed:${error?.code || "unknown"}`,
      pid: verdict.pid,
    };
  }
  if (await waitForExit(verdict.pid, STOP_TIMEOUT_MS)) {
    return { attempted: true, stopped: true, reason: "stopped", pid: verdict.pid };
  }

  // A hard stop is only allowed when the exact same owned process still owns
  // the socket. Missing owner evidence or any identity change fails closed.
  if (!processStillMatches(verdict.pid, port, expectedDataDir, ownerState, env)) {
    return { attempted: true, stopped: false, reason: "still_running_unverified", pid: verdict.pid };
  }
  try {
    process.kill(verdict.pid, "SIGKILL");
  } catch (error) {
    if (error?.code !== "ESRCH") {
      return {
        attempted: true,
        stopped: false,
        reason: `kill_failed:${error?.code || "unknown"}`,
        pid: verdict.pid,
      };
    }
  }
  const stopped = await waitForExit(verdict.pid, KILL_TIMEOUT_MS);
  return {
    attempted: true,
    stopped,
    reason: stopped ? "killed" : "still_running",
    pid: verdict.pid,
  };
}

// The install and rollback paths are synchronous. Run the bounded async stop
// worker in a short-lived subprocess rather than making the CLI lifecycle async.
export function stopLocalEvmDaemonSync({ env = process.env } = {}) {
  const fallback = { attempted: false, stopped: false, reason: "subprocess_failed", pid: 0 };
  try {
    const result = spawnSync(process.execPath, [fileURLToPath(import.meta.url), "--stop"], {
      encoding: "utf8",
      timeout: STOP_TIMEOUT_MS + KILL_TIMEOUT_MS + 5000,
      env,
    });
    if (result.status !== 0 || !result.stdout) return fallback;
    return JSON.parse(result.stdout.trim());
  } catch {
    return fallback;
  }
}

if (
  process.argv[1] &&
  fileURLToPath(import.meta.url) === process.argv[1] &&
  process.argv.includes("--stop")
) {
  stopLocalEvmDaemon()
    .then((result) => {
      process.stdout.write(JSON.stringify(result));
      process.exit(0);
    })
    .catch(() => {
      process.stdout.write(
        JSON.stringify({ attempted: false, stopped: false, reason: "worker_failed", pid: 0 }),
      );
      process.exit(0);
    });
}
