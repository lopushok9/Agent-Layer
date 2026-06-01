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
  "$PYTHON_BIN" - "$SERVER_PY" >&2 <<'PY'
import json, sys
print(json.dumps({
    "error": "agent-wallet server.py failed to parse — runtime likely broken.",
    "server_py": sys.argv[1],
    "fix": "npx @agentlayer.tech/wallet install --yes (or: npx @agentlayer.tech/wallet rollback)",
}))
PY
  exit 1
fi

exec "$PYTHON_BIN" "$SERVER_PY"
