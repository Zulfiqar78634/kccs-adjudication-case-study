#!/usr/bin/env bash
# End-to-end check: fresh virtualenv, install, tests, demo, CLI checks.
# Writes all evidence to evidence/ (logs, results, summary) without copying the workbook.
# Usage: scripts/e2e_check.sh [path/to/workbook.xlsx]
set -uo pipefail
cd "$(dirname "$0")/.."
WB="${1:-data/KCCS_Sentinel_Reference_Data_Pack.xlsx}"
EV=evidence
LOG="$EV/logs"
if [ ! -f "$WB" ]; then
  echo "Workbook not found at $WB. Copy KCCS_Sentinel_Reference_Data_Pack.xlsx into data/ (see README)." >&2
  exit 1
fi
rm -rf "$EV/logs" "$EV/results" "$EV"/*.txt artifacts/e2e && mkdir -p "$LOG" "$EV/results" artifacts/e2e   # keeps E2E_EVIDENCE.md
RESULTS="$EV/results/checks.tsv"
printf 'id\tcheck\texpected\tobserved\tresult\n' > "$RESULTS"
FAIL=0
record() {  # id, check, expected, observed
  local res=PASS; [ "$3" = "$4" ] || { res=FAIL; FAIL=$((FAIL+1)); }
  printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$res" >> "$RESULTS"
  printf '%-4s %-5s %s\n' "$1" "$res" "$2"
}

PY="${PYTHON:-python3}"
{ echo "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"; echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo n/a)"
  echo "python: $($PY --version 2>&1)"; echo "os: $(uname -sr)"
  echo "workbook_sha256: $(sha256sum "$WB" | cut -d' ' -f1)"; echo "workbook_bytes: $(wc -c < "$WB")"; } > "$EV/environment.txt"

# E1 fresh install
rm -rf .venv-e2e && "$PY" -m venv .venv-e2e && . .venv-e2e/bin/activate
pip install -q --upgrade pip > "$LOG/01_install.log" 2>&1
pip install -e ".[dev]" >> "$LOG/01_install.log" 2>&1; rc=$?
pip freeze --exclude-editable > "$EV/pip_freeze.txt"
record E1 "Fresh install (pip install -e .[dev])" 0 "$rc"

# E2 test suite
export KCCS_WORKBOOK="$WB"
python -m pytest -v -o addopts="" -p no:cacheprovider > "$LOG/02_pytest.log" 2>&1; rc=$?
record E2 "Test suite exit code" 0 "$rc"
record E3 "Tests passed" "76 passed" "$(grep -oE '[0-9]+ passed' "$LOG/02_pytest.log" | tail -1)"

# E4 data-quality inspection
kccs-evidence inspect --workbook "$WB" --out-dir artifacts/e2e/data_quality > "$LOG/03_inspect.log" 2>&1; rc=$?
record E4 "Workbook inspection report written" 0 "$rc"

# E5-E10 demo
kccs-evidence demo --workbook "$WB" --out-dir artifacts/e2e --now 2026-11-08T12:00:00Z > "$LOG/04_demo.log" 2>&1; rc=$?
record E5 "Full demo exit code" 0 "$rc"
D=artifacts/e2e/demo_run.json
j() { python -c "import json,sys;d=json.load(open('$D'));print($1)"; }
record E6 "Workbook rows ingested" 1413 "$(j "d['ingest']['new_records']")"
record E7 "Re-ingest is idempotent (new records)" 0 "$(j "d['ingest_again_idempotent']['new_records']")"
record E8 "Cross-tenant read denied in demo" True "$(j "d['isolation_demo'].startswith('DENIED')")"
record E9 "Correction leaves original assessment byte-identical" True "$(j "d['correction_demo']['original_unchanged']")"
record E10 "At-alert replay after correction reproduces original ID" True "$(j "d['correction_demo']['replay_at_alert_after_correction_same_id']")"
record E11 "Assessments stored" 841 "$(grep -oE 'assessments stored: [0-9]+' "$LOG/04_demo.log" | grep -oE '[0-9]+$')"
record E12 "All demo evidence packages verify" True "$(j "all(p['ok'] for p in d['packages_verified']) and len(d['packages_verified'])==6")"

# E13 brief case EXC-107133
C=artifacts/e2e/cases/EXC-107133_at_alert.json
c() { python -c "import json;a=json.load(open('$C'));print($1)"; }
record E13 "EXC-107133 abstains (no disposition)" "ABSTAIN_BLOCKING_EVIDENCE_GAPS False" "$(c "a['disposition_evidence_status'], a['is_disposition']")"
record E14 "EXC-107133 product resolved within T-KAVERI" "02_Product_Master!R57" "$(c "a['entities']['product']['resolved_id']")"
record E15 "EXC-107133 SOP overlap detected" "SOP-KAV-9392 CONFLICT_OVERLAPPING_REVISIONS ['Rev 02', 'Rev 03']" "$(c "a['evidence']['sop_origin'][0]['doc_id'], a['evidence']['sop_origin'][0]['status'], a['evidence']['sop_origin'][0]['in_force']")"
record E16 "EXC-107133 wrong-presentation study rejected" "STB-3584 False" "$(c "a['evidence']['stability']['referenced']['study_ref'], a['evidence']['stability']['referenced']['admissible']")"
record E17 "EXC-107133 pen study offered as candidate" True "$(c "any(x['study_ref']=='STB-2738' and x['admissible'] for x in a['evidence']['stability']['unreferenced_candidates'])")"
record E18 "EXC-107133 notification deadline from alert receipt" 2026-08-12T06:31:00Z "$(c "a['notification_track']['due_at_utc']")"

# E19-E25 CLI operations
DB=artifacts/e2e/cli.sqlite; rm -f "$DB"
kccs-evidence ingest --workbook "$WB" --db "$DB" > "$LOG/05_cli.log" 2>&1
kccs-evidence assess --db "$DB" --tenant T-KAVERI --event EXC-107133 --knowledge-cutoff alert --now 2026-11-08T12:00:00Z --out artifacts/e2e/then.json >> "$LOG/05_cli.log" 2>&1
ID1=$(python -c "import json;print(json.load(open('artifacts/e2e/then.json'))['assessment_id'])")
record E19 "Assessment ID reproducible across runs" "$(j "d['correction_demo']['original_assessment']")" "$ID1"
kccs-evidence assess --db "$DB" --tenant T-KAVERI --event EXC-107133 --knowledge-cutoff 2026-09-14T23:59:00Z --now 2026-11-08T12:00:00Z --out artifacts/e2e/later.json >> "$LOG/05_cli.log" 2>&1
record E20 "Later knowledge cutoff gives a different assessment" True "$(python -c "import json;print(json.load(open('artifacts/e2e/later.json'))['assessment_id']!='$ID1')")"
kccs-evidence assess --db "$DB" --tenant T-MERIDIAN --tenant-scope T-PINNACLE --event EXC-110630 >> "$LOG/05_cli.log" 2>&1; rc=$?
record E21 "CLI cross-tenant read refused (exit code)" 3 "$rc"
kccs-evidence export-package --db "$DB" --assessment-id "$ID1" --tenant-scope T-KAVERI --out-dir artifacts/e2e/cli_packages >> "$LOG/05_cli.log" 2>&1
kccs-evidence verify-package "artifacts/e2e/cli_packages/$ID1" >> "$LOG/05_cli.log" 2>&1; rc=$?
record E22 "Exported package verifies" 0 "$rc"
kccs-evidence export-package --db "$DB" --assessment-id "$ID1" --tenant-scope T-PINNACLE --out-dir artifacts/e2e/other >> "$LOG/05_cli.log" 2>&1; rc=$?
record E23 "Other tenant cannot export the package (exit code)" 3 "$rc"
python - "artifacts/e2e/cli_packages/$ID1/assessment.json" <<'PYEOF'
import sys; p = sys.argv[1]; t = open(p, encoding="utf-8").read()
open(p, "w", encoding="utf-8").write(t.replace("ABSTAIN_BLOCKING_EVIDENCE_GAPS", "READY_FOR_QA_REVIEW"))
PYEOF
kccs-evidence verify-package "artifacts/e2e/cli_packages/$ID1" >> "$LOG/05_cli.log" 2>&1; rc=$?
record E24 "Tampered package rejected (exit code)" 2 "$rc"
kccs-evidence ingest --workbook "$WB" --db "$DB" >> "$LOG/05_cli.log" 2>&1
record E25 "CLI re-ingest adds nothing" '"new_records": 0' "$(tail -1 "$LOG/05_cli.log" | grep -oE '"new_records": [0-9]+')"
deactivate

# Copy result files that contain derived summaries only (no raw workbook rows, no database).
cp artifacts/e2e/evaluation/summary.md "$EV/results/evaluation_summary.md"
cp artifacts/e2e/data_quality/report.md "$EV/results/data_quality_report.md"
cp "$D" "$EV/results/demo_run.json"
python - "$C" "$EV/results/EXC-107133_assessment_excerpt.json" <<'PYEOF'
import json, sys
a = json.load(open(sys.argv[1]))
keep = {k: a[k] for k in ("assessment_id", "disposition_evidence_status", "is_disposition", "blocking_reasons",
                          "time_semantics", "required_human_actions", "notification_track", "disposition_authority")}
keep["entities"] = {k: {f: v[f] for f in ("input_value", "status", "resolved_id", "basis")} for k, v in a["entities"].items()}
keep["sop_origin"] = [{f: s.get(f) for f in ("doc_id", "status", "in_force", "dates_evaluated", "date_basis")} for s in a["evidence"]["sop_origin"]]
st = a["evidence"]["stability"]
keep["stability"] = {"status": st["status"],
                     "referenced": {f: st["referenced"][f] for f in ("study_ref", "admissible", "rejection_reasons")},
                     "candidates": [{f: c[f] for f in ("study_ref", "admissible", "rejection_reasons")} for c in st["unreferenced_candidates"]]}
keep["reviewer_aid"] = a["reviewer_aid"]["items"]
keep["manifest"] = {k: a["manifest"][k] for k in ("kernel_version", "ruleset_version", "code_sha256", "config", "model", "stubs")}
json.dump(keep, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)
PYEOF
TOTAL=$(($(wc -l < "$RESULTS") - 1))
echo "checks: $TOTAL, failed: $FAIL" | tee "$EV/RESULT.txt"
rm -rf .venv-e2e
[ "$FAIL" -eq 0 ]
