# Harden Wallet Runtime Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent-wallet MCP bridges fail loudly with actionable fixes (Layer 1+2) and make a broken/stale runtime impossible to activate (Layer 3+4), so issues like the v0.1.31 `SyntaxError` and the Claude "server.py not found" never silently surface as `-32000`.

**Architecture:** Three layers. (1) `run_mcp.sh` self-checks the resolved `server.py` and prints a structured, actionable error. (2) `doctor` validates the *live runtime* (`current`), runs a real MCP `initialize` handshake, resolves each wired editor the same way its launcher does, and attaches a `fix` command per failing check. (3) `install`/`update` verify the newly-activated release via handshake and auto-rollback `current → previous` on failure; codex/claude installs pin the resolved `OPENCLAW_HOME` + venv python into the editor `.mcp.json` env so the launcher never re-derives a divergent home.

**Tech Stack:** Node ESM (`bin/openclaw-agent-wallet.mjs`), POSIX `sh` (`run_mcp.sh`), Python 3.10+ runtime (FastMCP `server.py`), Python smoke tests (`agent-wallet/tests/smoke_*.py`) driven through the CLI with a temp `OPENCLAW_HOME`.

---

## File Structure

- `claude-code/plugins/agent-wallet/scripts/run_mcp.sh` — **modify**: add `py_compile` self-check + structured error (Layer 1). Codex launcher (`codex/plugins/agent-wallet/scripts/run_mcp.sh`) stays self-contained but gets the same self-check for parity.
- `bin/openclaw-agent-wallet.mjs` — **modify**:
  - new `verifyRuntime(releaseRoot, env)` helper (handshake gate) — Layer 2/3 shared.
  - new `resolveEditorServerChecks(env)` helper (per-editor resolution) — Layer 2.
  - rewrite `runDoctor()` to validate live runtime + emit `checks[]` with `fix` — Layer 2.
  - hook verify + auto-rollback into `runInstall()` after `switchSymlink(currentPath, releaseRoot)` — Layer 3.
  - pin env into editor `.mcp.json` in `runCodexInstall()` / `runClaudeCodeInstall()` — Layer 4.
- `agent-wallet/tests/smoke_run_mcp_resolution.py` — **create**: Layer 1 test.
- `agent-wallet/tests/smoke_doctor_runtime_checks.py` — **create**: Layer 2 test.
- `agent-wallet/tests/smoke_install_verify_rollback.py` — **create**: Layer 3 test.
- `agent-wallet/tests/smoke_editor_mcp_env_pin.py` — **create**: Layer 4 test.
- `CHANGELOG.md` — **modify**: Unreleased section.

**Testable seams added:**
- `AGENT_WALLET_VERIFY_FORCE_FAIL=1` → `verifyRuntime` returns failure without running python (deterministic rollback test).
- `AGENT_WALLET_VERIFY_DISABLE=1` → skip verify entirely (keeps existing smoke tests that install a stub runtime green).

---

## Task 1: Layer 1 — `run_mcp.sh` self-check + structured error

**Files:**
- Modify: `claude-code/plugins/agent-wallet/scripts/run_mcp.sh`
- Modify: `codex/plugins/agent-wallet/scripts/run_mcp.sh`
- Test: `agent-wallet/tests/smoke_run_mcp_resolution.py`

- [ ] **Step 1: Write the failing test**

Create `agent-wallet/tests/smoke_run_mcp_resolution.py`:

```python
"""Smoke test: run_mcp.sh resolves server.py and self-checks it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(launcher: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(launcher)],
        input="",
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    launcher = repo_root / "claude-code/plugins/agent-wallet/scripts/run_mcp.sh"
    tmp = Path("/tmp/openclaw-run-mcp-resolution")
    if tmp.exists():
        shutil.rmtree(tmp)
    home = tmp / "openclaw"
    runtime_codex = home / "agent-wallet-runtime/current/codex/plugins/agent-wallet"
    runtime_codex.mkdir(parents=True, exist_ok=True)

    base_env = dict(os.environ)
    base_env["OPENCLAW_HOME"] = str(home)
    base_env["AGENT_WALLET_PYTHON"] = sys.executable

    # Case A: no server.py anywhere -> structured "not found" error, exit 1.
    res = _run(launcher, base_env)
    assert res.returncode == 1, f"expected exit 1, got {res.returncode}: {res.stderr}"
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert "not found" in payload["error"].lower(), payload
    assert "install --yes" in payload["fix"], payload

    # Case B: server.py present but broken -> structured "failed to parse" error, exit 1.
    (runtime_codex / "server.py").write_text("def broken(\n", encoding="utf-8")
    res = _run(launcher, base_env)
    assert res.returncode == 1, f"expected exit 1, got {res.returncode}: {res.stderr}"
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert "parse" in payload["error"].lower(), payload
    assert payload["server_py"].endswith("server.py"), payload

    print("OK smoke_run_mcp_resolution")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 agent-wallet/tests/smoke_run_mcp_resolution.py`
Expected: FAIL — Case A error JSON currently has no `fix` key (`KeyError: 'fix'`), and Case B currently *succeeds in finding* the file but `exec`s it (no parse check), so it won't emit the parse error.

- [ ] **Step 3: Write minimal implementation**

In `claude-code/plugins/agent-wallet/scripts/run_mcp.sh`, replace the resolution `else` branch and add a self-check before `exec`. Final file:

```sh
#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
OPENCLAW_HOME=${OPENCLAW_HOME:-"$HOME/.openclaw"}
PACKAGE_ROOT=${AGENT_WALLET_PACKAGE_ROOT:-${OPENCLAW_AGENT_WALLET_PACKAGE_ROOT:-"$OPENCLAW_HOME/agent-wallet-runtime/current/agent-wallet"}}

# Resolve server.py. When Claude Code copies this plugin into its cache, the
# relative sibling paths below no longer resolve, so fall back to the codex
# plugin copy inside the installed runtime package, which is always present.
LOCAL_SERVER="$PLUGIN_ROOT/server.py"
CODEX_SERVER="$PLUGIN_ROOT/../../codex/plugins/agent-wallet/server.py"
RUNTIME_CODEX_DIR="$OPENCLAW_HOME/agent-wallet-runtime/current/codex/plugins/agent-wallet"

if [ -f "$LOCAL_SERVER" ]; then
  SERVER_PY="$LOCAL_SERVER"
elif [ -f "$CODEX_SERVER" ]; then
  SERVER_PY=$(CDPATH= cd -- "$PLUGIN_ROOT/../../codex/plugins/agent-wallet" && pwd)/server.py
elif [ -f "$RUNTIME_CODEX_DIR/server.py" ]; then
  SERVER_PY=$(CDPATH= cd -- "$RUNTIME_CODEX_DIR" && pwd)/server.py
else
  printf '{"error":"agent-wallet server.py not found in plugin, codex sibling, or runtime package.","fix":"npx @agentlayer.tech/wallet install --yes"}\n' >&2
  exit 1
fi

if [ -n "${AGENT_WALLET_PYTHON:-}" ]; then
  PYTHON_BIN=$AGENT_WALLET_PYTHON
elif [ -n "${OPENCLAW_AGENT_WALLET_PYTHON:-}" ]; then
  PYTHON_BIN=$OPENCLAW_AGENT_WALLET_PYTHON
elif [ -x "$PACKAGE_ROOT/.venv/bin/python" ]; then
  PYTHON_BIN=$PACKAGE_ROOT/.venv/bin/python
elif [ -x "$PACKAGE_ROOT/.runtime-venv/bin/python" ]; then
  PYTHON_BIN=$PACKAGE_ROOT/.runtime-venv/bin/python
else
  PYTHON_BIN=python3
fi

# Fail loudly (not -32000) if the resolved server cannot even be parsed.
if ! "$PYTHON_BIN" -m py_compile "$SERVER_PY" 2>/dev/null; then
  printf '{"error":"agent-wallet server.py failed to parse — runtime likely broken.","server_py":"%s","fix":"npx @agentlayer.tech/wallet install --yes (or: npx @agentlayer.tech/wallet rollback)"}\n' "$SERVER_PY" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SERVER_PY"
```

Apply the identical self-check block (the `if ! "$PYTHON_BIN" -m py_compile ...` lines before `exec`) to `codex/plugins/agent-wallet/scripts/run_mcp.sh`, immediately before its `exec "$PYTHON_BIN" "$PLUGIN_ROOT/server.py"` line, using `"$PLUGIN_ROOT/server.py"` as the `SERVER_PY` value in the message.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 agent-wallet/tests/smoke_run_mcp_resolution.py`
Expected: `OK smoke_run_mcp_resolution`

- [ ] **Step 5: Commit**

```bash
git add claude-code/plugins/agent-wallet/scripts/run_mcp.sh codex/plugins/agent-wallet/scripts/run_mcp.sh agent-wallet/tests/smoke_run_mcp_resolution.py
git commit -m "agent-wallet: launcher self-checks server.py and emits actionable errors"
```

---

## Task 2: Layer 2 — `verifyRuntime()` handshake helper

**Files:**
- Modify: `bin/openclaw-agent-wallet.mjs` (add helper near `activePythonRuntimeInfo`, ~line 305)
- Test: covered indirectly by Task 3/4 tests; add a direct unit invocation here.

- [ ] **Step 1: Write the failing test**

Create `agent-wallet/tests/smoke_verify_runtime.py`:

```python
"""Smoke test: verifyRuntime gate via the hidden --self-verify command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVER_STUB = '''import sys, json
line = sys.stdin.readline()
req = json.loads(line)
print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":{"serverInfo":{"name":"Agent Wallet","version":"test"}}}))
sys.stdout.flush()
'''


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    tmp = Path("/tmp/openclaw-verify-runtime")
    if tmp.exists():
        shutil.rmtree(tmp)
    release = tmp / "release"
    codex_dir = release / "codex/plugins/agent-wallet"
    venv_bin = release / "agent-wallet/.runtime-venv/bin"
    codex_dir.mkdir(parents=True, exist_ok=True)
    venv_bin.mkdir(parents=True, exist_ok=True)
    # Symlink the venv python to the host python so the handshake can run.
    (venv_bin / "python").symlink_to(sys.executable)

    env = dict(os.environ)

    # Good server -> ok true.
    (codex_dir / "server.py").write_text(SERVER_STUB, encoding="utf-8")
    res = subprocess.run(
        ["node", str(cli), "--self-verify", str(release)],
        capture_output=True, text=True, env=env, timeout=40,
    )
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True, payload
    assert res.returncode == 0

    # Broken server -> ok false, exit 1.
    (codex_dir / "server.py").write_text("def broken(\n", encoding="utf-8")
    res = subprocess.run(
        ["node", str(cli), "--self-verify", str(release)],
        capture_output=True, text=True, env=env, timeout=40,
    )
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False, payload
    assert res.returncode == 1

    print("OK smoke_verify_runtime")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 agent-wallet/tests/smoke_verify_runtime.py`
Expected: FAIL — `--self-verify` is an unknown command; the CLI defaults to `install` and errors / does not emit `{"ok":...}`.

- [ ] **Step 3: Write minimal implementation**

In `bin/openclaw-agent-wallet.mjs`, add this helper (place after `activePythonRuntimeInfo`, before `runDoctor`):

```js
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

function verifyRuntime(releaseRoot, env = process.env) {
  if (String(env.AGENT_WALLET_VERIFY_DISABLE || "") === "1") {
    return { ok: true, skipped: true };
  }
  if (String(env.AGENT_WALLET_VERIFY_FORCE_FAIL || "") === "1") {
    return { ok: false, error: "verify forced to fail (AGENT_WALLET_VERIFY_FORCE_FAIL)" };
  }
  const serverPy = path.join(releaseRoot, "codex", "plugins", "agent-wallet", "server.py");
  if (!fs.existsSync(serverPy)) {
    return { ok: false, error: `server.py missing at ${serverPy}` };
  }
  const python = resolveVenvPython(releaseRoot) || commandPath("python3") || "python3";
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
    return { ok: false, error: `handshake spawn failed: ${probe.error.message}` };
  }
  const out = String(probe.stdout || "");
  if (out.includes('"serverInfo"')) {
    return { ok: true };
  }
  const detail = (probe.stderr || out || "").trim().split("\n").slice(-3).join(" ");
  return { ok: false, error: `MCP initialize handshake failed: ${detail || "no serverInfo in response"}` };
}
```

Then register the hidden command. In the command-dispatch tail (after the `doctor` block, ~line 1426), add:

```js
if (command === "--self-verify") {
  const releaseRoot = args[1] ? path.resolve(expandHome(args[1])) : resolvedCurrentRuntimeRoot();
  const result = releaseRoot
    ? verifyRuntime(releaseRoot)
    : { ok: false, error: "no runtime to verify" };
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.ok ? 0 : 1);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 agent-wallet/tests/smoke_verify_runtime.py`
Expected: `OK smoke_verify_runtime`

- [ ] **Step 5: Commit**

```bash
git add bin/openclaw-agent-wallet.mjs agent-wallet/tests/smoke_verify_runtime.py
git commit -m "agent-wallet: add verifyRuntime() MCP handshake gate + --self-verify"
```

---

## Task 3: Layer 2 — `doctor` validates the live runtime with fixes

**Files:**
- Modify: `bin/openclaw-agent-wallet.mjs` (`runDoctor`, lines 620-670; add `resolveEditorServerChecks`)
- Test: `agent-wallet/tests/smoke_doctor_runtime_checks.py`

- [ ] **Step 1: Write the failing test**

Create `agent-wallet/tests/smoke_doctor_runtime_checks.py`:

```python
"""Smoke test: doctor validates the live runtime and reports fixes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVER_STUB = '''import sys, json
req = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":{"serverInfo":{"name":"Agent Wallet","version":"t"}}}))
sys.stdout.flush()
'''


def _doctor(cli: Path, env: dict) -> dict:
    res = subprocess.run(["node", str(cli), "doctor", "--deep"],
                         capture_output=True, text=True, env=env, timeout=60)
    return json.loads(res.stdout.strip()), res.returncode


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    tmp = Path("/tmp/openclaw-doctor-runtime")
    if tmp.exists():
        shutil.rmtree(tmp)
    home = tmp / "openclaw"
    release = home / "agent-wallet-runtime/releases/9.9.9"
    codex_dir = release / "codex/plugins/agent-wallet"
    venv_bin = release / "agent-wallet/.runtime-venv/bin"
    codex_dir.mkdir(parents=True, exist_ok=True)
    venv_bin.mkdir(parents=True, exist_ok=True)
    (venv_bin / "python").symlink_to(sys.executable)
    current = home / "agent-wallet-runtime/current"
    current.symlink_to(release)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(home)

    # Healthy runtime -> all checks ok, exit 0.
    (codex_dir / "server.py").write_text(SERVER_STUB, encoding="utf-8")
    payload, code = _doctor(cli, env)
    names = {c["name"]: c for c in payload["checks"]}
    assert names["current_symlink"]["ok"] is True, payload
    assert names["server_py_parses"]["ok"] is True, payload
    assert names["mcp_initialize_handshake"]["ok"] is True, payload
    assert payload["ok"] is True and code == 0, payload

    # Broken server.py -> handshake/parse fail with a fix string, exit 1.
    (codex_dir / "server.py").write_text("def broken(\n", encoding="utf-8")
    payload, code = _doctor(cli, env)
    names = {c["name"]: c for c in payload["checks"]}
    assert names["server_py_parses"]["ok"] is False, payload
    assert "install --yes" in names["server_py_parses"]["fix"], payload
    assert payload["ok"] is False and code == 1, payload

    print("OK smoke_doctor_runtime_checks")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 agent-wallet/tests/smoke_doctor_runtime_checks.py`
Expected: FAIL — current `doctor` output has no `checks` key (`KeyError: 'checks'`).

- [ ] **Step 3: Write minimal implementation**

In `bin/openclaw-agent-wallet.mjs`, add `resolveEditorServerChecks` and replace `runDoctor`:

```js
function resolveEditorServerChecks(env = process.env) {
  const checks = [];
  // Claude Code cache copies: resolve server.py the way run_mcp.sh does.
  const runtimeCodex = (() => {
    const root = resolvedCurrentRuntimeRoot(env);
    return root ? path.join(root, "codex", "plugins", "agent-wallet", "server.py") : null;
  })();
  const claudeCacheGlobRoot = expandHome("~/.claude/plugins/cache");
  if (fs.existsSync(claudeCacheGlobRoot)) {
    const reachable = runtimeCodex && fs.existsSync(runtimeCodex);
    checks.push({
      name: "editor:claude-code",
      ok: Boolean(reachable),
      error: reachable ? "" : "Claude cache copy cannot resolve server.py from runtime",
      fix: reachable ? "" : "npx @agentlayer.tech/wallet claude-code install --yes",
    });
  }
  // Codex: plugin symlink target under the codex plugin install root.
  const codexTarget = path.join(resolveCodexPluginInstallRoot(env), "agent-wallet", "server.py");
  if (fs.existsSync(path.dirname(path.dirname(codexTarget)))) {
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

  // Host prerequisites.
  for (const command of ["node", "npm"]) {
    checks.push({
      name: `command:${command}`,
      ok: hasCommand(command),
      error: hasCommand(command) ? "" : `${command} not found on PATH`,
      fix: hasCommand(command) ? "" : `install ${command}`,
    });
  }
  const python = selectedPythonProbe();
  checks.push({
    name: "python>=3.10",
    ok: Boolean(python.path && python.version_ok && python.venv_ok),
    error: !python.path ? "python3 not found"
      : !python.version_ok ? `selected python ${python.version} < 3.10`
      : !python.venv_ok ? `python ${python.version} lacks venv/ensurepip` : "",
    fix: python.path && python.version_ok && python.venv_ok ? "" : "install python>=3.10 with venv",
  });

  // Live runtime integrity.
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
      : parseOk ? "" : "server.py present but failed to parse",
    fix: parseOk ? "" : fixInstall,
  });

  if (deep && currentRoot) {
    const verify = verifyRuntime(currentRoot, env);
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

  const ok = checks.every((c) => c.ok);
  console.log(
    JSON.stringify(
      {
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
```

Update the dispatch call (line ~1425) from `process.exit(runDoctor());` to `process.exit(runDoctor(args.slice(1)));`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 agent-wallet/tests/smoke_doctor_runtime_checks.py`
Expected: `OK smoke_doctor_runtime_checks`

- [ ] **Step 5: Commit**

```bash
git add bin/openclaw-agent-wallet.mjs agent-wallet/tests/smoke_doctor_runtime_checks.py
git commit -m "agent-wallet: doctor validates live runtime + per-editor resolution with fixes"
```

---

## Task 4: Layer 3 — install verify + auto-rollback

**Files:**
- Modify: `bin/openclaw-agent-wallet.mjs` (`runInstall`, after `switchSymlink(currentPath, releaseRoot)` at line 787)
- Test: `agent-wallet/tests/smoke_install_verify_rollback.py`

- [ ] **Step 1: Write the failing test**

Create `agent-wallet/tests/smoke_install_verify_rollback.py`. It drives a real install into a temp home, then forces verify failure and asserts `current` rolls back to `previous`:

```python
"""Smoke test: a release that fails verification is auto-rolled-back."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _install(cli: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(cli), "install", "--yes", "--backend", "none"],
        capture_output=True, text=True, env=env, timeout=600,
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    version = json.loads((repo_root / "package.json").read_text())["version"]
    tmp = Path("/tmp/openclaw-install-rollback")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(tmp)
    env["AGENT_WALLET_BOOT_KEY"] = "test-boot"
    env["AGENT_WALLET_MASTER_KEY"] = "test-master"
    env["AGENT_WALLET_APPROVAL_SECRET"] = "test-approval"

    current = tmp / "agent-wallet-runtime/current"

    # 1) First install with verify disabled -> establishes a known-good current.
    env1 = {**env, "AGENT_WALLET_VERIFY_DISABLE": "1"}
    res = _install(cli, env1)
    assert res.returncode == 0, res.stderr
    good_target = os.readlink(current)
    assert version in good_target, good_target

    # 2) Second install with forced verify failure -> must roll back to good target.
    env2 = {**env, "AGENT_WALLET_VERIFY_FORCE_FAIL": "1"}
    res = _install(cli, env2)
    assert res.returncode != 0, "install should fail when verify fails"
    assert "rolled back" in (res.stderr + res.stdout).lower(), res.stderr
    after = os.readlink(current)
    assert after == good_target, f"current not rolled back: {after} != {good_target}"

    print("OK smoke_install_verify_rollback")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 agent-wallet/tests/smoke_install_verify_rollback.py`
Expected: FAIL — install currently ignores verify; second install leaves `current` pointing at the new (forced-fail) release, and no "rolled back" message is printed.

- [ ] **Step 3: Write minimal implementation**

In `runInstall`, immediately after the symlink switch block (after line 787 `switchSymlink(currentPath, releaseRoot);`), insert the verify gate:

```js
  const verification = verifyRuntime(releaseRoot, env);
  if (!verification.ok && !verification.skipped) {
    const rollbackTarget = currentTarget; // pre-switch target, if any
    if (rollbackTarget && existingRuntimePointerTarget(currentPath)) {
      switchSymlink(currentPath, rollbackTarget);
    }
    console.error(
      JSON.stringify(
        {
          ok: false,
          command: commandName,
          version: packageVersion,
          error: `runtime verification failed: ${verification.error}`,
          rolled_back: Boolean(rollbackTarget),
          current_runtime_target: readLinkOrNull(currentPath),
          fix: "npx @agentlayer.tech/wallet rollback",
        },
        null,
        2,
      ),
    );
    return 1;
  }
```

Note: `currentTarget` is already captured at line 783 (`const currentTarget = existingRuntimePointerTarget(currentPath);`) before the switch, so it holds the previous good target.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 agent-wallet/tests/smoke_install_verify_rollback.py`
Expected: `OK smoke_install_verify_rollback`

- [ ] **Step 5: Run the existing install smoke test to confirm no regression**

Run: `python3 agent-wallet/tests/smoke_npm_installer.py`
Expected: PASS (it installs a real runtime; verify runs the genuine handshake and succeeds). If the sandbox cannot build the venv, set `AGENT_WALLET_VERIFY_DISABLE=1` for that legacy test invocation and note it.

- [ ] **Step 6: Commit**

```bash
git add bin/openclaw-agent-wallet.mjs agent-wallet/tests/smoke_install_verify_rollback.py
git commit -m "agent-wallet: verify new release on install and auto-rollback current on failure"
```

---

## Task 5: Layer 4 — pin OPENCLAW_HOME + venv python into editor `.mcp.json`

**Files:**
- Modify: `bin/openclaw-agent-wallet.mjs` (`runCodexInstall` line 1190, `runClaudeCodeInstall` line 1326; add `pinEditorMcpEnv` helper)
- Test: `agent-wallet/tests/smoke_editor_mcp_env_pin.py`

Rationale: the plugin sources are symlinked from the per-user release bundle, so the bundle's `.mcp.json` (`releases/<v>/{codex,claude-code}/plugins/agent-wallet/.mcp.json`) is safe to rewrite with the resolved absolute home/python. `run_mcp.sh` already honors `OPENCLAW_HOME` and `AGENT_WALLET_PYTHON`, so pinning them removes the divergence class.

- [ ] **Step 1: Write the failing test**

Create `agent-wallet/tests/smoke_editor_mcp_env_pin.py`:

```python
"""Smoke test: codex/claude install pins OPENCLAW_HOME into .mcp.json env."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "bin/openclaw-agent-wallet.mjs"
    tmp = Path("/tmp/openclaw-mcp-env-pin")
    if tmp.exists():
        shutil.rmtree(tmp)
    home = tmp / "home"
    # Pre-stage a current runtime so the resolver has a venv python to pin.
    release = home / "agent-wallet-runtime/releases/9.9.9"
    venv_bin = release / "agent-wallet/.runtime-venv/bin"
    mcp_dir = release / "claude-code/plugins/agent-wallet"
    venv_bin.mkdir(parents=True, exist_ok=True)
    mcp_dir.mkdir(parents=True, exist_ok=True)
    (venv_bin / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    (mcp_dir / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"agent-wallet": {"command": "sh",
            "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/run_mcp.sh"],
            "env": {"FASTMCP_LOG_LEVEL": "ERROR"}}}}), encoding="utf-8")
    (home / "agent-wallet-runtime/current").symlink_to(release)

    env = dict(os.environ)
    env["OPENCLAW_HOME"] = str(home)
    env["AGENT_WALLET_CLAUDE_CODE_MARKETPLACE_DIR"] = str(tmp / "marketplace")
    env["AGENT_WALLET_CLAUDE_CODE_PLUGIN_SOURCE"] = str(mcp_dir)

    res = subprocess.run(
        ["node", str(cli), "claude-code", "install", "--yes", "--skip-enable"],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert res.returncode == 0, res.stderr + res.stdout

    pinned = json.loads((mcp_dir / ".mcp.json").read_text())
    server_env = pinned["mcpServers"]["agent-wallet"]["env"]
    assert server_env["OPENCLAW_HOME"] == str(home), server_env
    assert server_env["AGENT_WALLET_PYTHON"].endswith("python"), server_env

    print("OK smoke_editor_mcp_env_pin")


if __name__ == "__main__":
    main()
```

(If `resolveClaudeCodePluginSource` does not already honor an env override, add support for `AGENT_WALLET_CLAUDE_CODE_PLUGIN_SOURCE` in that resolver as part of Step 3 so the test can point at a temp bundle.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 agent-wallet/tests/smoke_editor_mcp_env_pin.py`
Expected: FAIL — `.mcp.json` env has no `OPENCLAW_HOME` / `AGENT_WALLET_PYTHON` keys after install.

- [ ] **Step 3: Write minimal implementation**

Add the helper near `ensureClaudeCodeMarketplace` (~line 1279):

```js
function pinEditorMcpEnv(pluginSource, env = process.env) {
  const mcpPath = path.join(pluginSource, ".mcp.json");
  if (!fs.existsSync(mcpPath)) return { pinned: false, reason: "no .mcp.json" };
  let doc;
  try {
    doc = JSON.parse(fs.readFileSync(mcpPath, "utf8"));
  } catch (error) {
    return { pinned: false, reason: `unreadable .mcp.json: ${error.message}` };
  }
  const servers = doc.mcpServers || {};
  const entry = servers["agent-wallet"];
  if (!entry) return { pinned: false, reason: "no agent-wallet server entry" };
  const currentRoot = resolvedCurrentRuntimeRoot(env);
  const venvPython = currentRoot ? resolveVenvPython(currentRoot) : null;
  entry.env = {
    ...(entry.env || {}),
    OPENCLAW_HOME: resolveOpenclawHome(env),
    ...(venvPython ? { AGENT_WALLET_PYTHON: venvPython } : {}),
  };
  writeJsonFile(mcpPath, doc);
  return { pinned: true, openclaw_home: resolveOpenclawHome(env), python: venvPython };
}
```

In `runClaudeCodeInstall`, right after `const pluginSource = resolveClaudeCodePluginSource();`, add:

```js
  const pinned = pinEditorMcpEnv(pluginSource);
```

and include `pinned_env: pinned` in the printed JSON payload.

In `runCodexInstall`, right after `const pluginSource = resolveCodexPluginSource();`, add the same `const pinned = pinEditorMcpEnv(pluginSource);` and include `pinned_env: pinned` in its JSON payload.

If needed for the test, extend `resolveClaudeCodePluginSource` to honor `env.AGENT_WALLET_CLAUDE_CODE_PLUGIN_SOURCE` before its existing default.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 agent-wallet/tests/smoke_editor_mcp_env_pin.py`
Expected: `OK smoke_editor_mcp_env_pin`

- [ ] **Step 5: Commit**

```bash
git add bin/openclaw-agent-wallet.mjs agent-wallet/tests/smoke_editor_mcp_env_pin.py
git commit -m "agent-wallet: pin OPENCLAW_HOME + venv python into editor .mcp.json on install"
```

---

## Task 6: Docs + full smoke sweep

**Files:**
- Modify: `CHANGELOG.md` (Unreleased)

- [ ] **Step 1: Add changelog entry**

Under `## Unreleased` in `CHANGELOG.md`, add:

```markdown
- Hardened runtime resolution end-to-end. `run_mcp.sh` now self-checks the
  resolved `server.py` with `py_compile` and emits a structured, actionable
  error instead of surfacing a bare MCP `-32000`. `doctor`/`doctor --deep`
  validate the live `current` runtime (symlink integrity, venv python,
  `server.py` parse, real MCP `initialize` handshake) and per-editor
  resolution, attaching a `fix` command to every failing check. `install` and
  `update` now verify the newly-activated release via handshake and
  auto-rollback `current → previous` on failure, so a broken release can no
  longer become active. `codex install` / `claude-code install` pin the
  resolved `OPENCLAW_HOME` and venv python into the editor `.mcp.json` env,
  eliminating launcher/installer home divergence.
```

- [ ] **Step 2: Run the full new + adjacent smoke sweep**

Run:
```bash
for t in smoke_run_mcp_resolution smoke_verify_runtime smoke_doctor_runtime_checks \
         smoke_install_verify_rollback smoke_editor_mcp_env_pin; do
  echo "== $t =="; python3 agent-wallet/tests/$t.py || break
done
node --check bin/openclaw-agent-wallet.mjs
```
Expected: each prints `OK ...`; `node --check` is silent (valid).

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for runtime-resolution hardening"
```

---

## Self-Review

**Spec coverage:**
- Layer 1 (actionable errors) → Task 1 (launcher self-check + structured error). ✓
- Layer 2 (smart doctor: current/venv/parse/handshake/per-editor + fix) → Task 2 (`verifyRuntime`) + Task 3 (`runDoctor` rewrite, `resolveEditorServerChecks`). ✓
- Layer 3a (post-install verify + auto-rollback) → Task 4. ✓
- Layer 3b/Layer 4 (pin OPENCLAW_HOME, kill divergence) → Task 5. ✓
- Docs/changelog + regression sweep → Task 6. ✓

**Placeholder scan:** No TBD/"handle errors"/"similar to" — every code step shows full code. ✓

**Type/name consistency:** `verifyRuntime(releaseRoot, env)` returns `{ ok, skipped?, error? }` and is called identically in Task 3 (doctor `--deep`), Task 4 (install gate), and the `--self-verify` command. `resolveVenvPython(releaseRoot)` defined in Task 2 and reused in Tasks 3 and 5. `resolvedCurrentRuntimeRoot`, `currentRuntimePath`, `existingRuntimePointerTarget`, `switchSymlink`, `readLinkOrNull`, `resolveOpenclawHome`, `writeJsonFile`, `resolveCodexPluginInstallRoot`, `hasFlag`, `expandHome`, `commandPath`, `spawnSync`, `selectedPythonProbe`, `hasCommand` are all pre-existing helpers in `bin/openclaw-agent-wallet.mjs`. Test seam env vars `AGENT_WALLET_VERIFY_DISABLE` / `AGENT_WALLET_VERIFY_FORCE_FAIL` are honored only inside `verifyRuntime`. ✓

**Known risk:** `runCodexInstall`/`runClaudeCodeInstall` symlink the plugin from the bundle; pinning rewrites the bundle's `.mcp.json` (per-user, per-release) — safe on single-user machines. If a future multi-user layout shares a release bundle read-only, Task 5 must switch from rewriting the bundle to copying the plugin per-user. Noted for the executor.
