#!/bin/sh
set -eu

# bootstrap_backend.sh — the in-CLI bridge to the npm installer.
#
# Claude Code's plugin marketplace only copies the plugin files (this MCP bridge
# and its skill) into the cache. It does NOT lay down the Python backend runtime
# (venv + agent_wallet package + server.py + sealed-secret handling) that the
# bridge talks to. This script closes that gap: it detects whether the backend
# runtime is present and, if not, delegates to the existing npm installer
# (`npx @agentlayer.tech/wallet install --yes`) so the whole thing can be set up
# without leaving the Claude Code CLI.
#
# Modes:
#   bootstrap_backend.sh check     Report readiness only. Exit 0 if ready, 1 if not.
#                                  Never installs anything.
#   bootstrap_backend.sh install   Ensure the backend is installed (default).
#                                  Idempotent: a no-op when already healthy.
#
# Used by:
#   - /wallet-setup slash command  -> `install` (explicit, user-initiated).
#   - SessionStart hook            -> `install` by default, so the backend sets
#                                     itself up on first session. Set
#                                     AGENT_WALLET_AUTO_BOOTSTRAP=0 to opt out and
#                                     get only a soft hint to run /wallet-setup.

MODE=${1:-install}

PACKAGE_SPEC=${AGENT_WALLET_BOOTSTRAP_PACKAGE:-"@agentlayer.tech/wallet@latest"}
OPENCLAW_HOME=${OPENCLAW_HOME:-"$HOME/.openclaw"}
RUNTIME_CURRENT="$OPENCLAW_HOME/agent-wallet-runtime/current"

# Resolve this script's plugin root with physical paths (pwd -P), the same way
# run_mcp.sh does, so a marketplace symlink does not break the "../../../codex"
# sibling math below.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PLUGIN_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)

log() {
  printf '%s\n' "$*" >&2
}

# Locate server.py exactly like run_mcp.sh: the plugin's own copy, then the codex
# sibling in a repo checkout, then the installed runtime package. Keeping this in
# lock-step with run_mcp.sh is what avoids a false "not installed" verdict in a
# dev checkout, where run_mcp.sh resolves the codex sibling but this script used
# to look only at the runtime path.
resolve_server() {
  if [ -f "$PLUGIN_ROOT/server.py" ]; then
    printf '%s' "$PLUGIN_ROOT/server.py"
  elif [ -f "$PLUGIN_ROOT/../../../codex/plugins/agent-wallet/server.py" ]; then
    printf '%s' "$PLUGIN_ROOT/../../../codex/plugins/agent-wallet/server.py"
  elif [ -f "$RUNTIME_CURRENT/codex/plugins/agent-wallet/server.py" ]; then
    printf '%s' "$RUNTIME_CURRENT/codex/plugins/agent-wallet/server.py"
  else
    printf '%s' ''
  fi
}

resolve_python() {
  if [ -n "${AGENT_WALLET_PYTHON:-}" ]; then
    printf '%s' "$AGENT_WALLET_PYTHON"
  elif [ -x "$RUNTIME_CURRENT/agent-wallet/.venv/bin/python" ]; then
    printf '%s' "$RUNTIME_CURRENT/agent-wallet/.venv/bin/python"
  elif [ -x "$RUNTIME_CURRENT/agent-wallet/.runtime-venv/bin/python" ]; then
    printf '%s' "$RUNTIME_CURRENT/agent-wallet/.runtime-venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    printf '%s' python3
  else
    printf '%s' ''
  fi
}

# Readiness proxy: the resolved server.py exists and parses (ast.parse, no
# bytecode written) — the same shallow check run_mcp.sh and `doctor` run before
# exec. It deliberately does NOT verify that the venv/dependencies are installed:
# importing or running the server would be too slow and flaky for a SessionStart
# hook and risks false-negative reinstall loops. run_mcp.sh surfaces any missing
# dependency with a clear error at first tool use, so this stays in lock-step
# with what actually runs the server rather than being stricter than it.
backend_ready() {
  server=$(resolve_server)
  [ -n "$server" ] || return 1
  py=$(resolve_python)
  [ -n "$py" ] || return 1
  "$py" -c 'import sys, ast; ast.parse(open(sys.argv[1], encoding="utf-8").read())' "$server" 2>/dev/null
}

if backend_ready; then
  [ "$MODE" = "check" ] || log "AgentLayer wallet backend already installed (server: $(resolve_server))."
  exit 0
fi

if [ "$MODE" = "check" ]; then
  log "AgentLayer wallet backend is not installed yet."
  log "Run /wallet-setup inside Claude Code to install it."
  exit 1
fi

# --- install path -----------------------------------------------------------

if ! command -v npx >/dev/null 2>&1; then
  log "Cannot install the AgentLayer wallet backend: npx (Node.js) was not found on PATH."
  log "Install Node.js 18+ and re-run /wallet-setup, or run manually:"
  log "  npx $PACKAGE_SPEC install --yes"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  log "Warning: python3 was not found on PATH. The installer needs Python >= 3.10 with venv."
  log "Install Python and re-run /wallet-setup if the install below fails."
fi

log "Installing the AgentLayer wallet backend runtime via npm (this may take a minute)…"
log "  -> npx $PACKAGE_SPEC install --yes"
if ! AGENT_WALLET_INSTALL_SOURCE=claude_marketplace_bootstrap npx -y "$PACKAGE_SPEC" install --yes; then
  log "Backend install failed. Ensure Node.js 18+ and Python >= 3.10 (with venv) are installed, then re-run /wallet-setup."
  exit 1
fi

# Re-pin the Claude Code cache copies so run_mcp.sh resolves OPENCLAW_HOME and the
# freshly installed runtime correctly (pinClaudeCacheCopies / marketplace wiring).
# --skip-enable: the plugin is already registered via the marketplace, so we only
# want the file pinning, not another `claude plugin install`.
log "Wiring the Claude Code bridge to the installed runtime…"
AGENT_WALLET_INSTALL_SOURCE=claude_marketplace_bootstrap npx -y "$PACKAGE_SPEC" claude-code install --yes --skip-enable || \
  log "Note: could not re-pin the Claude Code bridge automatically; it will still resolve the default runtime."

if backend_ready; then
  log "Done. The AgentLayer wallet backend is installed."
  log "Restart Claude Code (or reload the agent-wallet plugin) to activate the wallet tools."
  exit 0
fi

log "Install completed but the backend did not verify. Run: npx $PACKAGE_SPEC doctor --deep"
exit 1
