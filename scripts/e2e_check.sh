#!/usr/bin/env bash
# macOS/Linux convenience wrapper: finds Python 3.11+ and runs the cross-platform checker.
# Windows: run `py -3.12 scripts\e2e_check.py` (or `python scripts\e2e_check.py`) instead.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/_python.sh
exec "$PY" scripts/e2e_check.py "$@"
