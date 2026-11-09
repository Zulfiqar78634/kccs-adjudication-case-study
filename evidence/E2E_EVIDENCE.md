# End-to-end test evidence

**Result: 25 of 25 checks passed** on 9 November 2026 (04:36 UTC). The checks ran against the supplied workbook, in a fresh copy of the repository with a fresh Python environment.

The run was produced by `scripts/e2e_check.sh`. You can repeat it yourself:

```bash
cp /path/to/KCCS_Sentinel_Reference_Data_Pack.xlsx data/
scripts/e2e_check.sh
```

It rebuilds this whole `evidence/` folder and exits with code 0 only if every check passes.

## What was tested

| Item | Value |
|---|---|
| Code tested | commit `ef2884199f121bb9cc7859150f26a1f11e6096c9` (the submitted kernel plus this script) |
| Workbook | `KCCS_Sentinel_Reference_Data_Pack.xlsx`, 221,860 bytes, SHA-256 `9fe3fad7d0f77a5fbdaa0f8ce70336a911a8725d38d057b9d9d777c06ea57db3` |
| Environment | Python 3.12.3 on Linux; dependency versions in `pip_freeze.txt` |
| Duration | about 23 seconds, including the fresh install |

The workbook itself is **not** in this folder or the repository, because it is confidential. Only derived results are kept here.

## Results

| ID | Check | Expected | Observed | Result |
|---|---|---|---|---|
| E1 | Fresh install (`pip install -e .[dev]`) | exit 0 | exit 0 | PASS |
| E2 | Test suite exit code | 0 | 0 | PASS |
| E3 | Tests passed | 76 passed | 76 passed | PASS |
| E4 | Workbook inspection report written | exit 0 | exit 0 | PASS |
| E5 | Full demo exit code | 0 | 0 | PASS |
| E6 | Workbook rows ingested | 1,413 | 1,413 | PASS |
| E7 | Re-ingest adds no new records | 0 | 0 | PASS |
| E8 | Cross-tenant read denied in demo | denied | denied | PASS |
| E9 | Correction leaves the original assessment byte-identical | true | true | PASS |
| E10 | Replay "as known at alert" after a correction reproduces the original ID | true | true | PASS |
| E11 | Assessments stored (420 alerts × 2 knowledge views + 1 after correction) | 841 | 841 | PASS |
| E12 | All 6 demo evidence packages verify | true | true | PASS |
| E13 | EXC-107133 abstains and makes no disposition | `ABSTAIN_BLOCKING_EVIDENCE_GAPS`, `is_disposition=false` | same | PASS |
| E14 | EXC-107133 product resolved within T-KAVERI | `02_Product_Master!R57` | same | PASS |
| E15 | EXC-107133 SOP overlap detected | SOP-KAV-9392 Rev 02 + Rev 03, conflict | same | PASS |
| E16 | EXC-107133 wrong-presentation study rejected | STB-3584 not admissible | same | PASS |
| E17 | EXC-107133 correct pen study offered as a candidate | STB-2738 admissible | same | PASS |
| E18 | EXC-107133 notification deadline counted from alert receipt | 2026-08-12T06:31:00Z | same | PASS |
| E19 | Assessment ID reproducible across separate runs | `ASM-669e9e1d77c3ae0b6a6c75d9` | same | PASS |
| E20 | Later knowledge cutoff produces a different assessment | different ID | different ID | PASS |
| E21 | Command line: cross-tenant read refused | exit 3 | exit 3 | PASS |
| E22 | Command line: exported package verifies | exit 0 | exit 0 | PASS |
| E23 | Command line: another tenant cannot export the package | exit 3 | exit 3 | PASS |
| E24 | Command line: a tampered package is rejected | exit 2 | exit 2 | PASS |
| E25 | Command line: re-ingest adds nothing | `"new_records": 0` | same | PASS |

The same table, in machine-readable form, is in `results/checks.tsv`.

## Files in this folder

| File | What it is |
|---|---|
| `RESULT.txt` | One-line outcome: `checks: 25, failed: 0` |
| `environment.txt` | Date, commit, Python version, OS, workbook hash |
| `pip_freeze.txt` | Exact dependency versions installed |
| `logs/01_install.log` | Full install output |
| `logs/02_pytest.log` | Full test output: each of the 76 tests listed by name with PASSED |
| `logs/03_inspect.log` | Workbook inspection run |
| `logs/04_demo.log` | Full demo console output |
| `logs/05_cli.log` | Output of each command-line check (E19–E25) |
| `results/checks.tsv` | The results table above |
| `results/EXC-107133_assessment_excerpt.json` | Key fields of the brief's case: entities, SOP, stability, notification, required human actions, manifest |
| `results/evaluation_summary.md` | Results across all 420 alerts: blocking reasons, firmware replay, the 24 reviewer overrides, notification check |
| `results/data_quality_report.md` | Workbook inspection: sheets, missing values, joins, 27 overlapping SOP revision pairs, stability issues |
| `results/demo_run.json` | Machine-readable record of each demo claim |

## How to read these results

- The 420 alerts are a **stratified evidence pack**, not a random sample. Counts across them are not accuracy or automation-rate estimates.
- Every alert correctly abstains, because the pack has no temperature series, SOP content or batch history. See `FINAL_REPORT.md` §2.
- Not covered by this run: anything the documents mark "design only" (case workflow, regional cells, monitoring), load testing, and failover.
