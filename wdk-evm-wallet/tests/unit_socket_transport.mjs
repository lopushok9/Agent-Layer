import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
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

function requestOverSocket(socketPath, requestPath) {
  return new Promise((resolve, reject) => {
    const req = http.request({ socketPath, path: requestPath, method: "GET" }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => resolve({ status: res.statusCode, body }));
    });
    req.on("error", reject);
    req.end();
  });
}

test("server binds to socketPath and serves /health over it, mode 0600", async () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home });
    const { startServer } = await import("../src/server.js?test=" + Date.now());
    const { server, close } = await startServer(config);
    try {
      // startServer()'s promise resolves from inside its own "listening"
      // handler, so by the time we get here the socket is already bound —
      // awaiting a second "listening" event here would hang forever.
      assert.equal(server.listening, true);
      const stat = fs.statSync(config.socketPath);
      assert.equal(stat.mode & 0o777, 0o600);
      const response = await requestOverSocket(config.socketPath, "/health");
      assert.equal(response.status, 200);
      const payload = JSON.parse(response.body);
      assert.equal(payload.ok, true);
    } finally {
      await close();
    }
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test("a stale socket file (nothing listening) does not block a fresh bind", async () => {
  const home = tempHome();
  try {
    const config = loadConfig({ OPENCLAW_HOME: home });
    fs.mkdirSync(config.dataDir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(config.socketPath, ""); // never bound to by anything — pure leftover
    const { startServer } = await import("../src/server.js?test=" + Date.now());
    const { server, close } = await startServer(config);
    try {
      assert.equal(server.listening, true);
      const response = await requestOverSocket(config.socketPath, "/health");
      assert.equal(response.status, 200);
    } finally {
      await close();
    }
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});
