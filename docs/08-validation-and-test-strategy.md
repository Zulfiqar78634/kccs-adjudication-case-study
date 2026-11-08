# Validation and Test Strategy

## Evidence status
This revision does not assert a fresh test pass. Earlier conversation reports 15 passing tests and 420 processed events; neither is independently reproduced here. Processing rows is not proof of correct adjudication. Proposed checks below must not be represented as implemented without test evidence.

## Local execution (PowerShell, repository root)
Use a fresh terminal and preserve logs locally. Do not publish confidential workbook data or derived outputs without permission.

```powershell
git pull --ff-only origin main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r prototype/requirements.txt
python -m pip install -e prototype
New-Item -ItemType Directory -Force output | Out-Null
git rev-parse HEAD | Set-Content output/tested-commit.txt
python --version 2>&1 | Tee-Object output/python-version.txt
python -m pip freeze | Set-Content output/dependencies.txt
Get-FileHash data/KCCS_Sentinel_Reference_Data_Pack.xlsx -Algorithm SHA256 | Format-List | Out-File output/workbook-hash.txt
python -m pytest prototype/tests -q 2>&1 | Tee-Object output/pytest.txt
if ($LASTEXITCODE -ne 0) { throw 'Tests failed: stop submission validation.' }
python -m adjudication.cli run --workbook data/KCCS_Sentinel_Reference_Data_Pack.xlsx --output-dir output/local-validation 2>&1 | Tee-Object output/workbook-run.txt
if ($LASTEXITCODE -ne 0) { throw 'Workbook execution failed.' }
Get-Content output/local-validation/run_manifest.json
`` delimited

Replace the preceding closing marker with a standard Markdown code fence when reading: the commands end at Get-Content.

## Record before submission
Fill in actual tested commit, environment, workbook hash, test count/pass/fail, command exits, manifest counts, warnings and unresolved defects. Review adjudication_summary.csv, evidence_gaps.csv, case_audit_log.csv and adjudication_report.json; existence alone is not correctness. Missing or skipped source rows must be reconciled.

## Required correctness evidence
For each check record expected result, actual result, source sheet/event, assertion or manual verification, and pass/fail:
- EXC-107133 uses 06:31 alert time, not 06:14 excursion start; its reportable=N flag must not become a notification breach.
- A timely notification can coexist with a late disposition. Unknown notification evidence is distinct from proven late notification.
- Exact deadline, UTC/local offsets, overlapping SOP revisions and next-business-day rules have explicit boundary semantics.
- Product/study ownership and presentation, negative/conflicting aliases, and tenant/facility SOP applicability fail conservatively.
- Calibration correction creates a linked new attempt without deleting original inputs, decisions or clock events.
- Historical disposition import is not a newly authenticated approval. Exported CSV is not immutable production storage.

## Current source-review limitations
The reviewed CLI loads SOP objects without tenant or facility applicability and does not pass event tenant identity as an explicit ExcursionEvent argument. It maps product identifiers to one selected column and constructs aliases directionally. These are unresolved safety review items, not certified defects in every downstream path; inspect the full services and add regression tests before claiming tenant-safe production adjudication. This documentation change does not repair those code paths.

## Proposed long-term reliability controls (not implemented by this document)
- Versioned golden cases with QA-reviewed disagreements before each rules/model/prompt change; property tests and adapter contract tests.
- Independent scheduler heartbeat: page after two missed one-minute heartbeats; due-time sweeps and durable restart replay.
- Proposed notification escalation at 50%, 75% and 90% of verified window; immediate escalation for overdue unacknowledged filings. Verify policy with Regulatory Affairs.
- Alert-storm tenant isolation, duplicate replay, dependency-outage and restore drills; manual filing owner and acknowledgement record.
- Source-to-load reconciliation, missing evidence/conflicting identity metrics, cross-tenant access denial tests and audit retrieval under one hour.
- On-call runbook must identify owners, severity, recovery commands and manual fallback before production qualification.

A local pass demonstrates runnable software and tested assertions, not GxP qualification or complete fulfilment of the design.
