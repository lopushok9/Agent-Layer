#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
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

# Fail loudly (not -32000) if the resolved server cannot even be parsed.
if ! "$PYTHON_BIN" -m py_compile "$PLUGIN_ROOT/server.py" 2>/dev/null; then
  printf '{"error":"agent-wallet server.py failed to parse — runtime likely broken.","server_py":"%s","fix":"npx @agentlayer.tech/wallet install --yes (or: npx @agentlayer.tech/wallet rollback)"}\n' "$PLUGIN_ROOT/server.py" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$PLUGIN_ROOT/server.py"
