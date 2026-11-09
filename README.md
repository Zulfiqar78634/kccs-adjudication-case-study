# KCCS Sentinel: case-study submission

**Candidate:** Zulfiqar · **Brief:** *The Adjudication Problem* (Kestrel Cold Chain Solutions, 18 Sep 2026)

**In one sentence:** when a temperature alert fires, this system gathers the evidence a QA reviewer needs: the right product, the SOP in force on that date, the right stability study and the regulatory deadline. It uses only that customer's data, records exactly what it used, and **says "not enough evidence" instead of guessing**. It never makes the product decision; a named human does.

---

## How to review this in 6 steps

You can stop after any step. Steps 1–4 need no installation.

### Step 1: Read the summary (5–10 minutes)

Open **[FINAL_REPORT.md](FINAL_REPORT.md)**. It covers what I concluded, what I built, what it found in the data, and what is not built.

### Step 2: Find each part you asked for

| You asked for | Where it is |
|---|---|
| **1. Where you land**: requirements, what I won't build, rollout and first customer, gaps and contradictions, board targets I challenge | [docs/01_where_we_land.md](docs/01_where_we_land.md) |
| **2. The design**: architecture, components, data model and "as at a date" queries, case lifecycle, outages and the regulatory clock, versioning and deployment, diagrams | [docs/02_architecture_hld.md](docs/02_architecture_hld.md) (overview) and [docs/03_detailed_design_lld.md](docs/03_detailed_design_lld.md) (detail) |
| **3. Working prototype**: the most critical component, run on the real workbook, and how it is validated | Code in [src/kccs_evidence/](src/kccs_evidence/), tests in [tests/](tests/), validation in [docs/05_validation_and_operations.md](docs/05_validation_and_operations.md) |
| **4. Working log**: discarded ideas, wrong assumptions and how they were caught, changes of direction | [docs/06_working_log.md](docs/06_working_log.md) |

Also useful: what the data revealed, in [docs/04_data_findings_and_assumptions.md](docs/04_data_findings_and_assumptions.md), and a 20-minute walkthrough with hard questions, in [docs/07_review_walkthrough.md](docs/07_review_walkthrough.md).

### Step 3: See the proof that it works, without running anything

Open **[evidence/E2E_EVIDENCE.md](evidence/E2E_EVIDENCE.md)**. It records a full end-to-end run on the supplied workbook: **25 of 25 checks passed and all 76 automated tests passed**, with every log kept in [evidence/logs/](evidence/logs/).

### Step 4: Look at one real example: the brief's own case, EXC-107133

The brief describes Priya spending 1 hour 50 minutes on this insulin alert. Open [evidence/results/EXC-107133_assessment_excerpt.json](evidence/results/EXC-107133_assessment_excerpt.json) to see what the system finds from the data alone:

| Question the reviewer had to answer | What the system found |
|---|---|
| Which product is this? | GTIN `08901234500035` matched to Kaveri's own product record (the same GTIN also exists for 3 other customers, which it does not look at) |
| Which SOP revision was in force? | **Two revisions (Rev 02 and Rev 03) of SOP-KAV-9392 were both in force that day.** It flags the conflict instead of picking one |
| Which stability study applies? | The product record points to **STB-3584, a study for the vial, not the pen**, and it is partly unreadable, so it is rejected. The correct pen study **STB-2738** is found and offered for confirmation |
| Is the regulator deadline at risk? | If notifiable, due **12 Aug 2026 06:31 UTC**, counted from when the alert arrived, not from when the excursion started |
| Can it decide? | **No.** It lists the human actions needed, ending with "Sign or decline the disposition: Site QA" |

### Step 5: Run it yourself (about 2 minutes)

You need Python 3.11 or newer, git, and the workbook `KCCS_Sentinel_Reference_Data_Pack.xlsx`. No API keys and no internet are needed after install.

**macOS / Linux**

```bash
git clone https://github.com/Zulfiqar78634/kccs-adjudication-case-study.git
cd kccs-adjudication-case-study
mkdir -p data && cp /path/to/KCCS_Sentinel_Reference_Data_Pack.xlsx data/
python3 scripts/e2e_check.py
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/Zulfiqar78634/kccs-adjudication-case-study.git
cd kccs-adjudication-case-study
mkdir data; copy C:\path\to\KCCS_Sentinel_Reference_Data_Pack.xlsx data\
py -3.12 scripts\e2e_check.py        # or: python scripts\e2e_check.py
```

It creates its own Python environment, installs everything, runs all the checks, prints PASS or FAIL for each one, and writes the evidence to `evidence/`. **Expect the last line to start with `checks: 25, failed: 0`.**

- **Python too old?** The script says so and stops. On macOS the bundled `python3` is often 3.9: use `python3.12` (or `brew install python@3.12`). On Windows, install from python.org or the Microsoft Store, then use `py -3.12`.
- **No workbook to hand?** `scripts/e2e_check.py --synthetic` runs the same install and command-line checks on an invented workbook with the same layout.
- **Tested on:** Windows, macOS and Linux with Python 3.11, 3.12 and 3.13, on every commit ([cross-platform workflow](.github/workflows/cross-platform.yml)). Those machines use the synthetic workbook, because the confidential one is never uploaded. The full run on the real workbook is recorded in [evidence/](evidence/E2E_EVIDENCE.md).

For each command on its own, with the output to expect at every step, see **[docs/STEP_BY_STEP.md](docs/STEP_BY_STEP.md)**.

### Step 6: Read the code (optional)

Each file does one job:

| File | What it does, in plain words |
|---|---|
| [`sources.py`](src/kccs_evidence/sources.py) | Reads the workbook and keeps each row exactly as received, with its sheet and row number |
| [`store.py`](src/kccs_evidence/store.py) | Saves everything permanently. Corrections are added as new versions; nothing is ever overwritten or deleted |
| [`access.py`](src/kccs_evidence/access.py) | Makes sure each request can only see one customer's data, and logs every refusal |
| [`resolution.py`](src/kccs_evidence/resolution.py) | Works out which product, site and carrier an alert refers to, or says "ambiguous" or "unknown" |
| [`policy_sop.py`](src/kccs_evidence/policy_sop.py) | Finds the SOP revision in force at that site on that date, and flags overlaps |
| [`stability.py`](src/kccs_evidence/stability.py) | Checks that a stability study belongs to this customer, is for this product form, and is readable |
| [`signals.py`](src/kccs_evidence/signals.py) | Temperature arithmetic, including the faulty-firmware uncertainty ("up to 1.8 °C") |
| [`obligations.py`](src/kccs_evidence/obligations.py) | The regulatory notification clock, which runs separately and is never paused |
| [`assessment.py`](src/kccs_evidence/assessment.py) | Puts it all together into one assessment, or a refusal with reasons |
| [`package.py`](src/kccs_evidence/package.py) | Exports the evidence with fingerprints, so any later change is detected |
| [`evaluation.py`](src/kccs_evidence/evaluation.py) | Compares results with what humans did in the past. Kept separate so past outcomes never influence the assessment |
| [`cli.py`](src/kccs_evidence/cli.py) | The `kccs-evidence` command-line tool |

---

## Four ideas behind the design

1. **Refuse rather than guess.** If evidence is missing or conflicting, the answer is "not enough evidence, here is what a human must do". On this workbook every alert ends that way. That is correct, because the workbook has no temperature series, no SOP text and no batch history, which are exactly what a safe decision needs. With only those gaps closed, 8 of the 420 alerts would be ready for a reviewer.
2. **One customer at a time.** Searches are limited to the requesting customer's data from the start, rather than filtered afterwards. This prevents incidents like the Meridian/Pinnacle near-miss in the brief.
3. **"What did we know then?" is a separate question from "what do we know now?"** Every result records the date it reflects and the date of the knowledge it used. Re-running the past gives the same answer, even after later corrections.
4. **Two clocks.** The product decision can wait for evidence; the regulator's deadline cannot. Notification is tracked separately from the moment the alert arrives.

---

## Reference

### What the 78 tests prove

| Claim | Tests |
|---|---|
| Customers are isolated: cross-customer reads and exports are refused and logged; the same GTIN resolves separately per customer | `tests/test_tenant_isolation.py` |
| Dates are handled correctly: SOP revision at the site's local date, boundaries, overlaps reported as conflicts | `tests/test_temporal.py` |
| No future knowledge leaks into the past: a fact learned after the alert is invisible at that point in time | `tests/test_temporal.py` |
| Results are reproducible: same evidence, same ID; loading twice adds nothing | `tests/test_assessment.py`, `tests/test_ingestion_and_store.py` |
| Corrections never edit history: a new assessment supersedes the old, and the original stays identical | `tests/test_assessment.py`, `tests/test_ingestion_and_store.py` |
| Evidence packages can't be silently altered | `tests/test_package.py` |
| It never guesses and never makes a disposition (checked on all 420 alerts); past outcomes are not used as inputs | `tests/test_assessment.py` |
| Stability checks catch wrong product forms, unreadable studies and misleading folder paths | `tests/test_stability_and_signals.py` |
| The notification clock starts at alert receipt, is not paused by waiting, refuses to guess "next business day", and keeps every alert during a 1,912-alert storm | `tests/test_obligations.py` |
| It behaves identically on Windows, macOS and Linux: the full command-line flow on a synthetic workbook, byte-exact evidence packages, UTF-8 console output, and IDs unchanged by Windows line endings | `tests/test_cli_portable.py` |

### What is built, simulated, or design only

| Built and tested | Simulated or stubbed (clearly labelled) | Design only (documented, not built) |
|---|---|---|
| Workbook loading with row references; permanent versioned store; customer access control; product, site and carrier matching; SOP selection by date and site; stability checks; temperature and firmware arithmetic; "as known then" replay; reproducible assessments; corrections; evidence packages; notification clock; data-quality report; evaluation against past cases | Temperature-series archive, SOP document text, batch history, regulator gateway; one labelled simulated correction in the demo; small synthetic test cases for situations the workbook lacks | Reviewer workflow and dual signatures; regional deployment (EU, India, Americas); connectors to the nine source systems; optional language-model drafting; monitoring |

### Limitations

- Every alert abstains on this workbook, for the reasons above.
- Some interpretations (site-scope mapping, product-form keywords, notification rules, firmware bulletin) are my reading of the data and need QA or Regulatory Affairs approval. They are kept in [src/kccs_evidence/config/](src/kccs_evidence/config/).
- The 420 alerts are a hand-picked evidence pack, not a random sample. Counts across them are not accuracy or automation-rate estimates.
- Recovery targets, alert thresholds and costs in the design documents are proposals, not measurements.

### Troubleshooting

| Problem | Fix |
|---|---|
| `Workbook not found` | Put the file in `data/` with exactly this name: `KCCS_Sentinel_Reference_Data_Pack.xlsx` |
| Tests show `45 skipped` | Same cause: the workbook is not in `data/` |
| `externally-managed-environment` | Use the scripts, which create their own Python environment, or activate a virtual environment first |
| `kccs-evidence: command not found` | Activate the environment (`. .venv/bin/activate`) or use `python -m kccs_evidence.cli` |

### Repository map

```
README.md                     this page: start here
FINAL_REPORT.md               summary of the whole submission
docs/01 … 07                  the written deliverables (see Step 2)
docs/STEP_BY_STEP.md          run every command, with the expected output
evidence/                     recorded end-to-end test run (25/25 passed) and its logs
src/kccs_evidence/            the prototype (see Step 6)
tests/                        78 automated tests (45 need the real workbook; 33 run anywhere)
scripts/e2e_check.py          run every check and record the evidence (Windows, macOS, Linux)
scripts/run_all.sh            macOS/Linux: install, test and run the demo
```

The confidential workbook is not in this repository. Results produced on your machine go to `artifacts/`, which is also not committed.
