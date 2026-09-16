#!/bin/sh
set -eu

# Orchestrates enabling the wallet-balance statusLine:
#   1. Resolve the Base + Solana addresses once via the real MCP server
#      (resolve_wallet_addresses.py), using the same interpreter/venv
#      resolution as run_mcp.sh so it can actually import the `mcp` client.
#   2. Copy the lightweight polling script to a stable location outside the
#      plugin cache (so a plugin update/reinstall doesn't move the path a
#      user's settings.json already points at).
#   3. Register it in ~/.claude/settings.json (enable_statusline.py), which
#      refuses to clobber a different statusLine the user already has.

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

RUN_MCP="$SCRIPT_DIR/run_mcp.sh"

echo "Resolving wallet addresses (can take several seconds on a cold wallet backend)..." >&2
"$PYTHON_BIN" "$SCRIPT_DIR/resolve_wallet_addresses.py" "$RUN_MCP"

STABLE_DIR="$OPENCLAW_HOME/wallet-statusline"
mkdir -p "$STABLE_DIR"
cp "$SCRIPT_DIR/wallet_statusline.py" "$STABLE_DIR/wallet_statusline.py"

python3 "$SCRIPT_DIR/enable_statusline.py" "$STABLE_DIR/wallet_statusline.py"
