import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..");
const SOURCE = path.join(ROOT, ".openclaw", "extensions", "agent-wallet", "index.ts");

async function main() {
  const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), "openclaw-plugin-runtime-"));
  const runtimePackageRoot = path.join(
    tempHome,
    "agent-wallet-runtime",
    "current",
    "agent-wallet"
  );
  fs.mkdirSync(path.join(runtimePackageRoot, "agent_wallet"), { recursive: true });
  fs.writeFileSync(
    path.join(runtimePackageRoot, "agent_wallet", "__init__.py"),
    "__all__ = []\n",
    "utf8"
  );

  const previousOpenclawHome = process.env.OPENCLAW_HOME;
  process.env.OPENCLAW_HOME = tempHome;

  let source = fs.readFileSync(SOURCE, "utf8");
  source = source.replace(
    'import { execFile } from "node:child_process";',
    "const execFile = globalThis.__TEST_EXEC_FILE__;"
  );
  source = source.replace(
    "const execFileAsync = promisify(execFile);",
    "const execFileAsync = (...args) => globalThis.__TEST_EXEC_FILE_ASYNC__(...args);"
  );

  const calls = [];
  globalThis.__TEST_EXEC_FILE_ASYNC__ = async (pythonBin, args, options) => {
    calls.push({ pythonBin, args, options });
    return {
      stdout: JSON.stringify({
        ok: true,
        data: {
          backend: "solana_local",
          network: "mainnet",
        },
      }),
      stderr: "",
    };
  };
  globalThis.__TEST_EXEC_FILE__ = (pythonBin, args, options, callback) => {
    globalThis.__TEST_EXEC_FILE_ASYNC__(pythonBin, args, options)
      .then(({ stdout, stderr }) => callback(null, stdout, stderr))
      .catch((error) => callback(error));
  };

  try {
    const moduleUrl = `data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`;
    const mod = await import(moduleUrl);
    const register = mod.default;

    const tools = [];
    const api = {
      config: {
        plugins: {
          entries: {
            "agent-wallet": {
              config: {
                userId: "openclaw-test-user",
                backend: "solana_local",
                network: "mainnet",
                pythonBin: "/tmp/fake-python",
              },
            },
          },
        },
      },
      logger: { info() {}, debug() {} },
      registerTool(definition) {
        tools.push(definition);
      },
    };

    register(api);
    const capabilitiesTool = tools.find((tool) => tool.name === "get_wallet_capabilities");
    assert.ok(capabilitiesTool, "get_wallet_capabilities tool should be registered");

    await capabilitiesTool.execute("1", {});

    assert.equal(calls.length, 1);
    assert.equal(calls[0].pythonBin, "/tmp/fake-python");
    assert.equal(calls[0].options.cwd, runtimePackageRoot);
    assert.ok(
      String(calls[0].options.env.PYTHONPATH || "").startsWith(runtimePackageRoot),
      "PYTHONPATH should start with the trusted runtime package root"
    );
  } finally {
    if (previousOpenclawHome === undefined) {
      delete process.env.OPENCLAW_HOME;
    } else {
      process.env.OPENCLAW_HOME = previousOpenclawHome;
    }
    delete globalThis.__TEST_EXEC_FILE__;
    delete globalThis.__TEST_EXEC_FILE_ASYNC__;
    fs.rmSync(tempHome, { recursive: true, force: true });
  }

  console.log("smoke_openclaw_extension_runtime_fallback: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
