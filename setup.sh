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

require_cmd python3
require_cmd node
require_cmd npm

require_path "$INSTALLER" "Python installer"
require_path "${ROOT_DIR}/agent-wallet" "agent-wallet package"
require_path "${ROOT_DIR}/.openclaw/extensions/agent-wallet" "OpenClaw extension"
require_path "${ROOT_DIR}/wdk-btc-wallet/package.json" "wdk-btc-wallet package"
require_path "${ROOT_DIR}/wdk-evm-wallet/package.json" "wdk-evm-wallet package"

exec python3 "$INSTALLER" \
  --package-root "${ROOT_DIR}/agent-wallet" \
  --extension-path "${ROOT_DIR}/.openclaw/extensions/agent-wallet" \
  --wdk-btc-root "${ROOT_DIR}/wdk-btc-wallet" \
  --wdk-evm-root "${ROOT_DIR}/wdk-evm-wallet" \
  --npm-bin "$(command -v npm)" \
  "$@"
