import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

import {
  classifyDaemonHealth,
  daemonTakeoverDisabled,
  expectedDataDirFor,
  isLoopbackServiceUrl,
  readDaemonHealth,
  stopLocalEvmDaemon,
} from "./evm-daemon.mjs";

const DATA_DIR = "/tmp/agentlayer-home/wdk-evm-wallet";
const PORT = 18081;
const PID = 4242;

function health(overrides = {}) {
  return {
    service: "wdk-evm-wallet",
    pid: PID,
    dataDir: DATA_DIR,
    instanceId: "instance-a",
    ...overrides,
  };
}

function inspection(overrides = {}) {
  return {
    available: true,
    listenerPids: [PID],
    cwd: "/tmp/runtime/wdk-evm-wallet",
    ...overrides,
  };
}

function ownerState(overrides = {}) {
  return {
    present: true,
    valid: true,
    value: {
      pid: PID,
      port: PORT,
      data_dir: DATA_DIR,
      instance_id: "instance-a",
      ...overrides,
    },
  };
}

function classify(overrides = {}) {
  const selectedHealth = Object.prototype.hasOwnProperty.call(overrides, "health")
    ? overrides.health
    : health();
  return classifyDaemonHealth(selectedHealth, {
    expectedDataDir: overrides.expectedDataDir ?? DATA_DIR,
    port: PORT,
    inspection: overrides.inspection ?? inspection(),
    ownerState: overrides.ownerState ?? ownerState(),
  });
}

test("a verified same-home daemon is stoppable", () => {
  assert.deepEqual(classify(), { stoppable: true, reason: "stoppable", pid: PID });
});

test("a missing or foreign service is never stoppable", () => {
  assert.equal(classify({ health: null }).reason, "not_running");
  assert.equal(classify({ health: health({ service: "something-else" }) }).reason, "foreign_service");
});

test("a daemon for another wallet home is never stoppable", () => {
  assert.equal(
    classify({ health: health({ dataDir: "/tmp/other-home/wdk-evm-wallet" }) }).reason,
    "foreign_vault",
  );
});

test("the reported pid must own the listening socket", () => {
  assert.equal(
    classify({ inspection: inspection({ listenerPids: [9999] }) }).reason,
    "pid_not_listener",
  );
  assert.equal(
    classify({ inspection: inspection({ available: false, listenerPids: [] }) }).reason,
    "process_inspection_unavailable",
  );
});

test("the listener must run from a wdk-evm-wallet directory", () => {
  assert.equal(
    classify({ inspection: inspection({ cwd: "/tmp/unrelated-service" }) }).reason,
    "foreign_process",
  );
});

test("a mismatched or corrupt ownership record is refused", () => {
  assert.equal(
    classify({ ownerState: ownerState({ pid: 9999 }) }).reason,
    "owner_mismatch",
  );
  assert.equal(
    classify({ ownerState: { present: true, valid: false, value: null } }).reason,
    "owner_mismatch",
  );
});

test("a missing ownership record still permits the strictly verified graceful stop", () => {
  assert.equal(
    classify({ ownerState: { present: false, valid: true, value: null } }).reason,
    "stoppable",
  );
});

test("only loopback http service URLs are accepted", () => {
  assert.equal(isLoopbackServiceUrl("http://127.0.0.1:8081"), true);
  assert.equal(isLoopbackServiceUrl("http://localhost:8081"), true);
  assert.equal(isLoopbackServiceUrl("http://[::1]:8081"), true);
  assert.equal(isLoopbackServiceUrl("http://example.com:8081"), false);
  assert.equal(isLoopbackServiceUrl("https://127.0.0.1:8081"), false);
});

test("the kill switch accepts common true values", () => {
  assert.equal(daemonTakeoverDisabled({ OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER: "1" }), true);
  assert.equal(daemonTakeoverDisabled({ OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER: "true" }), true);
  assert.equal(daemonTakeoverDisabled({ OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER: "0" }), false);
});

test("the installer stop path honors the kill switch before probing a daemon", async () => {
  const result = await stopLocalEvmDaemon({
    serviceUrl: "http://127.0.0.1:1",
    env: { OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER: "1" },
  });
  assert.deepEqual(result, {
    attempted: false,
    stopped: false,
    reason: "takeover_disabled",
    pid: 0,
  });
});

test("the installer refuses non-loopback service URLs before probing them", async () => {
  const result = await stopLocalEvmDaemon({
    serviceUrl: "http://example.com:8081",
    env: {},
  });
  assert.equal(result.reason, "non_local_service_url");
  assert.equal(result.attempted, false);
});

test("the target data dir is always pinned to the selected wallet home", () => {
  assert.equal(
    expectedDataDirFor({ HOME: "/tmp/user-home" }),
    "/tmp/user-home/.openclaw/wdk-evm-wallet",
  );
  assert.equal(
    expectedDataDirFor({ HOME: "/tmp/user-home", OPENCLAW_HOME: "/tmp/custom-home" }),
    "/tmp/custom-home/wdk-evm-wallet",
  );
  assert.equal(
    expectedDataDirFor({ HOME: "/tmp/user-home", WDK_EVM_DATA_DIR: "/tmp/explicit-dir" }),
    "/tmp/explicit-dir",
  );
});

const hasLsof = !spawnSync("lsof", ["-v"], { stdio: "ignore" }).error;

async function waitForHealth(serviceUrl, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const payload = await readDaemonHealth(serviceUrl, 250);
    if (payload) return payload;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`service did not become healthy: ${serviceUrl}`);
}

test("the installer stops a verified same-home daemon", { skip: !hasLsof }, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agentlayer-evm-stop-"));
  const walletHome = path.join(root, "home");
  const dataDir = path.join(walletHome, "wdk-evm-wallet");
  const daemonCwd = path.join(root, "runtime", "wdk-evm-wallet");
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(daemonCwd, { recursive: true });

  const childSource = `
    const http = require("node:http");
    const server = http.createServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({
        service: "wdk-evm-wallet",
        pid: process.pid,
        dataDir: process.env.TEST_DATA_DIR,
        instanceId: "instance-a"
      }));
    });
    process.on("SIGTERM", () => server.close(() => process.exit(0)));
    server.listen(0, "127.0.0.1", () => {
      process.stdout.write(String(server.address().port) + "\\n");
    });
  `;
  const child = spawn(process.execPath, ["-e", childSource], {
    cwd: daemonCwd,
    env: { ...process.env, TEST_DATA_DIR: dataDir },
    stdio: ["ignore", "pipe", "inherit"],
  });
  try {
    const port = await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.stdout.once("data", (chunk) => resolve(Number(String(chunk).trim())));
    });
    const serviceUrl = `http://127.0.0.1:${port}`;
    await waitForHealth(serviceUrl);
    fs.writeFileSync(
      path.join(dataDir, "service-owner.json"),
      JSON.stringify({
        pid: child.pid,
        port,
        data_dir: dataDir,
        instance_id: "instance-a",
      }),
      { mode: 0o600 },
    );

    const result = await stopLocalEvmDaemon({
      serviceUrl,
      env: {
        ...process.env,
        OPENCLAW_HOME: walletHome,
        WDK_EVM_DATA_DIR: dataDir,
      },
    });
    assert.equal(result.stopped, true, JSON.stringify(result));
    assert.equal(result.pid, child.pid);
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("a spoofed health pid cannot terminate an unrelated process", { skip: !hasLsof }, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "agentlayer-evm-spoof-"));
  const dataDir = path.join(root, "home", "wdk-evm-wallet");
  fs.mkdirSync(dataDir, { recursive: true });
  const victim = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
    stdio: "ignore",
  });
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(
      JSON.stringify({
        service: "wdk-evm-wallet",
        pid: victim.pid,
        dataDir,
        instanceId: "instance-a",
      }),
    );
  });
  try {
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const serviceUrl = `http://127.0.0.1:${server.address().port}`;
    const result = await stopLocalEvmDaemon({
      serviceUrl,
      env: { ...process.env, WDK_EVM_DATA_DIR: dataDir },
    });
    assert.equal(result.stopped, false);
    assert.equal(result.reason, "pid_not_listener");
    assert.doesNotThrow(() => process.kill(victim.pid, 0));
  } finally {
    await new Promise((resolve) => server.close(resolve));
    if (victim.exitCode === null && victim.signalCode === null) victim.kill("SIGKILL");
    fs.rmSync(root, { recursive: true, force: true });
  }
});
