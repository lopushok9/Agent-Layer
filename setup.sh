#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALLER="${ROOT_DIR}/agent-wallet/scripts/install_agent_wallet.py"

require_path() {
  target="$1"
  label="$2"
  if [ ! -e "$target" ]; then
    printf 'Missing %s at %s\n' "$label" "$target" >&2
    exit 1
  fi
}

require_cmd() {
  name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$name" >&2
    exit 1
  fi
}

find_python() {
  if [ -n "${OPENCLAW_AGENT_WALLET_PYTHON:-}" ]; then
    if is_usable_python "$OPENCLAW_AGENT_WALLET_PYTHON"; then
      printf '%s\n' "$OPENCLAW_AGENT_WALLET_PYTHON"
      return
    fi
    printf 'OPENCLAW_AGENT_WALLET_PYTHON is not usable for this installer: %s\n' "$OPENCLAW_AGENT_WALLET_PYTHON" >&2
    exit 1
  fi
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      candidate_path="$(command -v "$candidate")"
      if is_usable_python "$candidate_path"; then
        printf '%s\n' "$candidate_path"
        return
      fi
    fi
  done
  printf 'Required Python not found: need Python >= 3.10 with working venv/ensurepip.\n' >&2
  printf 'Install Python 3.10+ or set OPENCLAW_AGENT_WALLET_PYTHON=/path/to/working/python3.\n' >&2
  exit 1
}

is_usable_python() {
  python_bin="$1"
  "$python_bin" - <<'PY' >/dev/null 2>&1
import sys

if sys.version_info < (3, 10):
    raise SystemExit(
        "OpenClaw Agent Wallet requires Python >= 3.10. "
        f"Selected interpreter is {sys.version.split()[0]}. "
        "Install Python 3.10+ or set OPENCLAW_AGENT_WALLET_PYTHON=/path/to/python3."
    )
PY
  if [ "$?" -ne 0 ]; then
    return 1
  fi
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/openclaw-python-check.XXXXXX")"
  "$python_bin" -m venv "$tmp_dir/venv" >/dev/null 2>&1
  status="$?"
  rm -rf "$tmp_dir"
  return "$status"
}

PYTHON_BIN="$(find_python)"

require_cmd node
require_cmd npm

require_path "$INSTALLER" "Python installer"
require_path "${ROOT_DIR}/agent-wallet" "agent-wallet package"
require_path "${ROOT_DIR}/.openclaw/extensions/agent-wallet" "OpenClaw extension"
require_path "${ROOT_DIR}/wdk-btc-wallet/package.json" "wdk-btc-wallet package"
require_path "${ROOT_DIR}/wdk-evm-wallet/package.json" "wdk-evm-wallet package"

exec "$PYTHON_BIN" "$INSTALLER" \
  --package-root "${ROOT_DIR}/agent-wallet" \
  --extension-path "${ROOT_DIR}/.openclaw/extensions/agent-wallet" \
  --wdk-btc-root "${ROOT_DIR}/wdk-btc-wallet" \
  --wdk-evm-root "${ROOT_DIR}/wdk-evm-wallet" \
  --npm-bin "$(command -v npm)" \
  "$@"
