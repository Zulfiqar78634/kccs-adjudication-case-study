"""Stability evidence: ownership, presentation, readability, relevance, missingness.

* Ownership comes from 06_Stability_Index.tenant_code, never from file_path_text
  (00_README!R38). A referenced study owned by another tenant is unusable and
  its contents are not disclosed.
* Absence from the index is not evidence of absence: the index covers ~60% of
  the repository (00_README!R35).
* Unreadable/partial studies are never relied on, even where the index row has
  permitted_excursion_text populated.
"""
from __future__ import annotations

import re
from typing import Any

from .access import TenantView
from .config_loader import load_config
from .model import BLOCKING, INFO, REVIEW, Finding, Resolution, norm
from .signals import evaluate_limit, parse_limit


def presentations(text: str | None) -> set[str]:
    """Explicit presentation words win over brand-derived tokens.

    A study titled 'Glucodyne SoloJet — vial' is a vial study even though the
    brand name implies a pen; brand-derived tokens only apply when no explicit
    presentation word is present.
    """
    t = norm(text)
    explicit, brand = set(), set()
    for tok in load_config("reference_facts.json")["presentation_lexicon"]["tokens"]:
        if re.search(rf"(?<![a-z]){re.escape(tok['token'])}(?![a-z])", t):
            (brand if tok.get("brand_derived") else explicit).add(tok["presentation"])
    return explicit or brand


def study_presentations(text: str | None) -> set[str]:
    """A study's presentation is stated in its suffix ('… — vial', '… (pen)'); the prefix is the product name.

    'Rinvatec PFS 40 — vial' is a vial study even though the product name contains 'PFS' (EXC-110497).
    """
    raw = str(text or "")
    if "—" in raw:
        suffix = presentations(raw.rsplit("—", 1)[1])
        if suffix:
            return suffix
    for paren in reversed(re.findall(r"\(([^)]*)\)", raw)):
        found = presentations(paren)
        if found:
            return found
    return presentations(raw)


def _name_keys(product: dict[str, Any]) -> set[str]:
    keys = set()
    brand = norm(product.get("brand_as_labelled"))
    if brand:
        first = re.split(r"[^a-z]+", brand)[0]
        if len(first) >= 4:
            keys.add(first)
    inn = norm(product.get("generic_inn"))
    if inn:
        keys.add(inn.split()[0])
    return keys


def assess_study(study, product: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Admissibility checks for one indexed study (already known to be this tenant's)."""
    reasons, notes = [], []
    prod_pres, study_pres = presentations(product.get("brand_as_labelled")), study_presentations(study.get("product_text_as_written"))
    presentation_verified = bool(prod_pres and study_pres and prod_pres & study_pres)
    if prod_pres and study_pres and not (prod_pres & study_pres):
        reasons.append(f"presentation mismatch: product {sorted(prod_pres)} vs study {sorted(study_pres)}")
    elif not presentation_verified:
        notes.append("presentation not stated on " + ("the product label" if not prod_pres else "the study") + "; match unverified")
    keys = _name_keys(product)
    if keys and not any(k in norm(study.get("product_text_as_written")) for k in keys):
        reasons.append("study product text does not name this product")
    readable = str(study.get("readable") or "")
    if readable.startswith("N"):
        reasons.append(f"unreadable ({readable})")
        if study.get("permitted_excursion_text"):
            notes.append("index row carries permitted_excursion_text although the study is unreadable; not relied on")
    elif readable.startswith("Partial"):
        reasons.append(f"partially readable ({readable}); requires human verification")
    if not study.get("permitted_excursion_text") and not readable.startswith("N"):
        reasons.append(f"study type '{study.get('study_type')}' does not establish an excursion limit")
    folder = str(study.get("file_path_text") or "").split("/")
    if len(folder) > 2 and folder[2] not in (tenant, "Shared"):
        notes.append(f"file path folder '{folder[2]}' differs from owner {tenant}; ownership taken from tenant_code")
    elif len(folder) > 2 and folder[2] == "Shared":
        notes.append("filed under a shared folder; ownership taken from tenant_code")
    return {"ref": study.source_ref, "study_ref": study.record_key, "product_text": study.get("product_text_as_written"),
            "study_type": study.get("study_type"), "readable": study.get("readable"),
            "permitted_excursion_text": study.get("permitted_excursion_text") if not readable.startswith("N") else None,
            "admissible": not reasons, "presentation_verified": presentation_verified,
            "rejection_reasons": reasons, "notes": notes}


def assess_stability(view: TenantView, product: Resolution, ev: dict[str, Any], spec, fw) -> tuple[dict[str, Any], list[Finding]]:
    out: dict[str, Any] = {"status": "NOT_EVALUATED", "referenced": None, "unreferenced_candidates": [], "limit_checks": []}
    if not product.usable:
        out["status"] = "BLOCKED_PRODUCT_UNRESOLVED"
        return out, [Finding("STABILITY_NOT_SELECTABLE", BLOCKING, "stability",
                             "Stability evidence cannot be selected without a resolved product.", ())]
    p = product.attributes
    findings: list[Finding] = []
    own = {s.record_key: s for s in view.tenant_records("06_Stability_Index")}
    ref = p.get("stability_study_ref")
    master_limit = parse_limit(p.get("permitted_excursion_text"))
    out["product_master_permitted_excursion"] = master_limit
    if not ref:
        findings.append(Finding("STABILITY_REF_MISSING", BLOCKING, "stability",
                                "Product master carries no stability_study_ref.", (product.resolved_id,),
                                "Locate the governing stability study"))
    elif ref not in own:
        # Do not look the reference up under other tenants; that would itself be cross-tenant access.
        out["referenced"] = {"study_ref": ref, "in_tenant_index": False}
        findings.append(Finding("STABILITY_REF_NOT_IN_TENANT_INDEX", BLOCKING, "stability",
                                f"{ref} is not in this tenant's stability index. The index covers ~60% of the repository, so absence is not evidence the study does not exist.",
                                (product.resolved_id, "00_README!R35"), "Retrieve the study from the repository and index it"))
    else:
        a = assess_study(own[ref], p, view.tenant)
        out["referenced"] = a
        if not a["admissible"]:
            findings.append(Finding("STABILITY_REFERENCED_STUDY_INADMISSIBLE", BLOCKING, "stability",
                                    f"Product master references {ref}, which cannot be relied on: {'; '.join(a['rejection_reasons'])}.",
                                    (product.resolved_id, a["ref"]), "Identify the study for this presentation"))
        for n in a["notes"]:
            findings.append(Finding("STABILITY_PATH_OR_INDEX_NOTE", INFO, "stability", f"{ref}: {n}", (a["ref"],)))
    keys = _name_keys(p)
    for s in own.values():
        if s.record_key == ref or not any(k in norm(s.get("product_text_as_written")) for k in keys):
            continue
        out["unreferenced_candidates"].append(assess_study(s, p, view.tenant))
    admissible_ref = out["referenced"] if out["referenced"] and out["referenced"].get("admissible") else None
    admissible_cands = [c for c in out["unreferenced_candidates"] if c["admissible"]]
    basis = None
    if admissible_ref:
        out["status"], basis = "REFERENCED_STUDY_ADMISSIBLE", admissible_ref
    elif admissible_cands:
        out["status"] = "CANDIDATE_ONLY"
        basis = admissible_cands[0] if len(admissible_cands) == 1 else None
        findings.append(Finding("STABILITY_UNREFERENCED_CANDIDATE", REVIEW, "stability",
                                f"{len(admissible_cands)} admissible study(ies) for this product/presentation exist in the tenant index but are not referenced by the product master: {[c['study_ref'] for c in admissible_cands]}.",
                                tuple(c["ref"] for c in admissible_cands), "QA to confirm the study and correct the product-master reference"))
    else:
        out["status"] = "NO_ADMISSIBLE_STUDY"
        findings.append(Finding("STABILITY_NO_ADMISSIBLE_STUDY", BLOCKING, "stability",
                                "No admissible stability study found in the tenant index for this product and presentation.",
                                (product.resolved_id,), "Retrieve or commission stability evidence"))
    if basis:
        if not basis.get("presentation_verified"):
            findings.append(Finding("STABILITY_PRESENTATION_UNVERIFIED", REVIEW, "stability",
                                    f"{basis['study_ref']}: presentation is not stated on both the product label and the study, so the match is unverified.",
                                    (product.resolved_id, basis["ref"]), "Confirm the study covers this presentation"))
        study_limit = parse_limit(basis["permitted_excursion_text"])
        out["limit_checks"].append({"source": basis["study_ref"], **evaluate_limit(study_limit, ev, spec, fw)})
        if master_limit["kind"] not in ("ABSENT", "REFER_QA") and master_limit.get("text") and norm(master_limit["text"]) != norm(study_limit.get("text")):
            same_kind = master_limit["kind"] == study_limit["kind"] and all(
                master_limit.get(k) == study_limit.get(k) for k in ("hours", "ceiling_c", "threshold_c"))
            if not same_kind:
                findings.append(Finding("STABILITY_MASTER_VS_STUDY_CONFLICT", BLOCKING, "stability",
                                        f"Product master permitted excursion {master_limit['text']!r} disagrees with {basis['study_ref']} {study_limit.get('text')!r}.",
                                        (product.resolved_id, basis["ref"]), "QA to decide which governs and correct the other"))
    if master_limit["kind"] == "REFER_QA":
        findings.append(Finding("PRODUCT_MASTER_ALLOWANCE_IS_REFER_QA", REVIEW, "stability",
                                "Product master permitted excursion says 'Refer QA'; that is not an allowance (cf. EXC-110574).", (product.resolved_id,)))
    out["limit_checks"].append({"source": "product_master", **evaluate_limit(master_limit, ev, spec, fw)})
    for chk in out["limit_checks"]:
        if chk["status"] == "INDETERMINATE_FIRMWARE_UNCERTAINTY":
            findings.append(Finding("LIMIT_CHECK_FLIPS_WITHIN_FIRMWARE_BAND", BLOCKING, "firmware",
                                    f"Against {chk['source']}, the conclusion changes within the firmware under-reporting band {chk['firmware_band_c']}.",
                                    (), "Treat temperature as uncertain; consider lab test or alternative logger evidence"))
    return out, findings
