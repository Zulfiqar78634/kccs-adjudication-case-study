# KCCS Sentinel: evidence-resolution and replay kernel (case-study submission)

Candidate: **Zulfiqar**. Start with **[FINAL_REPORT.md](FINAL_REPORT.md)**.

```
Workbook / source systems → ingestion (row refs, hashes) → append-only bitemporal store
  → tenant-scoped evidence resolution (entities, SOP in force, stability, telemetry, firmware)
  → assessment + evidence package + notification-obligation clock → accountable human QA reviewer
```

## Reviewer's 5-minute path

1. `scripts/run_all.sh` (with the workbook in `data/`): installs, runs the 76 tests, runs the demo.
2. Open `artifacts/cases/EXC-107133_at_alert.json`: the brief's own case, reconstructed from the data.
3. Open `artifacts/evaluation/summary.md`: results across all 420 alerts, including what the kernel misses.
4. Skim `tests/`: each claim below is backed by a named test.

## Why every alert abstains, and why that is correct

The kernel is designed to refuse unsupported conclusions. On this pack, refusing is the right answer, because the missing inputs are exactly the ones a defensible disposition needs:
- the temperature series (the pack has only aggregates);
- SOP acceptance-limit content (the pack is an index only);
- batch exposure history.

Even while abstaining, each assessment:
- resolves product, site and carrier for that tenant only;
- names the SOP revision in force, or the conflict;
- accepts or rejects each stability study with a reason;
- computes the notification deadline;
- lists the precise human actions needed;
- can be replayed bit-for-bit.

If only the series and SOP content were captured, 8 of the 420 alerts would have no remaining blocker (see `FINAL_REPORT.md` §2).

## Why this is not an LLM system

No model, API key or network is used. The hard part is evidence correctness, which is deterministic and must be reproducible for an inspector. A language model could later draft reviewer prose *from* a finished assessment under a versioned route, but the design treats "no LLM" as a fully supported route. This matters because some tenants prohibit external model APIs, and self-hosting would exceed the model budget (`docs/02` §9).

## What the tests prove (76 tests, `tests/`)

| Claim | Tests |
|---|---|
| Tenant isolation: cross-tenant reads, exports and lookups are denied and audited; the same GTIN resolves separately per tenant; untenanted product aliases are unreadable | `test_tenant_isolation.py` |
| Temporal correctness: SOP revision at a site-local date, half-open boundaries, overlaps reported as conflicts, unknown timezone near a boundary reported as ambiguous | `test_temporal.py` |
| No future knowledge in replay: a bulletin or alias learned after the alert is invisible at that cutoff | `test_temporal.py::test_replay_excludes_bulletin_learned_after_alert`, `::test_alias_confirmed_after_alert_is_not_used_in_replay` |
| Replay determinism and idempotency: the same evidence state gives the same assessment ID; re-ingest adds nothing | `test_assessment.py::test_repeated_execution_is_idempotent`, `test_ingestion_and_store.py::test_reingest_is_idempotent` |
| Correction semantics: a correction creates a superseding assessment; the original row is byte-identical; history tables reject UPDATE/DELETE | `test_assessment.py::test_correction_produces_new_assessment_and_old_is_immutable`, `test_ingestion_and_store.py` |
| Evidence-package integrity: packages are reproducible and tampering is detected | `test_package.py` |
| Abstention, not guessing: missing or ambiguous evidence never yields READY; no output is ever a disposition (checked on all 420 alerts); historical outcomes are not inputs | `test_assessment.py` |
| Stability checks: wrong presentation (EXC-110497, EXC-107133), unreadable studies, misleading file paths, firmware "up to 1.8 °C" treated as an interval | `test_stability_and_signals.py` |
| Notification clock: starts at alert receipt; waits don't move it; "next business day" refuses to guess; failed delivery ≠ success; a storm of 1,912 keeps every obligation | `test_obligations.py` |

## What this is

A working prototype of the part of Kestrel's adjudication problem that is hardest to get right: turning a real alert into a **tenant-scoped, temporally correct, reproducible evidence assessment** that **refuses unsupported conclusions**. Around it sit the written deliverables (position, HLD/LLD, data findings, validation and operations, working log). The prototype never makes a pharmaceutical disposition; humans sign those.

| Implemented [IMPL] | Simulated / stubbed [SIM] | Design only [DESIGN] |
|---|---|---|
| Workbook ingestion with row refs and hashes; append-only bitemporal SQLite store; tenant access control with audit; tenant-scoped product/site/carrier resolution; human-approved mappings; SOP revision selection (half-open site-local dates, overlap = conflict, site scope); stability admissibility (owner, presentation, readability, relevance, missingness); limit arithmetic with firmware uncertainty band; telemetry quality flags; knowledge-cutoff replay (reconstructed and strict); assessments with execution manifest and content-hash IDs; supersession on correction; evidence package export/verify; notification obligation clock and state machine (reference, in-memory); data-quality report; separate evaluation layer | Telemetry archive, document content store, batch exposure history, regulator gateway (all report NOT_AVAILABLE); one clearly labelled **simulated** source correction in the demo; synthetic fixtures for edge cases the workbook lacks | Case workflow with leases and dual signature; outbox and durable DB timers; regional cells; connectors to the nine systems; LLM drafting route; per-tenant search indexes; WORM storage; monitoring |

## Prerequisites

Python ≥ 3.11 (tested on 3.12.3). No API keys, no network after install, no paid services.

## Where to place the workbook

The workbook is confidential and **not committed**. Copy the supplied file to:

```
data/KCCS_Sentinel_Reference_Data_Pack.xlsx
```

(or set `KCCS_WORKBOOK=/path/to/file.xlsx`).

## Commands

```bash
# one command: venv, install, tests (output saved), full demo
scripts/run_all.sh

# or step by step
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -v                                              # 76 tests
kccs-evidence inspect --workbook data/KCCS_Sentinel_Reference_Data_Pack.xlsx --out-dir artifacts/data_quality
kccs-evidence demo    --workbook data/KCCS_Sentinel_Reference_Data_Pack.xlsx --out-dir artifacts

# individual operations
kccs-evidence ingest  --workbook data/KCCS_Sentinel_Reference_Data_Pack.xlsx --db artifacts/kernel.sqlite
kccs-evidence assess  --db artifacts/kernel.sqlite --tenant T-KAVERI --event EXC-107133 --knowledge-cutoff alert --out /tmp/a.json
kccs-evidence assess  --db artifacts/kernel.sqlite --tenant T-KAVERI --event EXC-107133 --knowledge-cutoff 2026-09-14T23:59:00Z
kccs-evidence assess  --db artifacts/kernel.sqlite --tenant T-MERIDIAN --tenant-scope T-PINNACLE --event EXC-110630   # → ACCESS DENIED (exit 3)
kccs-evidence export-package --db artifacts/kernel.sqlite --assessment-id ASM-… --tenant-scope T-KAVERI
kccs-evidence verify-package artifacts/packages/ASM-…
```

## Expected outputs (`artifacts/`, git-ignored because they contain real data)

| Path | Content |
|---|---|
| `data_quality/report.md`, `report.json` | Inspection and data-quality report |
| `evaluation/summary.md`, `summary.json` | Coverage, abstentions, conflicts, firmware replay, override-reason coverage, notification check (**not** accuracy estimates) |
| `cases/*.json` | Full assessments for selected real cases, at alert and as at extract, plus the post-correction assessment |
| `packages/ASM-*/` | Evidence packages with `MANIFEST.json` hashes |
| `demo_run.json` | Idempotency, isolation denial, correction immutability, package verification |
| `test_output.txt` | Test run output |
| `kernel.sqlite` | The append-only store |

## Troubleshooting

- `workbook not found`: tests that need the workbook **skip** (CI does this deliberately). Place the file as above.
- `externally-managed-environment` from pip: use the venv (`scripts/run_all.sh` creates one).
- `ZoneInfoNotFoundError`: the `tzdata` dependency is installed by `pip install -e .`; re-run the install.
- Re-running the demo is safe. It deletes and rebuilds only its own `artifacts/` subfolders.

## Limitations and known risks

- The pack has no document content, no temperature series, no batch history and no recorded-time history. Every assessment therefore abstains, and replay "as known then" is a labelled reconstruction.
- Scope-string interpretations, the presentation lexicon, notification regimes and bulletin semantics are prototype interpretations that **need QA / Regulatory Affairs approval** (`src/kccs_evidence/config/`).
- Product aliases are quarantined by policy, so 81 alias-string references stay unresolved. This is intentional and costs coverage.
- Results over the 420 rows are from a stratified evidence pack, not population estimates.
- RPO/RTO, thresholds and costs in the docs are proposals or assumptions, not measurements.

## Repository map

```
FINAL_REPORT.md            cover report for the submission
SUBMISSION_CHECKLIST.md    evaluator expectations → file/section/test
docs/01..07                deliverables A, B, data findings, validation/ops, working log (D), walkthrough
docs/submission_email.md   covering note draft
src/kccs_evidence/         kernel (see module docstrings); config/ holds versioned interpretations
tests/                     76 pytest tests (real workbook + labelled synthetic fixtures)
scripts/                   run_all.sh, inspect_workbook.py
```
