#!/bin/sh
set -eu

# Resolve to PHYSICAL paths (pwd -P). Claude Code runs this plugin through a
# marketplace symlink (~/.claude/agentlayer-local/plugins/agent-wallet -> the real
# plugin dir). With a logical pwd, the symlink stays in PLUGIN_ROOT and the
# "../../../codex" sibling math below collapses lexically into a non-existent path
# (e.g. ~/.claude/codex), so `cd` fails and the server dies with -32000. Resolving
# the symlink up front keeps the `..` arithmetic consistent with the real layout.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PLUGIN_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
OPENCLAW_HOME=${OPENCLAW_HOME:-"$HOME/.openclaw"}
PACKAGE_ROOT=${AGENT_WALLET_PACKAGE_ROOT:-${OPENCLAW_AGENT_WALLET_PACKAGE_ROOT:-"$OPENCLAW_HOME/agent-wallet-runtime/current/agent-wallet"}}

# Resolve server.py. The claude-code plugin ships no server.py of its own; it
# reuses the sibling codex copy (real repo / installed runtime, where claude-code
# and codex sit side by side), falling back to the codex copy inside the runtime
# package, which is always present.
LOCAL_SERVER="$PLUGIN_ROOT/server.py"
CODEX_SERVER="$PLUGIN_ROOT/../../../codex/plugins/agent-wallet/server.py"
RUNTIME_CODEX_DIR="$OPENCLAW_HOME/agent-wallet-runtime/current/codex/plugins/agent-wallet"

if [ -f "$LOCAL_SERVER" ]; then
  SERVER_PY="$LOCAL_SERVER"
elif [ -f "$CODEX_SERVER" ]; then
  SERVER_PY=$(CDPATH= cd -- "$PLUGIN_ROOT/../../../codex/plugins/agent-wallet" && pwd -P)/server.py
elif [ -f "$RUNTIME_CODEX_DIR/server.py" ]; then
  SERVER_PY=$(CDPATH= cd -- "$RUNTIME_CODEX_DIR" && pwd -P)/server.py
else
  printf '{"error":"agent-wallet backend not installed yet (server.py not found in plugin, codex sibling, or runtime package).","fix":"Run /wallet-setup inside Claude Code, or: npx @agentlayer.tech/wallet install --yes"}\n' >&2
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
# Use ast.parse (no bytecode written) so a read-only install dir cannot trigger
# a false "runtime broken" error from py_compile failing to write __pycache__.
if ! "$PYTHON_BIN" -c 'import sys, ast; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$SERVER_PY" 2>/dev/null; then
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

# Tag anonymous telemetry with this frontend so adoption can be split per host
# (claude-code / codex / hermes / openclaw). An explicit override still wins.
: "${AGENT_WALLET_HOST:=claude-code}"
export AGENT_WALLET_HOST

exec "$PYTHON_BIN" "$SERVER_PY"
