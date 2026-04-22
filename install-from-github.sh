#!/bin/sh
set -eu

OPENCLAW_INSTALL_REPO_DEFAULT=""
OPENCLAW_INSTALL_REPO="${OPENCLAW_INSTALL_REPO:-$OPENCLAW_INSTALL_REPO_DEFAULT}"
OPENCLAW_INSTALL_ROOT="${OPENCLAW_INSTALL_ROOT:-$HOME/.openclaw/agent-wallet-runtime}"
OPENCLAW_INSTALL_TARGET="${OPENCLAW_INSTALL_TARGET:-$OPENCLAW_INSTALL_ROOT/current}"
OPENCLAW_INSTALL_RELEASE_TAG="${OPENCLAW_INSTALL_RELEASE_TAG:-}"
OPENCLAW_INSTALL_RELEASE_METADATA_URL="${OPENCLAW_INSTALL_RELEASE_METADATA_URL:-}"
OPENCLAW_INSTALL_ASSET_NAME="${OPENCLAW_INSTALL_ASSET_NAME:-}"
OPENCLAW_INSTALL_ASSET_PREFIX="${OPENCLAW_INSTALL_ASSET_PREFIX:-openclaw-agent-wallet-bundle-}"
OPENCLAW_INSTALL_ASSET_URL="${OPENCLAW_INSTALL_ASSET_URL:-${OPENCLAW_INSTALL_ARCHIVE_URL:-}}"

require_cmd() {
  name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$name" >&2
    exit 1
  fi
}

require_path() {
  target="$1"
  label="$2"
  if [ ! -e "$target" ]; then
    printf 'Missing %s at %s\n' "$label" "$target" >&2
    exit 1
  fi
}

resolve_release_metadata_url() {
  if [ -n "$OPENCLAW_INSTALL_RELEASE_METADATA_URL" ]; then
    printf '%s\n' "$OPENCLAW_INSTALL_RELEASE_METADATA_URL"
    return
  fi
  if [ -z "$OPENCLAW_INSTALL_REPO" ]; then
    printf 'OPENCLAW_INSTALL_REPO is required unless OPENCLAW_INSTALL_ASSET_URL or OPENCLAW_INSTALL_RELEASE_METADATA_URL is set.\n' >&2
    exit 1
  fi
  if [ -n "$OPENCLAW_INSTALL_RELEASE_TAG" ]; then
    printf 'https://api.github.com/repos/%s/releases/tags/%s\n' "$OPENCLAW_INSTALL_REPO" "$OPENCLAW_INSTALL_RELEASE_TAG"
    return
  fi
  printf 'https://api.github.com/repos/%s/releases/latest\n' "$OPENCLAW_INSTALL_REPO"
}

resolve_asset_url() {
  metadata_path="$1"
  python3 - "$metadata_path" "$OPENCLAW_INSTALL_ASSET_NAME" "$OPENCLAW_INSTALL_ASSET_PREFIX" <<'PY'
import json
import sys
from pathlib import Path

metadata_path = Path(sys.argv[1])
asset_name = sys.argv[2].strip()
asset_prefix = sys.argv[3].strip()
payload = json.loads(metadata_path.read_text(encoding="utf-8"))
assets = payload.get("assets") or []

selected = None
if asset_name:
    for asset in assets:
        if str(asset.get("name") or "").strip() == asset_name:
            selected = asset
            break
else:
    for asset in assets:
        name = str(asset.get("name") or "").strip()
        if name.startswith(asset_prefix) and name.endswith(".tar.gz"):
            selected = asset
            break

if not isinstance(selected, dict):
    raise SystemExit("Could not find a matching release bundle asset.")

download_url = str(selected.get("browser_download_url") or "").strip()
if not download_url:
    raise SystemExit("Matching release asset is missing browser_download_url.")

print(download_url)
PY
}

require_cmd curl
require_cmd tar
require_cmd mktemp
require_cmd rm
require_cmd mkdir
require_cmd mv
require_cmd find
require_cmd sh
require_cmd python3

TEMP_DIR="$(mktemp -d)"
ARCHIVE_PATH="${TEMP_DIR}/bundle.tar.gz"
METADATA_PATH="${TEMP_DIR}/release.json"
EXTRACT_DIR="${TEMP_DIR}/extract"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

if [ -z "$OPENCLAW_INSTALL_ASSET_URL" ]; then
  RELEASE_METADATA_URL="$(resolve_release_metadata_url)"
  printf 'Resolving release metadata %s\n' "$RELEASE_METADATA_URL" >&2
  curl -fsSL "$RELEASE_METADATA_URL" -o "$METADATA_PATH"
  OPENCLAW_INSTALL_ASSET_URL="$(resolve_asset_url "$METADATA_PATH")"
fi

printf 'Downloading %s\n' "$OPENCLAW_INSTALL_ASSET_URL" >&2
curl -fsSL "$OPENCLAW_INSTALL_ASSET_URL" -o "$ARCHIVE_PATH"

mkdir -p "$EXTRACT_DIR"
tar -xzf "$ARCHIVE_PATH" -C "$EXTRACT_DIR"

SOURCE_ROOT="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ -z "$SOURCE_ROOT" ] || [ ! -d "$SOURCE_ROOT" ]; then
  printf 'Could not determine extracted bundle root.\n' >&2
  exit 1
fi

require_path "$SOURCE_ROOT/setup.sh" "local setup entrypoint"
require_path "$SOURCE_ROOT/agent-wallet" "agent-wallet package"
require_path "$SOURCE_ROOT/.openclaw/extensions/agent-wallet" "OpenClaw extension"
require_path "$SOURCE_ROOT/wdk-btc-wallet/package.json" "wdk-btc-wallet runtime"
require_path "$SOURCE_ROOT/wdk-evm-wallet/package.json" "wdk-evm-wallet runtime"

mkdir -p "$OPENCLAW_INSTALL_ROOT"
rm -rf "$OPENCLAW_INSTALL_TARGET"
mv "$SOURCE_ROOT" "$OPENCLAW_INSTALL_TARGET"

printf 'Installed runtime bundle into %s\n' "$OPENCLAW_INSTALL_TARGET" >&2
exec sh "$OPENCLAW_INSTALL_TARGET/setup.sh" "$@"
