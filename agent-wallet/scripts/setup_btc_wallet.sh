#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PACKAGE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

resolve_python_bin() {
  if [ -n "${OPENCLAW_AGENT_WALLET_PYTHON:-}" ] && [ -x "${OPENCLAW_AGENT_WALLET_PYTHON}" ]; then
    printf "%s" "${OPENCLAW_AGENT_WALLET_PYTHON}"
    return 0
  fi

  if [ -x "/tmp/agent-wallet-venv/bin/python" ]; then
    printf "%s" "/tmp/agent-wallet-venv/bin/python"
    return 0
  fi

  if [ -x "$PACKAGE_ROOT/.venv/bin/python" ]; then
    printf "%s" "$PACKAGE_ROOT/.venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  command -v python
}

PYTHON_BIN=$(resolve_python_bin)
export OPENCLAW_AGENT_WALLET_PYTHON="$PYTHON_BIN"

has_flag() {
  flag=$1
  shift
  for arg in "$@"; do
    case "$arg" in
      "$flag"|"$flag"=*)
        return 0
        ;;
    esac
  done
  return 1
}

prompt_with_default() {
  label=$1
  default_value=$2
  if [ -t 0 ]; then
    printf "%s [%s]: " "$label" "$default_value" >&2
    read -r value
    if [ -z "${value:-}" ]; then
      printf "%s" "$default_value"
    else
      printf "%s" "$value"
    fi
    return 0
  fi
  printf "%s" "$default_value"
}

normalize_network_value() {
  case $(printf "%s" "$1" | tr '[:upper:]' '[:lower:]') in
    1|mainnet|bitcoin)
      printf "mainnet"
      ;;
    *)
      return 1
      ;;
  esac
}

prompt_network_choice() {
  default_value=$1
  if ! [ -t 0 ]; then
    printf "%s" "$default_value"
    return 0
  fi

  default_hint="1"

  while true; do
    printf "BTC network:\n" >&2
    printf "  1) mainnet\n" >&2
    printf "Choose network [%s]: " "$default_hint" >&2
    read -r choice
    if [ -z "${choice:-}" ]; then
      choice=$default_hint
    fi
    if network=$(normalize_network_value "$choice"); then
      printf "%s" "$network"
      return 0
    fi
    printf "Invalid choice. Enter 1, mainnet, or bitcoin.\n" >&2
  done
}

DEFAULT_USER_ID=${OPENCLAW_BTC_USER_ID:-${USER:-openclaw-user}-local}
if DEFAULT_NETWORK=$(normalize_network_value "${OPENCLAW_BTC_NETWORK:-mainnet}" 2>/dev/null); then
  :
else
  DEFAULT_NETWORK=mainnet
fi
DEFAULT_SERVICE_URL=${OPENCLAW_BTC_SERVICE_URL:-http://127.0.0.1:8080}

if ! has_flag --user-id "$@"; then
  USER_ID=$(prompt_with_default "OpenClaw user id" "$DEFAULT_USER_ID")
  set -- "$@" --user-id "$USER_ID"
fi

if ! has_flag --network "$@"; then
  NETWORK=$(prompt_network_choice "$DEFAULT_NETWORK")
  set -- "$@" --network "$NETWORK"
fi

if ! has_flag --service-url "$@"; then
  set -- "$@" --service-url "$DEFAULT_SERVICE_URL"
fi

if ! has_flag --config-path "$@" && [ -n "${OPENCLAW_BTC_CONFIG_PATH:-}" ]; then
  set -- "$@" --config-path "$OPENCLAW_BTC_CONFIG_PATH"
fi

if ! has_flag --wdk-wallet-root "$@" && [ -n "${OPENCLAW_BTC_WDK_WALLET_ROOT:-}" ]; then
  set -- "$@" --wdk-wallet-root "$OPENCLAW_BTC_WDK_WALLET_ROOT"
fi

if ! has_flag --python-bin "$@"; then
  set -- "$@" --python-bin "$PYTHON_BIN"
fi

if ! has_flag --package-root "$@"; then
  set -- "$@" --package-root "$PACKAGE_ROOT"
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/bootstrap_openclaw_btc.py" "$@"
