"""Evidence packages: reproducible export with hashes; tampering is detected."""

import json

from conftest import clock, principal

from kccs_evidence.assessment import assess_and_store
from kccs_evidence.package import export_package, verify_package


def test_export_and_verify(store, tmp_path):
    a, _ = assess_and_store(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    pkg = export_package(store, principal("T-KAVERI"), a["assessment_id"], tmp_path, "2026-11-08T12:00:00Z")
    res = verify_package(pkg)
    assert res["ok"], res
    src = json.loads((pkg / "source_records.json").read_text(encoding="utf-8"))
    cited = {(c["sheet"], c["record_key"]) for c in src["cited"]}
    assert ("05_SOP_Index", "SOP-KAV-9392 Rev 02") in cited and ("06_Stability_Index", "STB-2738") in cited
    assert all("final_disposition" not in v["allowed_fields"] for v in src["event"])
    assert {c["payload"].get("tenant_code") for c in src["cited"]} == {"T-KAVERI"}


def test_package_is_reproducible(store, tmp_path):
    a, _ = assess_and_store(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    p1 = export_package(store, principal("T-KAVERI"), a["assessment_id"], tmp_path / "1", "2026-11-08T12:00:00Z")
    p2 = export_package(store, principal("T-KAVERI"), a["assessment_id"], tmp_path / "2", "2026-11-08T12:00:00Z")
    assert (p1 / "assessment.json").read_bytes() == (p2 / "assessment.json").read_bytes()
    assert (p1 / "source_records.json").read_bytes() == (p2 / "source_records.json").read_bytes()


def test_tampering_detected(store, tmp_path):
    a, _ = assess_and_store(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    pkg = export_package(store, principal("T-KAVERI"), a["assessment_id"], tmp_path, "2026-11-08T12:00:00Z")
    p = pkg / "assessment.json"
    p.write_text(p.read_text(encoding="utf-8").replace("ABSTAIN_BLOCKING_EVIDENCE_GAPS", "READY_FOR_QA_REVIEW"), encoding="utf-8")
    res = verify_package(pkg)
    assert not res["ok"] and "hash mismatch assessment.json" in res["problems"]
