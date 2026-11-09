#!/usr/bin/env bash
# One-command clean install + tests + demo. Usage: scripts/run_all.sh [path/to/workbook.xlsx]
set -euo pipefail
cd "$(dirname "$0")/.."
WB="${1:-data/KCCS_Sentinel_Reference_Data_Pack.xlsx}"
if [ ! -f "$WB" ]; then
  echo "Workbook not found at $WB. Copy KCCS_Sentinel_Reference_Data_Pack.xlsx into data/ (see README)." >&2
  exit 1
fi
. scripts/_python.sh
# Rebuild the environment if it was created with an unsupported Python.
if [ -d .venv ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  rm -rf .venv
fi
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[dev]"
mkdir -p artifacts
export KCCS_WORKBOOK="$WB"
.venv/bin/python -m pytest -v -o addopts="" -p no:cacheprovider | tee artifacts/test_output.txt
.venv/bin/python -m kccs_evidence.cli demo --workbook "$WB" --out-dir artifacts | tee artifacts/demo_console.txt
echo
echo "Done. Open artifacts/evaluation/summary.md, artifacts/data_quality/report.md, artifacts/cases/, artifacts/demo_run.json"
