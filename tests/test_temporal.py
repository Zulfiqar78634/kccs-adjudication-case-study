"""Temporal semantics: interval boundaries, site-local dates, overlaps, replay without future knowledge."""
from datetime import datetime

import pytest

from conftest import BASELINE, clock, principal, synthetic_record, synthetic_store
from kccs_evidence.access import TenantView
from kccs_evidence.assessment import build_assessment
from kccs_evidence.model import Resolution
from kccs_evidence.policy_sop import select_sop
from kccs_evidence.temporal import UTC

TEM = ["Temperature Excursion Management"]


def _sop_store(revs):
    """SYNTHETIC SOP index: two revisions handing over on 2026-03-01 (half-open)."""
    recs = [synthetic_record("05_SOP_Index", f"SOP-SYN-1 {rev}", 2 + i, "T-SYN", "TENANT",
                             {"doc_id": "SOP-SYN-1", "tenant_code": "T-SYN", "title": TEM[0], "revision": rev,
                              "effective_from": f, "effective_to": t, "supersedes_text": None,
                              "applies_to_facilities_text": scope, "format": "Native PDF", "pages": 1, "language": "en",
                              "acceptance_limits_location": "Section 7.3 table"})
            for i, (rev, f, t, scope) in enumerate(revs)]
    return synthetic_store(recs)


def _site(code="BOM-NX-04", tz="Asia/Kolkata", trusted=True, country="IN"):
    return Resolution("FACILITY", "origin", code, "RESOLVED", code, "TEST",
                      attributes={"timezone": tz, "timezone_trusted": trusted, "country": country})


HANDOVER = [("Rev 01", "2026-01-01", "2026-03-01", "All sites"), ("Rev 02", "2026-03-01", None, "All sites")]


@pytest.mark.parametrize("utc_instant, expected", [
    (datetime(2026, 2, 28, 12, 0, tzinfo=UTC), ["Rev 01"]),     # local 28 Feb
    (datetime(2026, 2, 28, 18, 29, tzinfo=UTC), ["Rev 01"]),    # 23:59 IST
    (datetime(2026, 2, 28, 18, 31, tzinfo=UTC), ["Rev 02"]),    # 00:01 IST on 1 Mar: the local date decides, not UTC
    (datetime(2026, 3, 1, 0, 0, tzinfo=UTC), ["Rev 02"]),
])
def test_half_open_boundary_in_site_local_date(utc_instant, expected):
    st = _sop_store(HANDOVER)
    view = TenantView(st, principal("T-SYN"), "T-SYN", clock=clock)
    res, findings = select_sop(view, TEM, _site(), "origin", utc_instant)
    assert res[0]["status"] == "SELECTED" and res[0]["in_force"] == expected
    assert not any(f.code == "SOP_REVISION_OVERLAP" for f in findings)


def test_untrusted_timezone_near_boundary_is_ambiguous_not_guessed():
    st = _sop_store(HANDOVER)
    view = TenantView(st, principal("T-SYN"), "T-SYN", clock=clock)
    res, findings = select_sop(view, TEM, _site(tz="America/New_York", trusted=False), "origin", datetime(2026, 2, 28, 20, 0, tzinfo=UTC))
    assert res[0]["status"] == "BOUNDARY_AMBIGUOUS"
    assert any(f.code == "SOP_BOUNDARY_AMBIGUOUS" and f.severity == "BLOCKING" for f in findings)


def test_overlap_is_a_conflict_not_resolved_by_revision_number():
    st = _sop_store([("Rev 02", "2026-01-01", "2026-06-30", "All sites"), ("Rev 03", "2026-05-01", None, "All sites")])
    view = TenantView(st, principal("T-SYN"), "T-SYN", clock=clock)
    res, findings = select_sop(view, TEM, _site(), "origin", datetime(2026, 5, 15, 6, 0, tzinfo=UTC))
    assert res[0]["status"] == "CONFLICT_OVERLAPPING_REVISIONS" and "selected" not in res[0]
    assert any(f.code == "SOP_REVISION_OVERLAP" for f in findings)


def test_site_scope_unknown_when_site_unresolved():
    st = _sop_store([("Rev 01", "2026-01-01", None, "Bhiwandi and Kundli only")])
    view = TenantView(st, principal("T-SYN"), "T-SYN", clock=clock)
    unresolved = Resolution("FACILITY", "origin", "Bhiwandi (Nx)", "UNRESOLVED")
    res, findings = select_sop(view, TEM, unresolved, "origin", datetime(2026, 5, 15, 6, 0, tzinfo=UTC))
    assert res[0]["status"] == "SELECTED_PROVISIONAL"
    assert any(f.code == "SOP_SITE_SCOPE_UNKNOWN" for f in findings)
    res2, _ = select_sop(view, TEM, _site(code="BLR-CS-02"), "origin", datetime(2026, 5, 15, 6, 0, tzinfo=UTC))
    assert res2[0]["status"] == "NOT_APPLICABLE_TO_SITE"


def test_real_overlap_exc_107133(store):
    a = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    sop = a["evidence"]["sop_origin"][0]
    assert sop["doc_id"] == "SOP-KAV-9392" and sop["status"] == "CONFLICT_OVERLAPPING_REVISIONS"
    assert sop["in_force"] == ["Rev 02", "Rev 03"] and sop["dates_evaluated"] == ["2026-07-28"]
    assert "SOP_REVISION_OVERLAP" in a["blocking_reasons"]


def test_replay_excludes_bulletin_learned_after_alert(store, snapshot):
    # A TT-2.14.3 alert raised before the 2026-04-11 bulletin.
    ev = next(r for r in snapshot.records if r.sheet == "01_Excursion_Events" and r.get("logger_fw") == "TT-2.14.3"
              and r.get("alert_ts_utc") < "2026-04-01")
    then = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff="alert", clock=clock)
    now = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff="2026-09-14T23:59:00Z", clock=clock)
    assert "FIRMWARE_BULLETIN_APPLIES" not in {f["code"] for f in then["findings"]}
    assert "FIRMWARE_BULLETIN_APPLIES" in {f["code"] for f in now["findings"]}
    assert then["excursion"]["firmware_bulletin"] is None and now["excursion"]["firmware_bulletin"] == "TT-CB-114"


def test_alias_confirmed_after_alert_is_not_used_in_replay(store, snapshot):
    # 'F00231' -> BLR-CS-02 was confirmed by a reviewer on 2026-04-30 (07_Alias_Observations!R5).
    ev = next(r for r in snapshot.records if r.sheet == "01_Excursion_Events" and r.get("origin_ref_as_received") == "F00231"
              and r.get("alert_ts_utc") < "2026-04-30")
    then = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff="alert", clock=clock)
    later = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff="2026-09-14T23:59:00Z", clock=clock)
    assert then["entities"]["origin"]["status"] == "UNRESOLVED"
    assert later["entities"]["origin"]["status"] == "RESOLVED_PROVISIONAL" and later["entities"]["origin"]["resolved_id"] == "BLR-CS-02"


def test_strict_mode_abstains_when_nothing_was_recorded_by_cutoff(store):
    a = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", knowledge_cutoff="alert", mode="STRICT", clock=clock)
    assert a["disposition_evidence_status"] == "ABSTAIN_KNOWLEDGE_HISTORY_UNAVAILABLE"


def test_cutoff_before_alert_rejected(store):
    with pytest.raises(ValueError):
        build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", knowledge_cutoff="2026-07-28T06:00:00Z", clock=clock)


def test_policy_effective_date_convention_is_recorded(store):
    a = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    assert a["time_semantics"]["valid_at"] == "2026-07-28T06:14:00Z"          # excursion start
    assert a["time_semantics"]["alert_received_at"] == "2026-07-28T06:31:00Z"
    assert "half-open" in a["time_semantics"]["policy_date_convention"]
