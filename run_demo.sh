#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
. .venv/bin/activate
exec e2eproof demo --browser chromium
