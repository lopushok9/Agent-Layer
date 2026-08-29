import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { loadConfig } from "../src/config.js";

function tempHome() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "wdk-evm-socket-config-"));
}

test("socket transport is the default", () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home });
    assert.equal(config.transport, "socket");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("default socketPath lives inside dataDir", () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home });
    assert.equal(config.socketPath, path.join(config.dataDir, "daemon.sock"));
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("WDK_EVM_SOCKET_PATH overrides the default", () => {
  const home = tempHome();
  const override = path.join(home, "custom.sock");
  try {
    const config = loadConfig({ OPENCLAW_HOME: home, WDK_EVM_SOCKET_PATH: override });
    assert.equal(config.socketPath, override);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("WDK_EVM_TRANSPORT=tcp selects tcp transport and keeps host/port", () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home, WDK_EVM_TRANSPORT: "tcp", PORT: "9999" });
    assert.equal(config.transport, "tcp");
    assert.equal(config.port, 9999);
    assert.equal(config.host, "127.0.0.1");
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("an unrecognized WDK_EVM_TRANSPORT value throws", () => {
  const home = tempHome();
  try {
    assert.throws(() => loadConfig({ OPENCLAW_HOME: home, WDK_EVM_TRANSPORT: "carrier-pigeon" }));
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});
