"""Shared fixtures.

Most tests run against the real workbook (place it at data/KCCS_Sentinel_Reference_Data_Pack.xlsx
or set KCCS_WORKBOOK). Tests that need a situation the workbook does not contain use small,
clearly labelled SYNTHETIC records built in this file; they never replace the workbook.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from kccs_evidence.access import Principal
from kccs_evidence.sources import SourceRecord, SourceSnapshot, canonical_json, load_workbook_snapshot, sha256_text
from kccs_evidence.store import Store
from kccs_evidence.temporal import UTC

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = Path(os.environ.get("KCCS_WORKBOOK", ROOT / "data" / "KCCS_Sentinel_Reference_Data_Pack.xlsx"))
BASELINE = "2026-09-14T00:00:00Z"
FIXED_NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def clock():
    return FIXED_NOW


@pytest.fixture(scope="session")
def snapshot():
    if not WORKBOOK.exists():
        pytest.skip(f"workbook not found at {WORKBOOK}; see README 'Where to place the workbook'")
    return load_workbook_snapshot(WORKBOOK)


@pytest.fixture()
def store(snapshot):
    st = Store(":memory:")
    st.ingest_snapshot(snapshot, BASELINE)
    return st


@pytest.fixture(scope="session")
def all_tenants(snapshot):
    return frozenset(r.tenant_code for r in snapshot.records if r.sheet == "01_Excursion_Events")


def principal(*tenants: str) -> Principal:
    return Principal("test-reviewer", frozenset(tenants))


def event_ids(snapshot, pred):
    return [r for r in snapshot.records if r.sheet == "01_Excursion_Events" and pred(r)]


# ---------------- SYNTHETIC fixtures (labelled; supplementary edge cases only) ----------------
def synthetic_record(sheet: str, key: str, row: int, tenant: str | None, attribution: str, payload: dict) -> SourceRecord:
    return SourceRecord(sheet, key, row, tenant, attribution, payload, sha256_text(canonical_json({"sheet": sheet, "payload": payload})))


def synthetic_store(records: list[SourceRecord]) -> Store:
    snap = SourceSnapshot("SNAP-SYNTHETIC", "synthetic", "0" * 64, "2026-01-01", records)
    st = Store(":memory:")
    st.ingest_snapshot(snap, "2026-01-01T00:00:00Z")
    return st
