#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "$0")" && pwd)"
python="${RALF_PYTHON:-python3}"
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
"$python" -m venv "$here/.venv"
"$here/.venv/bin/python" -m pip install --upgrade pip
"$here/.venv/bin/python" -m pip install "torch>=2.2,<3" --index-url https://download.pytorch.org/whl/cpu
"$here/.venv/bin/python" -m pip install -r "$here/requirements.txt"
"$here/.venv/bin/python" "$here/configure.py" "$@"
"$here/.venv/bin/python" "$here/doctor.py"
echo 'Ready. Start the workbench with: bash launch.sh'
