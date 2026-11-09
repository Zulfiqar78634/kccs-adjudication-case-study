"""Portable end-to-end test of the command-line tool, using a SYNTHETIC workbook (no confidential data).

Runs on every platform in CI, including Windows and macOS, where the real workbook is not available.
It covers the platform-sensitive paths: subprocess console encoding of non-ASCII output, byte-exact
evidence-package files (Windows newline translation), file paths, SQLite and time zones.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from synthetic_workbook import build

NOW = "2026-11-08T12:00:00Z"


@pytest.fixture(scope="module")
def env_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("portable")
    wb = build(d / "synthetic.xlsx")
    return d, wb


def cli(*args, cwd) -> subprocess.CompletedProcess:
    # Remove UTF-8 overrides so the platform's default console encoding is exercised (cp1252 on Windows).
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    return subprocess.run([sys.executable, "-m", "kccs_evidence.cli", *map(str, args)], capture_output=True, cwd=cwd, env=env)


def test_full_cli_flow_on_this_platform(env_dir):
    d, wb = env_dir
    db = d / "k.sqlite"

    p = cli("ingest", "--workbook", wb, "--db", db, cwd=d)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    assert json.loads(p.stdout)["new_records"] > 0
    assert json.loads(cli("ingest", "--workbook", wb, "--db", db, cwd=d).stdout)["new_records"] == 0

    # Printing an assessment containing "°" and "—" to a pipe must not crash and must be UTF-8.
    p = cli("assess", "--db", db, "--tenant", "T-KAVERI", "--event", "EXC-900001", "--knowledge-cutoff", "alert", "--now", NOW, cwd=d)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    text = p.stdout.decode("utf-8")
    assert "°" in text and "—" in text
    a = json.loads(text)
    assert a["is_disposition"] is False and a["disposition_evidence_status"] == "ABSTAIN_BLOCKING_EVIDENCE_GAPS"
    assert a["evidence"]["sop_origin"][0]["status"] == "CONFLICT_OVERLAPPING_REVISIONS"
    assert a["evidence"]["sop_origin"][0]["in_force"] == ["Rev 01", "Rev 02"]
    assert a["evidence"]["stability"]["referenced"]["study_ref"] == "STB-0001"
    assert a["evidence"]["stability"]["referenced"]["admissible"] is True
    assert a["notification_track"]["due_at_utc"] == "2026-07-30T06:30:00Z"           # India 360 h from alert receipt
    aid = a["assessment_id"]
    if os.environ.get("KCCS_ID_OUT"):                                                     # CI compares this across OSes
        Path(os.environ["KCCS_ID_OUT"]).write_text(aid + "\n" + a["manifest"]["code_sha256"] + "\n", encoding="utf-8")

    p = cli("assess", "--db", db, "--tenant", "T-KAVERI", "--event", "EXC-900001", "--knowledge-cutoff", "alert", "--now", NOW, cwd=d)
    assert json.loads(p.stdout.decode("utf-8"))["assessment_id"] == aid                 # reproducible

    # Evidence package: export, verify, then tamper (Windows newline translation used to break this).
    p = cli("export-package", "--db", db, "--assessment-id", aid, "--tenant-scope", "T-KAVERI", "--out-dir", d / "pk", "--now", NOW, cwd=d)
    assert p.returncode == 0 and json.loads(p.stdout)["ok"] is True, p.stdout + p.stderr
    pkg = d / "pk" / aid
    assert b"\r\n" not in (pkg / "assessment.json").read_bytes()
    assert cli("verify-package", pkg, cwd=d).returncode == 0
    f = pkg / "assessment.json"
    f.write_bytes(f.read_bytes().replace(b"ABSTAIN_BLOCKING_EVIDENCE_GAPS", b"READY_FOR_QA_REVIEW"))
    p = cli("verify-package", pkg, cwd=d)
    assert p.returncode == 2 and "hash mismatch" in p.stdout.decode("utf-8")

    # Access control and error handling.
    p = cli("assess", "--db", db, "--tenant", "T-PINNACLE", "--tenant-scope", "T-KAVERI", "--event", "EXC-900002", cwd=d)
    assert p.returncode == 3 and b"ACCESS DENIED" in p.stderr
    p = cli("assess", "--db", db, "--tenant", "T-KAVERI", "--event", "EXC-900002", cwd=d)  # other tenant's event
    assert p.returncode == 4 and b"NOT FOUND" in p.stderr and b"Traceback" not in p.stderr
    p = cli("ingest", "--workbook", d / "missing.xlsx", "--db", db, cwd=d)
    assert p.returncode == 2 and b"Traceback" not in p.stderr


def test_code_fingerprint_ignores_line_endings(tmp_path, monkeypatch):
    """A CRLF checkout (Git for Windows default) must fingerprint the same code identically."""
    import shutil
    import kccs_evidence
    from kccs_evidence import assessment

    src = Path(kccs_evidence.__file__).parent
    lf = assessment.code_fingerprint()
    crlf_pkg = tmp_path / "kccs_evidence"
    shutil.copytree(src, crlf_pkg, ignore=shutil.ignore_patterns("__pycache__"))
    for py in crlf_pkg.glob("*.py"):
        py.write_bytes(py.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))

    class _Res:
        @staticmethod
        def files(_name):
            return crlf_pkg

    monkeypatch.setattr(assessment, "resources", _Res)
    assert assessment.code_fingerprint() == lf
