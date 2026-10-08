#!/usr/bin/env bash
# Start the local server (http://127.0.0.1:8765)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
exec "$PY" -m uvicorn server.main:app --host 127.0.0.1 --port 8765 --reload
