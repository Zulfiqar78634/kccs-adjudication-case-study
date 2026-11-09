import sqlite3

import pytest
from conftest import BASELINE


def test_all_15_sheets_ingested_with_row_refs(snapshot):
    sheets = {r.sheet for r in snapshot.records}
    assert len(sheets) == 15
    events = [r for r in snapshot.records if r.sheet == "01_Excursion_Events"]
    assert len(events) == 420
    ev = next(r for r in events if r.record_key == "EXC-107133")
    assert ev.source_ref == "01_Excursion_Events!R221"
    assert ev.get("alert_ts_utc") == "2026-07-28 06:31"  # original string preserved


def test_leading_zero_gtin_preserved_as_string(snapshot):
    gtins = [r.get("gtin") for r in snapshot.records if r.sheet == "02_Product_Master" and r.get("gtin")]
    assert gtins and all(isinstance(g, str) and g.startswith("0") and len(g) == 14 for g in gtins)
    ev = next(r for r in snapshot.records if r.record_key == "EXC-107133")
    assert ev.get("product_ref_as_received") == "08901234500035"


def test_reingest_is_idempotent(store, snapshot):
    stats = store.ingest_snapshot(snapshot, BASELINE)
    assert stats == {"new_records": 0, "new_versions": 0, "unchanged": len(snapshot.records)}


@pytest.mark.parametrize("table", ["source_record_version", "assessment", "audit_event", "mapping_assertion"])
def test_append_only_tables_reject_update_and_delete(store, table):
    # Triggers only fire on existing rows, so make sure every table has one.
    store.audit(at=BASELINE, actor="t", tenant=None, action="X", target=None, outcome="OK")
    store.add_mapping(
        assertion_id="MAP-T",
        tenant="T-AURA",
        kind="FACILITY",
        source_string="x",
        canonical_id="AMS-CS-01",
        decision="APPROVED",
        actor="qa",
        recorded_at=BASELINE,
    )
    store.put_assessment(
        {"assessment_id": "ASM-T", "event": {"event_id": "E", "tenant_code": "T-AURA"}, "time_semantics": {"valid_at": BASELINE, "knowledge_cutoff": BASELINE}},
        BASELINE,
    )
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.raw_execute(f"UPDATE {table} SET rowid = rowid")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.raw_execute(f"DELETE FROM {table}")


def test_correction_adds_version_and_keeps_original(store):
    before = store.record_history("03_Facility_Registry", "SYS-05-7010")
    v = store.apply_correction(
        "03_Facility_Registry", "SYS-05-7010", {"timezone_in_source": "America/Chicago"}, "2026-10-01T00:00:00Z", "qa", "Memphis is US Central"
    )
    hist = store.record_history("03_Facility_Registry", "SYS-05-7010")
    assert v == 2 and len(hist) == 2
    assert hist[0].payload == before[0].payload and hist[0].get("timezone_in_source") == "America/New_York"
    # as known before the correction, the old value is returned
    old = store.records("03_Facility_Registry", shared=True, as_known_at="2026-09-30T00:00:00Z")
    assert next(r for r in old if r.record_key == "SYS-05-7010").get("timezone_in_source") == "America/New_York"


def test_correction_rejects_unknown_column(store):
    with pytest.raises(ValueError):
        store.apply_correction("03_Facility_Registry", "SYS-05-7010", {"nope": 1}, "2026-10-01T00:00:00Z", "qa", "x")
