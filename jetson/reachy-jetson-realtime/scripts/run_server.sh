#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
exec python -m jetson_realtime_probe.server
