#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${OPENCLAW_AGENT_WALLET_PYTHON:-python3}

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
    2|testnet)
      printf "testnet"
      ;;
    3|regtest)
      printf "regtest"
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

  case "$default_value" in
    mainnet|bitcoin) default_hint="1" ;;
    testnet) default_hint="2" ;;
    regtest) default_hint="3" ;;
    *) default_hint="1" ;;
  esac

  while true; do
    printf "BTC network:\n" >&2
    printf "  1) mainnet\n" >&2
    printf "  2) testnet\n" >&2
    printf "  3) regtest\n" >&2
    printf "Choose network [%s]: " "$default_hint" >&2
    read -r choice
    if [ -z "${choice:-}" ]; then
      choice=$default_hint
    fi
    if network=$(normalize_network_value "$choice"); then
      printf "%s" "$network"
      return 0
    fi
    printf "Invalid choice. Enter 1, 2, 3, mainnet, testnet, or regtest.\n" >&2
  done
}

DEFAULT_USER_ID=${OPENCLAW_BTC_USER_ID:-${USER:-openclaw-user}-local}
DEFAULT_NETWORK=${OPENCLAW_BTC_NETWORK:-mainnet}
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

exec "$PYTHON_BIN" "$SCRIPT_DIR/bootstrap_openclaw_btc.py" "$@"
