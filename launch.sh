#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
exec "$here/.venv/bin/python" "$here/start.py" "$@"
