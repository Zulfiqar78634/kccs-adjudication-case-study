"""Entity resolution using only justified, tenant-scoped evidence.

Never guesses: no fuzzy matching, no cross-tenant lookups, and unattributed
product aliases are not consulted (see reference_facts.product_alias_policy).
Ambiguity is returned as AMBIGUOUS with candidates, not resolved by ranking.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from .access import TenantView
from .config_loader import load_config
from .model import BLOCKING, INFO, REVIEW, Finding, Resolution, norm

PRODUCT_FIELDS = {"gtin": "IDENTIFIER", "internal_sku": "IDENTIFIER", "legacy_code": "IDENTIFIER",
                  "brand_as_labelled": "LABEL", "generic_inn": "MOLECULE"}


def _mapping_hit(view: TenantView, kind: str, value: str) -> dict | None:
    """Latest human mapping decision for this string (tenant-specific beats shared)."""
    hits = [m for m in view.mappings(kind) if norm(m["source_string"]) == norm(value)]
    if not hits:
        return None
    hits.sort(key=lambda m: (m["tenant_code"] is not None, m["recorded_at"]))
    return hits[-1]


def resolve_product(view: TenantView, value: str | None) -> tuple[Resolution, list[Finding]]:
    res = Resolution("PRODUCT", "product", value, "UNRESOLVED")
    if value in (None, ""):
        res.status = "MISSING_INPUT"
        return res, [Finding("PRODUCT_REF_MISSING", BLOCKING, "identity",
                             "Alert carries no product reference; product, specification and stability evidence cannot be selected.",
                             (), "Identify the product from shipment/consignment documents and record it")]
    rows = view.tenant_records("02_Product_Master")
    key = norm(value)
    matches = [(r, f) for r in rows for f in PRODUCT_FIELDS if key and norm(r.get(f)) == key]
    by_row: dict[str, list[str]] = {}
    for r, f in matches:
        by_row.setdefault(r.source_ref, []).append(f)
    findings: list[Finding] = []
    if not by_row:
        m = _mapping_hit(view, "PRODUCT", value)
        target = next((r for r in rows if m and r.source_ref == m["canonical_id"]), None)
        if m and m["decision"] == "APPROVED" and target is not None:
            res.status, res.resolved_id, res.basis = "RESOLVED", target.source_ref, f"APPROVED_MAPPING {m['assertion_id']}"
            res.source_refs = [target.source_ref]
            res.attributes = dict(target.payload)
            return res, [Finding("PRODUCT_RESOLVED_BY_HUMAN_MAPPING", INFO, "identity",
                                 f"Resolved via human-approved mapping {m['assertion_id']} by {m['actor']} at {m['recorded_at']}.",
                                 (target.source_ref,))]
        res.notes.append("No exact match in this tenant's product master. Unattributed product aliases are not consulted (policy QUARANTINE_UNATTRIBUTED).")
        return res, [Finding("PRODUCT_UNRESOLVED", BLOCKING, "identity",
                             f"Product reference {value!r} does not match any identifier, label or INN in this tenant's product master.",
                             (), "Confirm product identity and record a tenant-scoped mapping for approval")]
    res.candidates = [{"id": ref, "matched_fields": fields} for ref, fields in by_row.items()]
    if len(by_row) > 1:
        res.status = "AMBIGUOUS"
        refs = tuple(by_row)
        specs = sorted({str(r.get("storage_spec_text")) for r, _ in matches})
        return res, [Finding("PRODUCT_AMBIGUOUS", BLOCKING, "identity",
                             f"Reference {value!r} matches {len(by_row)} product-master rows for this tenant (storage specs: {specs}). Not resolved by ranking.",
                             refs, "Select the correct product-master row; consider correcting the duplicate at source")]
    ref, fields = next(iter(by_row.items()))
    row = next(r for r, _ in matches if r.source_ref == ref)
    res.resolved_id, res.source_refs, res.attributes = ref, [ref], dict(row.payload)
    kinds = {PRODUCT_FIELDS[f] for f in fields}
    if kinds == {"MOLECULE"}:
        res.status, res.basis = "RESOLVED_PROVISIONAL", "INN_MATCH"
        findings.append(Finding("PRODUCT_MATCHED_BY_INN_ONLY", REVIEW, "identity",
                                "Matched on the international non-proprietary name only; an INN identifies the molecule, not the presentation or strength.",
                                (ref,), "Confirm presentation and strength from shipment documents"))
    else:
        res.status, res.basis = "RESOLVED", "EXACT_" + "+".join(sorted(fields)).upper()
    if row.get("gtin") is None:
        findings.append(Finding("PRODUCT_GTIN_ABSENT_IN_MASTER", INFO, "identity", "Product-master row has no GTIN.", (ref,)))
    return res, findings


def _site_groups(registry) -> set[str]:
    counts = Counter(r.get("code_in_source") for r in registry)
    return {c for c, n in counts.items() if n >= 2}


def resolve_facility(view: TenantView, value: str | None, role: str, knowledge_date: date | None) -> tuple[Resolution, list[Finding]]:
    res = Resolution("FACILITY", role, value, "UNRESOLVED")
    if value in (None, ""):
        res.status = "MISSING_INPUT"
        return res, [Finding(f"{role.upper()}_FACILITY_MISSING", BLOCKING, "identity", f"No {role} facility reference.", ())]
    registry = view.shared_records("03_Facility_Registry")
    groups = _site_groups(registry)
    key = norm(value)
    hits = [r for r in registry if key in (norm(r.get("name_in_source")), norm(r.get("code_in_source")))]
    linked = {r.get("code_in_source") for r in hits if r.get("code_in_source") in groups}
    unlinked = [r for r in hits if r.get("code_in_source") not in groups]
    res.source_refs = [r.source_ref for r in hits]
    findings: list[Finding] = []
    if len(linked) == 1 and not unlinked:
        res.status, res.resolved_id, res.basis = "RESOLVED", next(iter(linked)), "REGISTRY_SITE_CODE"
    elif len(linked) > 1:
        res.status = "AMBIGUOUS"
        res.candidates = [{"id": s} for s in sorted(linked)]
        findings.append(Finding(f"{role.upper()}_FACILITY_AMBIGUOUS", BLOCKING, "identity",
                                f"{value!r} matches registry records for several sites {sorted(linked)}.", tuple(res.source_refs),
                                "Confirm which physical site was involved"))
    else:
        m = _mapping_hit(view, "FACILITY", value)
        if m and m["decision"] == "APPROVED":
            res.status, res.resolved_id, res.basis = "RESOLVED", m["canonical_id"], f"APPROVED_MAPPING {m['assertion_id']}"
        else:
            sites, refs, notes = set(), [], []
            for a in view.alias_observations("FACILITY"):
                if norm(a.get("string_b")) != key and norm(a.get("string_a")) != key:
                    continue
                confirmed = a.get("confirmed_on")
                if knowledge_date and confirmed and date.fromisoformat(confirmed) > knowledge_date:
                    notes.append(f"{a.source_ref} confirmed {confirmed}, after knowledge cutoff; not used")
                    continue
                if a.get("same_real_world_thing") != "Y":
                    notes.append(f"{a.source_ref} asserts NOT the same entity")
                    continue
                other = a.get("string_a") if norm(a.get("string_b")) == key else a.get("string_b")
                if other in groups:
                    sites.add(other)
                    refs.append(a.source_ref)
                    if a.get("comment"):
                        notes.append(f"{a.source_ref}: {a.get('comment')}")
            res.notes.extend(notes)
            if len(sites) == 1:
                res.status, res.resolved_id, res.basis = "RESOLVED_PROVISIONAL", next(iter(sites)), "UNVERIFIED_REVIEWER_ALIAS"
                res.source_refs += refs
                disputed = any("Disputed" in n for n in notes)
                findings.append(Finding(f"{role.upper()}_FACILITY_PROVISIONAL", REVIEW, "identity",
                                        f"{value!r} linked to {res.resolved_id} only by a reviewer alias observation (not authoritative)"
                                        + ("; the alias is disputed by the TMS owner" if disputed else "") + ".",
                                        tuple(refs), "Approve or reject the facility mapping"))
            elif len(sites) > 1:
                res.status = "AMBIGUOUS"
                res.candidates = [{"id": s} for s in sorted(sites)]
                findings.append(Finding(f"{role.upper()}_FACILITY_AMBIGUOUS", BLOCKING, "identity",
                                        f"Alias observations link {value!r} to several sites {sorted(sites)}.", tuple(refs),
                                        "Confirm which physical site was involved"))
            else:
                findings.append(Finding(f"{role.upper()}_FACILITY_UNRESOLVED", BLOCKING if role == "origin" else REVIEW,
                                        "identity", f"{role} reference {value!r} could not be linked to a registry site.",
                                        tuple(res.source_refs), "Identify the site and record a mapping for approval"))
    if res.resolved_id:
        site_rows = [r for r in registry if r.get("code_in_source") == res.resolved_id]
        tzs = sorted({r.get("timezone_in_source") for r in site_rows})
        countries = sorted({r.get("country") for r in site_rows})
        flags = {f["site"]: f for f in load_config("reference_facts.json")["facility_timezone_flags"]}
        flag = flags.get(res.resolved_id)
        res.attributes = {"country": countries[0] if len(countries) == 1 else None, "timezones_in_source": tzs,
                          "timezone": tzs[0] if len(tzs) == 1 else None,
                          "timezone_trusted": len(tzs) == 1 and flag is None,
                          "registry_records": [r.source_ref for r in site_rows],
                          "gmp_licences_in_source": sorted({r.get("gmp_licence_ref") for r in site_rows if r.get("gmp_licence_ref")})}
        if flag:
            findings.append(Finding("FACILITY_TIMEZONE_" + flag["status"], REVIEW, "policy",
                                    f"{res.resolved_id}: {flag['issue']}", (flag["source"],)))
        if len(res.attributes["gmp_licences_in_source"]) > 1:
            findings.append(Finding("FACILITY_GMP_LICENCE_CONFLICT", INFO, "identity",
                                    f"{res.resolved_id} carries {len(res.attributes['gmp_licences_in_source'])} different GMP licence refs across source systems.",
                                    tuple(res.attributes["registry_records"])))
    return res, findings


def resolve_carrier(view: TenantView, value: str | None, knowledge_date: date | None) -> tuple[Resolution, list[Finding]]:
    res = Resolution("CARRIER", "carrier", value, "UNRESOLVED")
    if value in (None, ""):
        res.status = "MISSING_INPUT"
        return res, [Finding("CARRIER_REF_MISSING", REVIEW, "liability", "No carrier reference.", ())]
    contracts = view.shared_records("04_Carrier_Contracts")
    key = norm(value)

    def names(c):
        return {norm(c.get("counterparty_legal_entity"))} | {norm(n) for n in str(c.get("names_seen_on_documents") or "").split("|")}

    hits = [c for c in contracts if key in names(c)]
    basis = "CONTRACT_NAME_MATCH"
    if not hits:
        m = _mapping_hit(view, "CARRIER", value)
        if m and m["decision"] == "APPROVED":
            hits, basis = [c for c in contracts if c.record_key == m["canonical_id"]], f"APPROVED_MAPPING {m['assertion_id']}"
        else:
            entities, refs = set(), []
            for a in view.alias_observations("CARRIER"):
                if a.get("same_real_world_thing") != "Y" or key not in (norm(a.get("string_a")), norm(a.get("string_b"))):
                    continue
                confirmed = a.get("confirmed_on")
                if knowledge_date and confirmed and date.fromisoformat(confirmed) > knowledge_date:
                    res.notes.append(f"{a.source_ref} confirmed {confirmed}, after knowledge cutoff; not used")
                    continue
                entities |= {norm(a.get("string_a")), norm(a.get("string_b"))}
                refs.append(a.source_ref)
            hits = [c for c in contracts if names(c) & entities]
            basis = "UNVERIFIED_REVIEWER_ALIAS"
            res.source_refs += refs
    res.source_refs += [c.source_ref for c in hits]
    if len(hits) == 1:
        c = hits[0]
        res.status = "RESOLVED" if basis != "UNVERIFIED_REVIEWER_ALIAS" else "RESOLVED_PROVISIONAL"
        res.resolved_id, res.basis = c.record_key, basis
        res.attributes = {k: c.get(k) for k in ("counterparty_legal_entity", "effective_from", "effective_to", "governing_law",
                                                 "cold_chain_clause", "liability_cap", "claim_window_days", "amendment_docs")}
        sev = REVIEW if res.status == "RESOLVED_PROVISIONAL" else INFO
        return res, [Finding("CARRIER_RESOLVED" if sev == INFO else "CARRIER_PROVISIONAL", sev, "liability",
                             f"Carrier {value!r} -> {c.get('counterparty_legal_entity')} ({c.record_key}) by {basis}.",
                             tuple(res.source_refs), None if sev == INFO else "Approve carrier legal-entity mapping")]
    if len(hits) > 1:
        res.status = "AMBIGUOUS"
        res.candidates = [{"id": c.record_key, "legal_entity": c.get("counterparty_legal_entity")} for c in hits]
        return res, [Finding("CARRIER_AMBIGUOUS", REVIEW, "liability",
                             f"{value!r} matches several legal entities/contracts {[c.record_key for c in hits]}; subsidiaries have different claim windows.",
                             tuple(res.source_refs), "Confirm the contracting legal entity for this leg")]
    return res, [Finding("CARRIER_UNRESOLVED", REVIEW, "liability",
                         f"Carrier {value!r} not found in the contract index or carrier aliases.", (),
                         "Identify the carrier legal entity")]
