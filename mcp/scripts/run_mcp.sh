#!/bin/sh
set -eu

# Framework-neutral stdio launcher. It resolves the shared wallet runtime and
# deliberately keeps secrets out of MCP configuration files.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
MCP_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
OPENCLAW_HOME=${OPENCLAW_HOME:-"$HOME/.openclaw"}
PACKAGE_ROOT=${AGENT_WALLET_PACKAGE_ROOT:-${OPENCLAW_AGENT_WALLET_PACKAGE_ROOT:-"$MCP_ROOT/../agent-wallet"}}
export AGENT_WALLET_PACKAGE_ROOT="$PACKAGE_ROOT"

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

if [ ! -f "$MCP_ROOT/server.py" ]; then
  printf '{"error":"AgentLayer universal MCP server is missing.","fix":"wallet install --yes"}\n' >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys, ast; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$MCP_ROOT/server.py" 2>/dev/null; then
  printf '{"error":"AgentLayer universal MCP server failed to parse.","fix":"wallet install --yes (or: wallet rollback)"}\n' >&2
  exit 1
fi

: "${AGENT_WALLET_HOST:=mcp}"
export AGENT_WALLET_HOST

exec "$PYTHON_BIN" "$MCP_ROOT/server.py"
