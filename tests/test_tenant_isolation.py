"""Tenant isolation: enforced before retrieval, across resolution, stability, packages and audit."""
import pytest

from conftest import clock, principal
from kccs_evidence.access import TenantAccessDenied, TenantView
from kccs_evidence.assessment import build_assessment
from kccs_evidence.package import export_package
from kccs_evidence.resolution import resolve_product


def test_cross_tenant_view_is_denied_and_audited(store):
    with pytest.raises(TenantAccessDenied):
        TenantView(store, principal("T-PINNACLE"), "T-MERIDIAN", clock=clock)
    denials = [a for a in store.audit_events("TENANT_VIEW_OPEN") if a["outcome"] == "DENIED"]
    assert denials and denials[-1]["tenant_code"] == "T-MERIDIAN"


def test_cross_tenant_assessment_denied(store, snapshot):
    meridian_event = next(r.record_key for r in snapshot.records if r.sheet == "01_Excursion_Events" and r.tenant_code == "T-MERIDIAN")
    with pytest.raises(TenantAccessDenied):
        build_assessment(store, principal("T-PINNACLE"), "T-MERIDIAN", meridian_event, clock=clock)


def test_event_of_other_tenant_is_not_found_rather_than_revealed(store):
    view = TenantView(store, principal("T-PINNACLE"), "T-PINNACLE", clock=clock)
    with pytest.raises(KeyError):
        view.event("EXC-107133")                 # a T-KAVERI event


def test_same_gtin_under_multiple_tenants_resolves_within_tenant(store):
    # 08901234500035 is carried by T-VIRENT, T-NORDIA, T-PINNACLE and T-KAVERI product-master rows.
    rows = {}
    for tenant in ("T-KAVERI", "T-PINNACLE", "T-VIRENT", "T-NORDIA"):
        res, _ = resolve_product(TenantView(store, principal(tenant), tenant, clock=clock), "08901234500035")
        assert res.status == "RESOLVED"
        rows[tenant] = res.resolved_id
    assert rows["T-KAVERI"] == "02_Product_Master!R57" and rows["T-PINNACLE"] == "02_Product_Master!R28"
    assert len(set(rows.values())) == 4
    assert rows["T-KAVERI"] != rows["T-PINNACLE"]


def test_identifier_known_only_to_another_tenant_is_unresolved(store):
    # GTIN 08901234507719 (Somavance) exists only in T-AURA's master.
    res, findings = resolve_product(TenantView(store, principal("T-KAVERI"), "T-KAVERI", clock=clock), "08901234507719")
    assert res.status == "UNRESOLVED" and res.candidates == []
    assert "T-AURA" not in str(res.to_dict()) and "02_Product_Master!R5" not in str(res.to_dict())


def test_product_aliases_are_quarantined_for_every_tenant(store):
    view = TenantView(store, principal("T-VIRENT"), "T-VIRENT", clock=clock)
    with pytest.raises(TenantAccessDenied):
        view.alias_observations("PRODUCT")
    res, _ = resolve_product(view, "ins glargine kbx")   # an alias string in 07, not in T-VIRENT master
    assert res.status == "UNRESOLVED"


def test_stability_ownership_from_tenant_code_not_path(store):
    # STB-4764 is owned by T-MERIDIAN but filed under /Stability/T-PINNACLE/; STB-6586 is the reverse.
    pin = {r.record_key: r for r in TenantView(store, principal("T-PINNACLE"), "T-PINNACLE", clock=clock).tenant_records("06_Stability_Index")}
    mer = {r.record_key: r for r in TenantView(store, principal("T-MERIDIAN"), "T-MERIDIAN", clock=clock).tenant_records("06_Stability_Index")}
    assert "STB-4764" not in pin and "/T-PINNACLE/" in mer["STB-4764"].get("file_path_text")
    assert "STB-6586" in pin and "/T-MERIDIAN/" in pin["STB-6586"].get("file_path_text")


def test_package_export_denied_for_other_tenant(store, tmp_path):
    a = build_assessment(store, principal("T-KAVERI"), "T-KAVERI", "EXC-107133", clock=clock)
    store.put_assessment(a, "2026-11-08T12:00:00Z")
    with pytest.raises(TenantAccessDenied):
        export_package(store, principal("T-PINNACLE"), a["assessment_id"], tmp_path, "2026-11-08T12:00:00Z")


def test_lane_history_never_includes_other_tenants(store, snapshot):
    for r in [r for r in snapshot.records if r.sheet == "01_Excursion_Events" and r.tenant_code in ("T-PINNACLE", "T-MERIDIAN")][:20]:
        a = build_assessment(store, principal(r.tenant_code), r.tenant_code, r.record_key, knowledge_cutoff="2026-09-14T23:59:00Z", clock=clock)
        tenants = {next(x.tenant_code for x in snapshot.records if x.record_key == h["event_id"]) for h in a["evidence"]["lane_history"]}
        assert tenants <= {r.tenant_code}


def test_evaluation_only_sheets_not_reachable_from_tenant_view(store):
    view = TenantView(store, principal("T-AURA"), "T-AURA", clock=clock)
    for sheet in ("08_Reviewer_Queue_Log", "09_Override_Reasons"):
        with pytest.raises(TenantAccessDenied):
            view.tenant_records(sheet)
        with pytest.raises(TenantAccessDenied):
            view.shared_records(sheet)
