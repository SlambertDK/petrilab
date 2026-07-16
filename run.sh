#!/usr/bin/env bash
# Start the PetriLab dashboard on http://localhost:8770
# Uses the local virtualenv if present, otherwise the system Python.
set -euo pipefail
cd "$(dirname "$0")"

PY="python3"
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
fi

exec "$PY" -m uvicorn server:app --host 0.0.0.0 --port 8770
