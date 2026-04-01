#!/bin/sh
set -eu

if [ ! -f .env ]; then
  cp .env.example .env
fi

npm install
