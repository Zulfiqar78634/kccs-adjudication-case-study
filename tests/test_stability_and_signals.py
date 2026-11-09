"""Stability evidence, limit arithmetic and firmware uncertainty on real workbook cases."""

import pytest
from conftest import clock, principal

from kccs_evidence.access import TenantView
from kccs_evidence.assessment import build_assessment
from kccs_evidence.model import Resolution
from kccs_evidence.signals import evaluate_limit, excursion_direction, parse_limit, parse_spec_range
from kccs_evidence.stability import assess_stability, assess_study, study_presentations

FW = {"bulletin_id": "TT-CB-114", "direction": "UNDER_REPORTS", "magnitude_c_max": 1.8, "magnitude_c_min": 0.0}


def test_exc_107133_wrong_presentation_partial_and_unreferenced_candidate(store):
    a = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    st = a["evidence"]["stability"]
    assert st["referenced"]["study_ref"] == "STB-3584" and not st["referenced"]["admissible"]
    reasons = " ".join(st["referenced"]["rejection_reasons"])
    assert "presentation mismatch" in reasons and "Partial" in reasons and "Accelerated" in reasons
    cands = {c["study_ref"]: c for c in st["unreferenced_candidates"]}
    assert cands["STB-2738"]["admissible"] is True
    assert cands["STB-4400"]["admissible"] is False and cands["STB-4400"]["permitted_excursion_text"] is None  # unreadable
    assert st["status"] == "CANDIDATE_ONLY"
    assert "STABILITY_MASTER_VS_STUDY_CONFLICT" in a["blocking_reasons"]  # master 'cumulative 72 h' vs study 'once, 6 h < 15 °C'
    aid = {i["statement"].split(":")[-1].strip() for i in a["reviewer_aid"]["items"]}
    assert "WITHIN_STATED_LIMIT_FOR_THIS_EVENT_ONLY" in aid and "CUMULATIVE_UNVERIFIABLE" in aid


def test_exc_110497_pfs_product_vial_study_rejected(store):
    # Override reason: "STB-4417 is the vial, this shipment is the pre-filled syringe."
    a = build_assessment(store, principal("T-VIRENT"), "T-VIRENT", "EXC-110497", clock=clock)
    ref = a["evidence"]["stability"]["referenced"]
    assert ref["study_ref"] == "STB-4417" and not ref["admissible"]
    assert any("presentation mismatch" in r for r in ref["rejection_reasons"])
    assert study_presentations("Rinvatec PFS 40 — vial") == {"VIAL"}
    assert study_presentations("Glucodyne SoloJet (insulin glargine-kbx) — vial") == {"VIAL"}


def test_unreadable_study_with_index_limit_text_is_not_relied_on(store):
    view = TenantView(store, principal("T-AURA"), "T-AURA", clock=clock)
    stb = {s.record_key: s for s in view.tenant_records("06_Stability_Index")}
    assert stb["STB-5652"].get("permitted_excursion_text")  # the index row has text...
    res = assess_study(stb["STB-5652"], {"brand_as_labelled": "Somavance depot 120mg", "generic_inn": "lanreotide-vsp"}, "T-AURA")
    assert not res["admissible"] and res["permitted_excursion_text"] is None  # ...but it is never used
    assert any("unreadable" in r for r in res["rejection_reasons"])


def test_missing_and_unindexed_study_refs_are_explicit(store, snapshot):
    view = TenantView(store, principal("T-KAVERI"), "T-KAVERI", clock=clock)
    rows = {r.source_ref: r for r in view.tenant_records("02_Product_Master")}
    blank = rows["02_Product_Master!R55"]  # Frigovac-B, no stability_study_ref
    res = Resolution("PRODUCT", "product", "x", "RESOLVED", blank.source_ref, attributes=dict(blank.payload))
    ev = {"max_temp_c": 9.0, "min_temp_c": 4.0, "duration_min": 20}
    out, findings = assess_stability(view, res, ev, (2.0, 8.0), None)
    assert "STABILITY_REF_MISSING" in {f.code for f in findings}
    # A reference that is not in this tenant's index: absence is not evidence of absence.
    ref_rows = [r for r in snapshot.records if r.sheet == "02_Product_Master" and r.get("stability_study_ref")]
    indexed = {(r.tenant_code, r.record_key) for r in snapshot.records if r.sheet == "06_Stability_Index"}
    missing = next(r for r in ref_rows if (r.tenant_code, r.get("stability_study_ref")) not in indexed)
    v2 = TenantView(store, principal(missing.tenant_code), missing.tenant_code, clock=clock)
    res2 = Resolution("PRODUCT", "product", "x", "RESOLVED", missing.source_ref, attributes=dict(missing.payload))
    _, f2 = assess_stability(v2, res2, ev, (2.0, 8.0), None)
    msg = next(f.message for f in f2 if f.code == "STABILITY_REF_NOT_IN_TENANT_INDEX")
    assert "absence is not evidence" in msg


@pytest.mark.parametrize(
    "text, kind",
    [
        ("One excursion, up to 6 h below 15 °C", "SINGLE_BELOW_CEILING"),
        ("≤ 6 h to 15 °C, once only", "SINGLE_BELOW_CEILING"),
        ("Cumulative 72 h above 8 °C permitted across shelf life", "CUMULATIVE_ABOVE"),
        ("No excursion above 25 °C permitted", "CEILING"),
        ("Refer QA", "REFER_QA"),
        ("Do not freeze", "NO_FREEZE"),
        ("Something new", "UNPARSED"),
    ],
)
def test_limit_parsing(text, kind):
    assert parse_limit(text)["kind"] == kind


def test_firmware_up_to_1_8_is_an_interval_not_a_fixed_offset():
    lim = parse_limit("One excursion, up to 6 h below 15 °C")
    near = {"max_temp_c": 14.0, "min_temp_c": 5.0, "duration_min": 30}
    assert evaluate_limit(lim, near, (2.0, 8.0), None)["status"] == "WITHIN_STATED_LIMIT_FOR_THIS_EVENT_ONLY"
    res = evaluate_limit(lim, near, (2.0, 8.0), FW)
    assert res["status"] == "INDETERMINATE_FIRMWARE_UNCERTAINTY" and res["firmware_band_c"]["max"] == [14.0, 15.8]
    far = {"max_temp_c": 11.2, "min_temp_c": 5.4, "duration_min": 15}
    assert evaluate_limit(lim, far, (2.0, 8.0), FW)["status"] == "WITHIN_STATED_LIMIT_FOR_THIS_EVENT_ONLY"
    inside = {"max_temp_c": 7.0, "min_temp_c": 4.0}
    assert excursion_direction(inside, (2.0, 8.0), FW) == "WITHIN_REPORTED_BUT_POSSIBLY_ABOVE_AFTER_FIRMWARE_CORRECTION"


def test_exc_110448_cold_excursion_with_affected_firmware(store):
    # Reviewer reasoned "real max was probably inside spec". Reported min 0 °C on a 2–8 °C product; even the full
    # +1.8 °C band leaves the minimum below 2 °C, so the kernel keeps it a cold excursion.
    a = build_assessment(store, principal("T-VIRENT"), "T-VIRENT", "EXC-110448", clock=clock)
    assert a["excursion"]["firmware_bulletin"] == "TT-CB-114"
    assert a["excursion"]["direction_vs_spec_as_received"] == "BELOW"
    assert {"FIRMWARE_BULLETIN_APPLIES", "COLD_EXCURSION"} <= {f["code"] for f in a["findings"]}


def test_cumulative_allowance_never_reported_as_satisfied():
    lim = parse_limit("Cumulative 72 h above 8 °C permitted across shelf life")
    res = evaluate_limit(lim, {"max_temp_c": 9.0, "min_temp_c": 5.0, "duration_min": 41}, (2.0, 8.0), None)
    assert res["status"] == "CUMULATIVE_UNVERIFIABLE" and res["unverifiable_conditions"]


@pytest.mark.parametrize(
    "text, rng",
    [
        ("2-8 °C", (2.0, 8.0)),
        ("+2/+8 C", (2.0, 8.0)),
        ("2°C – 8°C", (2.0, 8.0)),
        ("FROZEN (-25,-15)", (-25.0, -15.0)),
        ("Store below 25 C", (None, 25.0)),
        ("Controlled room temperature", None),
        ("LN2 vapour phase (-196 nominal)", None),
    ],
)
def test_spec_parsing_does_not_assume(text, rng):
    assert parse_spec_range(text) == rng
