#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python bridge.py "$@"
fi

exec "${PYTHON:-python}" bridge.py "$@"
