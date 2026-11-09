# Step-by-step: run and check the submission

This guide takes you from an empty folder to every result, and shows the output to expect at each step. Commands are shown for **macOS/Linux (bash)**; where Windows PowerShell differs, the PowerShell version follows. Every bash command below was run as written on Linux with Python 3.12 and the supplied workbook; the PowerShell commands are run on Windows by the [cross-platform workflow](../.github/workflows/cross-platform.yml) using a synthetic workbook. Total time is about 2 minutes.

You need:
- **Python 3.11 or newer** (`python3 --version`; on Windows `py -3.12 --version` or `python --version`);
- **git**;
- the supplied workbook, **`KCCS_Sentinel_Reference_Data_Pack.xlsx`**.

No API keys, accounts or internet access are needed after installation.

---

## Step 1: Get the code

```bash
git clone https://github.com/Zulfiqar78634/kccs-adjudication-case-study.git
cd kccs-adjudication-case-study
```

**Expect:** a folder containing `README.md`, `FINAL_REPORT.md`, `docs/`, `src/`, `tests/` and `scripts/`.

## Step 2: Add the workbook

The workbook is confidential, so it is not in the repository. Copy it into the `data/` folder:

```bash
mkdir -p data
cp /path/to/KCCS_Sentinel_Reference_Data_Pack.xlsx data/
```

```powershell
mkdir data
copy C:\path\to\KCCS_Sentinel_Reference_Data_Pack.xlsx data\
```

**Expect:** `ls data/` shows `KCCS_Sentinel_Reference_Data_Pack.xlsx`.

## Step 3: Install

```bash
python3 -m venv .venv            # if `python3 --version` is older than 3.11 (common on macOS), use python3.12 or python3.13 here
. .venv/bin/activate
pip install -e ".[dev]"
```

```powershell
py -3.12 -m venv .venv           # or: python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled"), run `Set-ExecutionPolicy -Scope Process Bypass` in the same window first; it lasts only for that window.

**Expect:** the install ends with `Successfully installed … kccs-evidence-kernel-0.1.0 …`. The command `kccs-evidence --help` lists the subcommands `ingest`, `inspect`, `assess`, `export-package`, `verify-package`, `correct` and `demo`.

## Step 4: Run the tests

```bash
python -m pytest -v
```

**Expect:** the last line reads **`78 passed`**. If it says `45 skipped`, the workbook is not in `data/` (go back to Step 2).

## Step 5: Run the full demo on the workbook

```bash
kccs-evidence demo --workbook data/KCCS_Sentinel_Reference_Data_Pack.xlsx --out-dir artifacts
```

**Expect** (about 10 seconds), among the printed output:

```
"new_records": 1413                      ← every workbook row loaded once
"unchanged": 1413                        ← loading again adds nothing (safe to repeat)
"isolation_demo": "DENIED as expected: pinnacle-reviewer is not authorised for T-MERIDIAN"
"original_unchanged": true               ← a correction never edits the original assessment
"replay_at_alert_after_correction_same_id": true   ← replaying the past reproduces the same result
assessments stored: 841; outputs in artifacts
```

*Shortcut (macOS/Linux):* `scripts/run_all.sh` performs Steps 3–5 in one go and saves the test output to `artifacts/test_output.txt`. To run every check in this guide automatically and record the evidence, use `python scripts/e2e_check.py` (any OS) instead. It writes a pass/fail table and full logs to `evidence/`; the recorded run is in [`evidence/E2E_EVIDENCE.md`](../evidence/E2E_EVIDENCE.md).

## Step 6: Look at the brief's own case (EXC-107133)

Open **`artifacts/cases/EXC-107133_at_alert.json`**. Check these fields:

| Field | What you should see |
|---|---|
| `disposition_evidence_status` | `ABSTAIN_BLOCKING_EVIDENCE_GAPS`: the kernel refuses to conclude, and says why |
| `is_disposition` | `false`: it never makes the product decision |
| `entities.product` | GTIN `08901234500035` resolved within T-KAVERI to `02_Product_Master!R57` |
| `evidence.sop_origin[0]` | `SOP-KAV-9392`, status `CONFLICT_OVERLAPPING_REVISIONS`, in force: `Rev 02`, `Rev 03` |
| `evidence.stability.referenced` | `STB-3584` rejected: wrong presentation (vial, not pen), partially readable, accelerated study |
| `evidence.stability.unreferenced_candidates` | `STB-2738` (pen, "one excursion up to 6 h below 15 °C") admissible but not referenced |
| `notification_track.due_at_utc` | `2026-08-12T06:31:00Z`: counted from the alert (06:31), not the excursion start (06:14) |
| `required_human_actions` | the exact actions a reviewer must take, ending with "Sign or decline the disposition: Site QA" |
| `manifest` | code fingerprint, config hashes and the source versions used, for replay |

## Step 7: Ask the same question "as known then" and "as known later"

```bash
kccs-evidence ingest --workbook data/KCCS_Sentinel_Reference_Data_Pack.xlsx --db artifacts/my.sqlite
kccs-evidence assess --db artifacts/my.sqlite --tenant T-KAVERI --event EXC-107133 \
    --knowledge-cutoff alert --now 2026-11-08T12:00:00Z --out artifacts/then.json
kccs-evidence assess --db artifacts/my.sqlite --tenant T-KAVERI --event EXC-107133 \
    --knowledge-cutoff 2026-09-14T23:59:00Z --now 2026-11-08T12:00:00Z --out artifacts/later.json
```

In PowerShell, put each command on one line (or end lines with a backtick instead of `\`):

```powershell
kccs-evidence ingest --workbook data/KCCS_Sentinel_Reference_Data_Pack.xlsx --db artifacts/my.sqlite
kccs-evidence assess --db artifacts/my.sqlite --tenant T-KAVERI --event EXC-107133 --knowledge-cutoff alert --now 2026-11-08T12:00:00Z --out artifacts/then.json
kccs-evidence assess --db artifacts/my.sqlite --tenant T-KAVERI --event EXC-107133 --knowledge-cutoff 2026-09-14T23:59:00Z --now 2026-11-08T12:00:00Z --out artifacts/later.json
```

**Expect:**
```
ASM-b920c8d03004c712c883fb4a status=ABSTAIN_BLOCKING_EVIDENCE_GAPS stored=new
ASM-e301f0da23e6da659f419dd6 status=ABSTAIN_BLOCKING_EVIDENCE_GAPS stored=new
```

The first ID is identical on every machine, Python version and run. The ID is a fingerprint of the evidence, the knowledge cutoff and the exact code and rule versions, so the same inputs always give the same ID. Any change to the code or rules gives a different ID by design.

## Step 8: Check customer separation

```bash
kccs-evidence assess --db artifacts/my.sqlite --tenant T-MERIDIAN --tenant-scope T-PINNACLE --event EXC-110630
echo "exit code: $?"
```

```powershell
kccs-evidence assess --db artifacts/my.sqlite --tenant T-MERIDIAN --tenant-scope T-PINNACLE --event EXC-110630
echo "exit code: $LASTEXITCODE"
```

**Expect:** `ACCESS DENIED: cli-reviewer is not authorised for T-MERIDIAN` and `exit code: 3`. A Pinnacle user cannot read Meridian data, and the attempt is recorded in the audit log.

## Step 9: Export an evidence package and prove it cannot be altered

```bash
kccs-evidence export-package --db artifacts/my.sqlite --assessment-id ASM-b920c8d03004c712c883fb4a \
    --tenant-scope T-KAVERI --out-dir artifacts/my_packages
kccs-evidence verify-package artifacts/my_packages/ASM-b920c8d03004c712c883fb4a
```

In PowerShell, put the first command on one line (drop the `\`). **Expect:** `"ok": true`. Now change the package and verify again:

```bash
sed -i 's/ABSTAIN_BLOCKING_EVIDENCE_GAPS/READY_FOR_QA_REVIEW/' artifacts/my_packages/ASM-b920c8d03004c712c883fb4a/assessment.json
kccs-evidence verify-package artifacts/my_packages/ASM-b920c8d03004c712c883fb4a
```

```powershell
$f = "artifacts\my_packages\ASM-b920c8d03004c712c883fb4a\assessment.json"
[IO.File]::WriteAllText($f, [IO.File]::ReadAllText($f).Replace("ABSTAIN_BLOCKING_EVIDENCE_GAPS", "READY_FOR_QA_REVIEW"))
kccs-evidence verify-package artifacts\my_packages\ASM-b920c8d03004c712c883fb4a
```

**Expect:** `"ok": false` and `"problems": ["hash mismatch assessment.json"]`, with exit code 2. (On macOS, use `sed -i ''`.)

## Step 10: Read the results across all 420 alerts

| File | What it shows |
|---|---|
| `artifacts/evaluation/summary.md` | Abstentions and blocking reasons per alert, the firmware-bulletin replay, whether the 24 written reviewer overrides would have been surfaced (including the misses), and the notification-deadline check |
| `artifacts/data_quality/report.md` | Workbook inspection: sheets, missing values, join problems, the 27 overlapping SOP revision pairs, stability-index issues |
| `artifacts/demo_run.json` | Machine-readable proof of each demo claim from Step 5 |

These figures come from a stratified evidence pack, not a random sample. They are **not** accuracy or automation-rate estimates.

## Step 11: Read the written deliverables

| Order | File | Deliverable |
|---|---|---|
| 1 | `FINAL_REPORT.md` | Overview |
| 2 | `docs/01_where_we_land.md` | Where I land: requirements, non-goals, rollout, contradictions, board targets |
| 3 | `docs/02_architecture_hld.md`, `docs/03_detailed_design_lld.md` | The design |
| 4 | `docs/04_data_findings_and_assumptions.md` | Data findings |
| 5 | `docs/05_validation_and_operations.md` | How correctness is checked today and monitored later |
| 6 | `docs/06_working_log.md` | Working log |
| 7 | `docs/07_review_walkthrough.md` | 20-minute walkthrough and hard questions |

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| `Workbook not found at data/…` | Put the file in `data/` with exactly this name: `KCCS_Sentinel_Reference_Data_Pack.xlsx` |
| `45 skipped` in Step 4 | Same cause: the workbook is missing from `data/` |
| `error: externally-managed-environment` | Activate the virtual environment first (Step 3) |
| `requires a different Python` or `Python 3.11 or newer is required` | Your `python3` is too old. Install 3.11+ (macOS: `brew install python@3.12`) and recreate the environment with it (`rm -rf .venv && python3.12 -m venv .venv`) |
| `NOT FOUND: … not found for tenant …` | The database has not been loaded yet (run `kccs-evidence ingest` first), or the event belongs to another customer |
| `kccs-evidence: command not found` | Activate the virtual environment, or use `python -m kccs_evidence.cli …` instead |
| PowerShell: "running scripts is disabled on this system" | `Set-ExecutionPolicy -Scope Process Bypass`, then activate again |
| Windows: `python` opens the Microsoft Store or is not found | Use the Python launcher, `py -3.12`, or install Python from python.org with "Add to PATH" ticked |
| `ZoneInfoNotFoundError` | Re-run `pip install -e ".[dev]"`, which installs `tzdata` |
| Step 7 prints a different ID | Check that the workbook is the unmodified original (its SHA-256 starts with `9fe3fad7d0f77a5f`) and that the code is the version on `main` |
