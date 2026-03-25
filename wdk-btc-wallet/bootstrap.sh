#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
else
  echo "Using existing .env"
fi

if [ -z "${NPM_CONFIG_CACHE:-}" ]; then
  export NPM_CONFIG_CACHE=/tmp/npm-cache
fi

npm install

echo
echo "Bootstrap complete."
echo "Next step: npm start"
