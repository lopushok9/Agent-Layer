#!/bin/sh
set -eu

# Physical paths (pwd -P) so symlinked install layouts resolve to the real dir.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PLUGIN_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
OPENCLAW_HOME=${OPENCLAW_HOME:-"$HOME/.openclaw"}
PACKAGE_ROOT=${AGENT_WALLET_PACKAGE_ROOT:-${OPENCLAW_AGENT_WALLET_PACKAGE_ROOT:-"$OPENCLAW_HOME/agent-wallet-runtime/current/agent-wallet"}}

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

if [ ! -f "$PLUGIN_ROOT/server.py" ]; then
  printf '{"error":"agent-wallet server.py not found in codex plugin.","fix":"npx @agentlayer.tech/wallet install --yes"}\n' >&2
  exit 1
fi

# Fail loudly (not -32000) if the resolved server cannot even be parsed.
# Use ast.parse (no bytecode written) so a read-only install dir cannot trigger
# a false "runtime broken" error from py_compile failing to write __pycache__.
if ! "$PYTHON_BIN" -c 'import sys, ast; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$PLUGIN_ROOT/server.py" 2>/dev/null; then
  "$PYTHON_BIN" - "$PLUGIN_ROOT/server.py" >&2 <<'PY'
import json, sys
print(json.dumps({
    "error": "agent-wallet server.py failed to parse — runtime likely broken.",
    "server_py": sys.argv[1],
    "fix": "npx @agentlayer.tech/wallet install --yes (or: npx @agentlayer.tech/wallet rollback)",
}))
PY
  exit 1
fi

exec "$PYTHON_BIN" "$PLUGIN_ROOT/server.py"
