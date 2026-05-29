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

exec "$PYTHON_BIN" "$PLUGIN_ROOT/server.py"
