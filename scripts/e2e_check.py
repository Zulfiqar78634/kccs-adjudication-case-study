#!/usr/bin/env python3
"""End-to-end check that works the same on Windows, macOS and Linux.

Creates a fresh virtual environment, installs the package, runs the test suite, the demo and the
command-line checks, and records everything in evidence/. Exits 0 only if every check passes.

    python scripts/e2e_check.py [path/to/KCCS_Sentinel_Reference_Data_Pack.xlsx]
    python scripts/e2e_check.py --synthetic      # no workbook needed: platform smoke test on invented data

Use `python3` on macOS/Linux and `py -3.12` (or `python`) on Windows.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 - this script may be started by an older interpreter
    sys.exit(f"Python 3.11 or newer is required; this is {platform.python_version()}.\n"
             "Run it with a newer interpreter, e.g. `python3.12 scripts/e2e_check.py` (macOS/Linux) "
             "or `py -3.12 scripts\\e2e_check.py` (Windows). Install from https://www.python.org/downloads/")

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
args = [a for a in sys.argv[1:] if a != "--synthetic"]
SYNTHETIC = "--synthetic" in sys.argv[1:]

if SYNTHETIC:
    # Invented data only; results go to artifacts/, never to the committed evidence/ folder.
    EV = Path("artifacts/e2e-synthetic/evidence")
    ART = Path("artifacts/e2e-synthetic/run")
else:
    EV = Path("evidence")
    ART = Path("artifacts/e2e")
LOG, RES = EV / "logs", EV / "results"
for p in (LOG, RES, ART):
    shutil.rmtree(p, ignore_errors=True)
for p in EV.glob("*.txt"):
    p.unlink()
for p in (LOG, RES, ART):
    p.mkdir(parents=True, exist_ok=True)

if SYNTHETIC:
    WB = ART / "synthetic_workbook.xlsx"          # built after install, with the fresh environment's openpyxl
else:
    WB = Path(args[0] if args else "data/KCCS_Sentinel_Reference_Data_Pack.xlsx")
    if not WB.is_file():
        sys.exit(f"Workbook not found at {WB}. Copy KCCS_Sentinel_Reference_Data_Pack.xlsx into the data folder (see README),\n"
                 "or run `python scripts/e2e_check.py --synthetic` for a platform check on invented data.")

VENV = ROOT / ".venv-e2e"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
if not SYNTHETIC:
    ENV["KCCS_WORKBOOK"] = str(WB.resolve())
else:
    ENV.pop("KCCS_WORKBOOK", None)
NOW = "2026-11-08T12:00:00Z"
rows: list[tuple[str, str, str, str, str]] = []


def record(cid: str, check: str, expected, observed) -> None:
    res = "PASS" if str(expected) == str(observed) else "FAIL"
    rows.append((cid, check, str(expected), str(observed), res))
    print(f"{cid:<4} {res:<5} {check}" + ("" if res == "PASS" else f"   (expected {expected!r}, got {observed!r})"), flush=True)


def run(cmd: list, log: str) -> subprocess.CompletedProcess:
    proc = subprocess.run([str(a) for a in cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=ENV, cwd=ROOT)
    with open(LOG / log, "a", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(str(a) for a in cmd)}\n{proc.stdout}{proc.stderr}[exit {proc.returncode}]\n\n")
    return proc


def cli(*a, log: str = "05_cli.log") -> subprocess.CompletedProcess:
    return run([VPY, "-m", "kccs_evidence.cli", *a], log)


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def count(stdout: str, word: str) -> str:
    for line in reversed(stdout.splitlines()):
        toks = line.replace(",", " ").split()
        for i, t in enumerate(toks[1:], 1):
            if t == word and toks[i - 1].isdigit():
                return f"{toks[i - 1]} {word}"
    return f"0 {word}"


started = time.time()
git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT)

# E1 fresh install
shutil.rmtree(VENV, ignore_errors=True)
subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
run([VPY, "-m", "pip", "install", "-q", "--upgrade", "pip"], "01_install.log")
record("E1", "Fresh install (pip install -e .[dev])", 0, run([VPY, "-m", "pip", "install", "-e", ".[dev]"], "01_install.log").returncode)
(EV / "pip_freeze.txt").write_text(run([VPY, "-m", "pip", "freeze", "--exclude-editable"], "01_install.log").stdout, encoding="utf-8")
vpy_version = run([VPY, "--version"], "01_install.log").stdout.strip()
if SYNTHETIC:
    run([VPY, "-c", "import sys; sys.path.insert(0, 'tests'); from synthetic_workbook import build; build(sys.argv[1])", WB],
        "01_install.log")
    if not WB.is_file():
        sys.exit(f"Could not build the synthetic workbook; see {LOG / '01_install.log'}")
(EV / "environment.txt").write_text(
    f"date_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
    f"git_commit: {git.stdout.strip() or 'n/a'}\n"
    f"python: {vpy_version}\n"
    f"os: {platform.system()} {platform.release()} ({platform.platform()})\n"
    f"workbook: {'SYNTHETIC (tests/synthetic_workbook.py)' if SYNTHETIC else WB.name}\n"
    f"workbook_sha256: {hashlib.sha256(WB.read_bytes()).hexdigest()}\n"
    f"workbook_bytes: {WB.stat().st_size}\n", encoding="utf-8")

# E2-E3 test suite
p = run([VPY, "-m", "pytest", "-v", "-o", "addopts=", "-p", "no:cacheprovider"], "02_pytest.log")
record("E2", "Test suite exit code", 0, p.returncode)
if SYNTHETIC:
    record("E3", "Tests needing the real workbook are skipped, none fail", "0 failed", count(p.stdout, "failed"))
else:
    record("E3", "Tests passed (none skipped)", "78 passed / 0 skipped", f"{count(p.stdout, 'passed')} / {count(p.stdout, 'skipped')}")

# E4 inspection
record("E4", "Workbook inspection report written", 0,
       cli("inspect", "--workbook", WB, "--out-dir", ART / "data_quality", log="03_inspect.log").returncode)

if SYNTHETIC:
    tenant, event, other_tenant, other_event = "T-KAVERI", "EXC-900001", "T-PINNACLE", "EXC-900002"
else:
    tenant, event, other_tenant, other_event = "T-KAVERI", "EXC-107133", "T-MERIDIAN", "EXC-110630"
    # E5-E12 demo (needs the real workbook's events)
    p = cli("demo", "--workbook", WB, "--out-dir", ART, "--now", NOW, log="04_demo.log")
    record("E5", "Full demo exit code", 0, p.returncode)
    d = load(ART / "demo_run.json")
    record("E6", "Workbook rows ingested", 1413, d["ingest"]["new_records"])
    record("E7", "Re-ingest is idempotent (new records)", 0, d["ingest_again_idempotent"]["new_records"])
    record("E8", "Cross-tenant read denied in demo", True, d["isolation_demo"].startswith("DENIED"))
    record("E9", "Correction leaves original assessment byte-identical", True, d["correction_demo"]["original_unchanged"])
    record("E10", "At-alert replay after correction reproduces original ID", True,
           d["correction_demo"]["replay_at_alert_after_correction_same_id"])
    stored = next((ln.split("assessments stored:")[1].split(";")[0].strip() for ln in p.stdout.splitlines()
                   if "assessments stored:" in ln), "none")
    record("E11", "Assessments stored", 841, stored)
    record("E12", "All demo evidence packages verify", True,
           all(x["ok"] for x in d["packages_verified"]) and len(d["packages_verified"]) == 6)

    # E13-E18 brief case EXC-107133
    a = load(ART / "cases/EXC-107133_at_alert.json")
    sop, st = a["evidence"]["sop_origin"][0], a["evidence"]["stability"]
    record("E13", "EXC-107133 abstains (no disposition)", "ABSTAIN_BLOCKING_EVIDENCE_GAPS False",
           f"{a['disposition_evidence_status']} {a['is_disposition']}")
    record("E14", "EXC-107133 product resolved within T-KAVERI", "02_Product_Master!R57", a["entities"]["product"]["resolved_id"])
    record("E15", "EXC-107133 SOP overlap detected", "SOP-KAV-9392 CONFLICT_OVERLAPPING_REVISIONS ['Rev 02', 'Rev 03']",
           f"{sop['doc_id']} {sop['status']} {sop['in_force']}")
    record("E16", "EXC-107133 wrong-presentation study rejected", "STB-3584 False",
           f"{st['referenced']['study_ref']} {st['referenced']['admissible']}")
    record("E17", "EXC-107133 pen study offered as candidate", True,
           any(c["study_ref"] == "STB-2738" and c["admissible"] for c in st["unreferenced_candidates"]))
    record("E18", "EXC-107133 notification deadline from alert receipt", "2026-08-12T06:31:00Z", a["notification_track"]["due_at_utc"])

# E19-E25 command line, in a separate database
db = ART / "cli.sqlite"
cli("ingest", "--workbook", WB, "--db", db)
cli("assess", "--db", db, "--tenant", tenant, "--event", event, "--knowledge-cutoff", "alert", "--now", NOW, "--out", ART / "then.json")
id1 = load(ART / "then.json")["assessment_id"]
if SYNTHETIC:
    cli("assess", "--db", db, "--tenant", tenant, "--event", event, "--knowledge-cutoff", "alert", "--now", NOW, "--out", ART / "again.json")
    record("E19", "Assessment ID reproducible across runs", id1, load(ART / "again.json")["assessment_id"])
else:
    record("E19", "Assessment ID reproducible across runs", d["correction_demo"]["original_assessment"], id1)
cli("assess", "--db", db, "--tenant", tenant, "--event", event, "--knowledge-cutoff", "2026-09-14T23:59:00Z", "--now", NOW,
    "--out", ART / "later.json")
record("E20", "Later knowledge cutoff gives a different assessment", True, load(ART / "later.json")["assessment_id"] != id1)
record("E21", "CLI cross-tenant read refused (exit code)", 3,
       cli("assess", "--db", db, "--tenant", other_tenant, "--tenant-scope", tenant, "--event", other_event).returncode)
cli("export-package", "--db", db, "--assessment-id", id1, "--tenant-scope", tenant, "--out-dir", ART / "cli_packages")
pkg = ART / "cli_packages" / id1
record("E22", "Exported package verifies", 0, cli("verify-package", pkg).returncode)
record("E23", "Other tenant cannot export the package (exit code)", 3,
       cli("export-package", "--db", db, "--assessment-id", id1, "--tenant-scope", other_tenant, "--out-dir", ART / "other").returncode)
f = pkg / "assessment.json"
f.write_bytes(f.read_bytes().replace(b"ABSTAIN_BLOCKING_EVIDENCE_GAPS", b"READY_FOR_QA_REVIEW"))
record("E24", "Tampered package rejected (exit code)", 2, cli("verify-package", pkg).returncode)
again = json.loads(cli("ingest", "--workbook", WB, "--db", db).stdout.strip().splitlines()[-1])
record("E25", "CLI re-ingest adds nothing", '"new_records": 0', f'"new_records": {again["new_records"]}')

if not SYNTHETIC:
    # Derived results only: no workbook rows, no database.
    shutil.copyfile(ART / "evaluation/summary.md", RES / "evaluation_summary.md")
    shutil.copyfile(ART / "data_quality/report.md", RES / "data_quality_report.md")
    shutil.copyfile(ART / "demo_run.json", RES / "demo_run.json")
    keep = {k: a[k] for k in ("assessment_id", "disposition_evidence_status", "is_disposition", "blocking_reasons",
                              "time_semantics", "required_human_actions", "notification_track", "disposition_authority")}
    keep["entities"] = {k: {f2: v[f2] for f2 in ("input_value", "status", "resolved_id", "basis")} for k, v in a["entities"].items()}
    keep["sop_origin"] = [{f2: s.get(f2) for f2 in ("doc_id", "status", "in_force", "dates_evaluated", "date_basis")}
                          for s in a["evidence"]["sop_origin"]]
    keep["stability"] = {"status": st["status"],
                         "referenced": {f2: st["referenced"][f2] for f2 in ("study_ref", "admissible", "rejection_reasons")},
                         "candidates": [{f2: c[f2] for f2 in ("study_ref", "admissible", "rejection_reasons")}
                                        for c in st["unreferenced_candidates"]]}
    keep["reviewer_aid"] = a["reviewer_aid"]["items"]
    keep["manifest"] = {k: a["manifest"][k] for k in ("kernel_version", "ruleset_version", "code_sha256", "config", "model", "stubs")}
    (RES / "EXC-107133_assessment_excerpt.json").write_text(json.dumps(keep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

with open(RES / "checks.tsv", "w", encoding="utf-8", newline="\n") as fh:
    fh.write("id\tcheck\texpected\tobserved\tresult\n")
    for r in rows:
        fh.write("\t".join(r) + "\n")
failed = sum(r[4] == "FAIL" for r in rows)
summary = f"checks: {len(rows)}, failed: {failed}"
(EV / "RESULT.txt").write_text(summary + "\n", encoding="utf-8")
shutil.rmtree(VENV, ignore_errors=True)
print(f"{summary}   ({time.time() - started:.0f} s, {vpy_version}, {platform.system()}"
      f"{', SYNTHETIC workbook' if SYNTHETIC else ''}; evidence in {EV})")
sys.exit(1 if failed else 0)
