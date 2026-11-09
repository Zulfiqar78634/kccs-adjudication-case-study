"""Assessment-level behaviour: idempotency, leakage control, corrections, safe failure, human mappings."""

import ast
import json
from pathlib import Path

from conftest import clock, principal, synthetic_record, synthetic_store

from kccs_evidence.assessment import OUTCOME_FIELDS, assess_and_store, build_assessment

SRC = Path(__file__).resolve().parents[1] / "src" / "kccs_evidence"
ALLOWED_STATUSES = {"ABSTAIN_BLOCKING_EVIDENCE_GAPS", "READY_FOR_QA_REVIEW", "QUARANTINED_FOR_ATTRIBUTION", "ABSTAIN_KNOWLEDGE_HISTORY_UNAVAILABLE"}


def test_repeated_execution_is_idempotent(store):
    a1, new1 = assess_and_store(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    a2, new2 = assess_and_store(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    assert a1["assessment_id"] == a2["assessment_id"] and new1 is True and new2 is False
    assert len(store.assessments_for_event("T-KAVERI", "EXC-107133")) == 1


def test_assessment_id_independent_of_requesting_actor(store):
    a = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    from kccs_evidence.access import Principal

    b = build_assessment(store, Principal("someone-else", frozenset({"T-KAVERI", "T-AURA"})), "T-KAVERI", "EXC-107133", clock=clock)
    assert a["assessment_id"] == b["assessment_id"]


def test_outcome_fields_are_not_inputs(store):
    """Rewrite every outcome field of the current event; the assessment must not change."""
    before = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", knowledge_cutoff="now", clock=clock)
    store.apply_correction(
        "01_Excursion_Events",
        "EXC-107133",
        {
            "final_disposition": "DESTROY",
            "triage_outcome": "NON_ACTIONABLE — sensor artefact",
            "rules_engine_recommendation": "AUTO_CLOSE",
            "reviewer_overrode": "Y",
            "reopened_later": "Y",
            "regulator_reportable": "Y",
            "notes": "test",
        },
        "2026-10-01T00:00:00Z",
        "test",
        "outcome-leak probe",
    )
    after = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", knowledge_cutoff="now", clock=clock)
    assert before["assessment_id"] == after["assessment_id"]
    assert set(after["event"]["excluded_outcome_fields"]) == set(OUTCOME_FIELDS)
    assert not set(OUTCOME_FIELDS) & set(after["event"]["allowed_input_fields"])


def test_evidence_logic_modules_never_mention_outcome_fields():
    """Evidence logic must not reference outcome columns. Reporting layers (evaluation, inspection, cli summary) may;
    assessment.py holds the OUTCOME_FIELDS exclusion list and the knowledge-gated precedent view of earlier cases."""
    kernel = {
        "access.py",
        "resolution.py",
        "policy_sop.py",
        "stability.py",
        "signals.py",
        "obligations.py",
        "store.py",
        "sources.py",
        "temporal.py",
        "model.py",
        "package.py",
        "config_loader.py",
    }
    outcome = set(OUTCOME_FIELDS) - {"notes"}  # 'notes' is also a generic dict key used by result objects
    offenders = {}
    for py in SRC.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if names & outcome:
            offenders[py.name] = sorted(names & outcome)
    assert not set(offenders) & kernel, offenders
    gate_reads = set(offenders.get("assessment.py", [])) - outcome
    assert not gate_reads


def test_correction_produces_new_assessment_and_old_is_immutable(store):
    orig, _ = assess_and_store(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    row_before = dict(store.get_assessment_row(orig["assessment_id"]))
    pm = next(r for r in store.records("02_Product_Master", tenant="T-KAVERI") if r.get("stability_study_ref") == "STB-3584")
    store.apply_correction(
        "02_Product_Master", pm.record_key, {"stability_study_ref": "STB-2738"}, "2026-09-20T10:00:00Z", "SIMULATED-QA", "SIMULATED correction (test)"
    )
    new, inserted = assess_and_store(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", knowledge_cutoff="2026-09-21T00:00:00Z", clock=clock)
    assert inserted and new["assessment_id"] != orig["assessment_id"] and new["supersedes"] == orig["assessment_id"]
    assert "STABILITY_REFERENCED_STUDY_INADMISSIBLE" in new["change_from_superseded"]["removed_findings"]
    assert dict(store.get_assessment_row(orig["assessment_id"])) == row_before
    replay = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", knowledge_cutoff="alert", clock=clock)
    assert replay["assessment_id"] == orig["assessment_id"]  # what we concluded then is reproducible


def test_bulletin_reassessment_recommends_reopen_without_editing_original(store, snapshot):
    ev = next(r for r in snapshot.records if r.sheet == "01_Excursion_Events" and r.get("logger_fw") == "TT-2.14.3" and r.get("alert_ts_utc") < "2026-04-01")
    then, _ = assess_and_store(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, clock=clock)
    later, _ = assess_and_store(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff="2026-09-14T23:59:00Z", clock=clock)
    assert later["change_from_superseded"]["reopen_review_recommended"] is True
    assert "FIRMWARE_BULLETIN_APPLIES" in later["change_from_superseded"]["added_findings"]
    assert json.loads(store.get_assessment_row(then["assessment_id"])["payload_json"])["assessment_id"] == then["assessment_id"]


def test_missing_product_reference_abstains(store, snapshot):
    ev = next(r for r in snapshot.records if r.sheet == "01_Excursion_Events" and not r.get("product_ref_as_received"))
    a = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, clock=clock)
    assert a["entities"]["product"]["status"] == "MISSING_INPUT"
    assert {"PRODUCT_REF_MISSING", "STABILITY_NOT_SELECTABLE"} <= set(a["blocking_reasons"])


def test_never_a_disposition_across_all_events(store, snapshot):
    for ev in [r for r in snapshot.records if r.sheet == "01_Excursion_Events"]:
        a = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, clock=clock)
        assert a["is_disposition"] is False and a["disposition_evidence_status"] in ALLOWED_STATUSES
        assert a["required_human_actions"][-1]["because"] == "DISPOSITION_IS_A_HUMAN_DECISION"
        text = json.dumps(a["reviewer_aid"]) + a["disposition_evidence_status"]
        assert not any(w in text for w in ("RELEASE", "DESTROY", "QUARANTINE_PENDING_LAB", "RETURN_TO_ORIGIN", "REWORK", "AUTO_CLOSE"))
        assert not any("disposition" in k and k not in ("disposition_evidence_status", "disposition_authority", "is_disposition") for k in a)
        # Missing evidence is never favourable: blocked => not READY
        if a["blocking_reasons"]:
            assert a["disposition_evidence_status"] != "READY_FOR_QA_REVIEW"


def test_conflicting_tenant_attribution_is_quarantined(store):
    store.apply_correction(
        "01_Excursion_Events", "EXC-107133", {"shipment_ref": "SHP-MER-000001"}, "2026-10-01T00:00:00Z", "test", "SIMULATED conflicting attribution"
    )
    a = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", knowledge_cutoff="now", clock=clock)
    assert a["disposition_evidence_status"] == "QUARANTINED_FOR_ATTRIBUTION"


def test_untrusted_alias_then_human_approved_mapping(store, snapshot):
    ev = next(r for r in snapshot.records if r.sheet == "01_Excursion_Events" and r.get("origin_ref_as_received") == "F00231")
    cutoff = "2026-09-14T23:59:00Z"
    a = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff=cutoff, clock=clock)
    assert a["entities"]["origin"]["status"] == "RESOLVED_PROVISIONAL"
    assert a["entities"]["origin"]["basis"] == "UNVERIFIED_REVIEWER_ALIAS"
    assert any(f["code"] == "ORIGIN_FACILITY_PROVISIONAL" and f["severity"] == "REVIEW" for f in a["findings"])
    store.add_mapping(
        assertion_id="MAP-0001",
        tenant=None,
        kind="FACILITY",
        source_string="F00231",
        canonical_id="BLR-CS-02",
        decision="APPROVED",
        actor="qa-lead",
        recorded_at="2026-09-20T00:00:00Z",
        evidence_ref="07_Alias_Observations!R5",
    )
    b = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff="2026-09-21T00:00:00Z", clock=clock)
    assert b["entities"]["origin"]["status"] == "RESOLVED" and b["entities"]["origin"]["basis"] == "APPROVED_MAPPING MAP-0001"
    c = build_assessment(store, principal(ev.tenant_code), ev.tenant_code, ev.record_key, knowledge_cutoff=cutoff, clock=clock)
    assert c["entities"]["origin"]["basis"] == "UNVERIFIED_REVIEWER_ALIAS"  # mapping not visible before its recorded_at


def test_product_ambiguity_synthetic():
    """SYNTHETIC: the workbook has no tenant with two product rows sharing an identifier; build one."""

    def pm(row, spec):
        return synthetic_record(
            "02_Product_Master",
            f"R{row}",
            row,
            "T-SYN",
            "TENANT",
            {
                "tenant_code": "T-SYN",
                "brand_as_labelled": "Amberil 25mg tabs",
                "internal_sku": "SKU-ORL-7781",
                "gtin": None,
                "legacy_code": None,
                "generic_inn": None,
                "storage_spec_text": spec,
                "permitted_excursion_text": None,
                "stability_study_ref": None,
                "last_updated": "2025-01-01",
            },
        )

    st = synthetic_store([pm(2, "CRT 15-25C"), pm(3, "2-8 °C")])
    from kccs_evidence.access import TenantView
    from kccs_evidence.resolution import resolve_product

    res, findings = resolve_product(TenantView(st, principal("T-SYN"), "T-SYN", clock=clock), "SKU-ORL-7781")
    assert res.status == "AMBIGUOUS" and len(res.candidates) == 2 and res.resolved_id is None
    assert findings[0].code == "PRODUCT_AMBIGUOUS" and findings[0].severity == "BLOCKING"
