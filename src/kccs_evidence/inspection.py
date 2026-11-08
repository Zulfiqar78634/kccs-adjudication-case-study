"""Reproducible workbook inspection and data-quality report.

Reads the workbook through the same ingestion path as the kernel and writes
artifacts/data_quality/report.md + report.json. Nothing is cleaned; findings
distinguish MISSING (blank), INVALID (unparseable), CONFLICTING (sources
disagree) and UNKNOWN (not determinable from the pack).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from .model import norm
from .signals import parse_spec_range
from .sources import SourceSnapshot, load_workbook_snapshot
from .stability import presentations, study_presentations
from .temporal import parse_pack_utc

QUESTIONS_ANSWERABILITY = {
    "1": ("PARTIAL", "Revision windows and site scope are in 05; overlaps are detected. Acceptance-limit content and annexures are not in the pack. T-VIRENT has no 'Temperature Excursion Management' document indexed."),
    "2": ("PARTIAL", "06 covers ~60% of the repository; presentation/readability/relevance can be checked. Cumulative-over-shelf-life needs batch history, which is absent."),
    "3": ("PARTIAL", "Only the 420-row stratified sample; lane strings are inconsistent; equipment (reefer unit) is absent; prior outcomes are latest-value only."),
    "4": ("PARTIAL", "04 gives legal entities, windows, clauses; amendments 'filed separately' are absent; leg-level carrier entity is not in 01."),
    "5": ("PARTIAL", "gateway_gap_min and interpolated flags exist; gap position relative to the excursion and the raw series are absent."),
    "6": ("NO", "No stable physical-excursion key; shipment_ref is unique per row in 01; duplicates (EXC-110532) cannot be reproduced."),
    "7": ("NO", "BMS has no tenant tags; the TMS room-to-consignment mapping is not in the pack."),
    "8": ("NO", "No batch identifier or batch exposure history in any tab."),
    "9": ("YES (8 tenants)", "12_Tenant_Constraints.who_signs_a_disposition; 26 tenants not listed."),
    "10": ("PARTIAL", "Windows per market in 13!R22 and on reportable rows in 01; notifiability criteria and the US state calendar are absent."),
    "11": ("PARTIAL", "Prior outcomes exist for opened cases in the sample; reasoning only for the 24 in 09; reopened cases hold only the latest value."),
    "12": ("NO (today)", "The pack has no knowledge-time history; this is what the kernel's immutable store and packages are for."),
}


def _rows(snap: SourceSnapshot, sheet: str):
    return [r for r in snap.records if r.sheet == sheet]


def _column_profile(snap: SourceSnapshot, sheet: str) -> list[dict[str, Any]]:
    recs = _rows(snap, sheet)
    out = []
    for col in snap.sheet_columns[sheet]:
        vals = [r.payload.get(col) for r in recs]
        present = [v for v in vals if v not in (None, "")]
        types = Counter(type(v).__name__ for v in present)
        out.append({"column": col, "rows": len(vals), "missing": len(vals) - len(present),
                    "distinct": len({str(v) for v in present}), "types": dict(types)})
    return out


def inspect(workbook: str | Path) -> dict[str, Any]:
    snap = load_workbook_snapshot(workbook)
    rep: dict[str, Any] = {"workbook": {"file": snap.file_name, "sha256": snap.file_sha256, "extract_date": snap.extract_date,
                                        "snapshot_id": snap.snapshot_id}}
    rep["sheets"] = [{"sheet": s, "data_rows": len(_rows(snap, s)), "columns": len(snap.sheet_columns[s])} for s in snap.sheet_columns]
    rep["columns"] = {s: _column_profile(snap, s) for s in snap.sheet_columns if s not in ("00_README", "13_Volume_And_Cost")}
    ev, pm, fac = _rows(snap, "01_Excursion_Events"), _rows(snap, "02_Product_Master"), _rows(snap, "03_Facility_Registry")
    cc, sop, stb = _rows(snap, "04_Carrier_Contracts"), _rows(snap, "05_SOP_Index"), _rows(snap, "06_Stability_Index")
    alias, ql, ovr = _rows(snap, "07_Alias_Observations"), _rows(snap, "08_Reviewer_Queue_Log"), _rows(snap, "09_Override_Reasons")

    # ---- strata (00_README!R28) ----
    reopened = {e.record_key for e in ev if e.get("reopened_later") == "Y"}
    override_ids = {o.record_key for o in ovr}
    late = {e.record_key for e in ev if e.get("reported_within_window") == "N"}
    storm = {e.record_key for e in ev if "chiller controller failure" in str(e.get("notes") or "")}
    rep["strata"] = {"reopened_later_Y": len(reopened), "bulletin_note": sum("TT-CB-114" in str(e.get("notes") or "") for e in ev),
                     "override_reasons_rows": len(override_ids), "override_ids_present_in_01": len(override_ids & {e.record_key for e in ev}),
                     "late_notifications": len(late), "late_and_override": len(late & override_ids),
                     "storm_INC2502_rows": len(storm), "storm_and_override": len(storm & override_ids),
                     "reopened_fw": dict(Counter(e.get("logger_fw") for e in ev if e.record_key in reopened)),
                     "note": "Stratified evidence pack (00_README!R28): ratios inside 01 are NOT population ratios."}

    # ---- identifiers & timestamps ----
    gtins = [r.get("gtin") for r in pm if r.get("gtin") is not None]
    rep["identifiers"] = {"gtin_values": len(gtins), "gtin_all_strings": all(isinstance(g, str) for g in gtins),
                          "gtin_leading_zero": sum(str(g).startswith("0") for g in gtins),
                          "event_product_refs_numeric_type": sum(isinstance(e.get("product_ref_as_received"), (int, float)) for e in ev)}
    lat = defaultdict(list)
    bad_ts = []
    for e in ev:
        try:
            a, s = parse_pack_utc(e.get("alert_ts_utc")), parse_pack_utc(e.get("excursion_start_utc"))
            lat[e.get("source_system")].append((a - s).total_seconds() / 60)
        except ValueError:
            bad_ts.append(e.record_key)
    rep["timestamps"] = {"format": "YYYY-MM-DD HH:MM, no zone designator; UTC per 00_README!R31", "unparseable": bad_ts,
                         "detection_latency_min_by_source": {k: {"n": len(v), "min": min(v), "median": sorted(v)[len(v) // 2], "max": max(v)} for k, v in sorted(lat.items())}}
    # README!R41 reconciliation: local_end - offset == alert + days_to_disposition
    evmap = {e.record_key: e for e in ev}
    recon = Counter()
    worst = []
    for q in ql:
        e = evmap.get(q.get("case_ref"))
        if not e:
            recon["case_not_in_01"] += 1
            continue
        sign = -1 if str(q.get("reviewer_utc_offset")).startswith("-") else 1
        hh, mm = str(q.get("reviewer_utc_offset"))[1:].split(":")
        end_utc = parse_pack_utc(q.get("local_end")) - sign * timedelta(hours=int(hh), minutes=int(mm))
        expect = parse_pack_utc(e.get("alert_ts_utc")) + timedelta(days=float(e.get("days_to_disposition") or 0))
        diff = abs((end_utc - expect).total_seconds()) / 60
        recon["within_15_min" if diff <= 15 else "outside_15_min"] += 1
        worst.append((diff, q.record_key, q.get("case_ref")))
    worst.sort(reverse=True)
    rep["queue_log_reconciliation"] = {"counts": dict(recon), "largest_differences_min": [(round(d, 1), a, b) for d, a, b in worst[:5]],
                                       "note": "days_to_disposition has 2-decimal precision (~14 min), so a 15-minute tolerance is used."}

    # ---- product joins ----
    by_tenant = defaultdict(list)
    for r in pm:
        by_tenant[r.tenant_code].append(r)
    fields = ("gtin", "internal_sku", "legacy_code", "brand_as_labelled", "generic_inn")
    pj = Counter()
    cross_only = []
    for e in ev:
        ref = e.get("product_ref_as_received")
        if ref in (None, ""):
            pj["missing"] += 1
            continue
        own = {r.source_ref for r in by_tenant[e.tenant_code] for f in fields if norm(r.get(f)) == norm(ref)}
        other = {r.source_ref for t, rs in by_tenant.items() if t != e.tenant_code for r in rs for f in fields if norm(r.get(f)) == norm(ref)}
        if len(own) == 1:
            pj["exact_single_own_tenant"] += 1
        elif len(own) > 1:
            pj["ambiguous_own_tenant"] += 1
        elif other:
            pj["matches_other_tenants_only"] += 1
            cross_only.append((e.record_key, e.tenant_code, ref))
        else:
            pj["no_master_match"] += 1
    gtin_tenants = defaultdict(set)
    for r in pm:
        if r.get("gtin"):
            gtin_tenants[r.get("gtin")].add(r.tenant_code)
    dup_sku = Counter((r.tenant_code, r.get("internal_sku")) for r in pm if r.get("internal_sku"))
    rep["product_joins"] = {"event_product_ref": dict(pj), "examples_other_tenant_only": cross_only[:8],
                            "gtins_shared_across_tenants": {g: sorted(t) for g, t in gtin_tenants.items() if len(t) > 1},
                            "duplicate_sku_within_tenant": {f"{k[0]}|{k[1]}": n for k, n in dup_sku.items() if n > 1},
                            "product_alias_rows_without_tenant": sum(a.get("entity_kind") == "PRODUCT" for a in alias)}

    # ---- facilities ----
    groups = {c for c, n in Counter(r.get("code_in_source") for r in fac).items() if n >= 2}
    names = {norm(r.get("name_in_source")): r.get("code_in_source") for r in fac} | {norm(r.get("code_in_source")): r.get("code_in_source") for r in fac}
    fj = Counter()
    for e in ev:
        for role in ("origin_ref_as_received", "dest_ref_as_received"):
            code = names.get(norm(e.get(role)))
            fj["registry_site_code" if code in groups else "registry_unlinked_code" if code else "not_in_registry"] += 1
    rep["facility_joins"] = {"site_groups": sorted(groups), "records": len(fac), "event_refs": dict(fj),
                             "timezones_by_site": {g: sorted({r.get("timezone_in_source") for r in fac if r.get("code_in_source") == g}) for g in sorted(groups)},
                             "alias_negative_assertions": [(a.source_ref, a.get("string_a"), a.get("string_b"), a.get("comment")) for a in alias if a.get("same_real_world_thing") == "N"],
                             "alias_comments": dict(Counter(a.get("comment") for a in alias if a.get("comment")))}

    # ---- carriers ----
    def cnames(c):
        return {norm(c.get("counterparty_legal_entity"))} | {norm(n) for n in str(c.get("names_seen_on_documents") or "").split("|")}
    cj = Counter()
    for e in ev:
        hits = [c.record_key for c in cc if norm(e.get("carrier_ref_as_received")) in cnames(c)]
        cj["single_contract" if len(hits) == 1 else "multiple_contracts" if hits else "no_contract_name_match"] += 1
    rep["carrier_joins"] = {"event_refs": dict(cj), "contracts_without_cold_chain_clause": [c.record_key for c in cc if "none" in str(c.get("cold_chain_clause")).lower()],
                            "amendments_filed_separately": [c.record_key for c in cc if "separately" in str(c.get("amendment_docs") or "")],
                            "contracts_expired_before_2026-11-08": [c.record_key for c in cc if str(c.get("effective_to")) < "2026-11-08" and c.get("effective_to") != "evergreen"]}

    # ---- SOP ----
    docs = defaultdict(list)
    for r in sop:
        docs[r.get("doc_id")].append(r)
    overlaps = []
    for d, revs in docs.items():
        for a in revs:
            for b in revs:
                if a.record_key >= b.record_key:
                    continue
                a_to, b_to = a.get("effective_to") or "9999-12-31", b.get("effective_to") or "9999-12-31"
                if a.get("effective_from") < b_to and b.get("effective_from") < a_to:
                    overlaps.append({"doc_id": d, "tenant": a.tenant_code, "title": a.get("title"),
                                     "a": f"{a.get('revision')} [{a.get('effective_from')}, {a.get('effective_to') or 'open'})",
                                     "b": f"{b.get('revision')} [{b.get('effective_from')}, {b.get('effective_to') or 'open'})",
                                     "refs": [a.source_ref, b.source_ref]})
    touching = sum(1 for revs in docs.values() for a in revs for b in revs if a.get("effective_to") and a.get("effective_to") == b.get("effective_from"))
    tem_tenants = {r.tenant_code for r in sop if r.get("title") == "Temperature Excursion Management"}
    rev_order = [d for d, revs in docs.items() if [int(re.sub(r"\D", "", x.get("revision"))) for x in sorted(revs, key=lambda x: x.get("effective_from"))]
                 != sorted(int(re.sub(r"\D", "", x.get("revision"))) for x in revs)]
    rep["sop"] = {"documents": len(docs), "revisions": len(sop), "overlapping_pairs": overlaps,
                  "docs_with_overlap": sorted({o["doc_id"] for o in overlaps}),
                  "adjacent_handover_pairs_(to==next_from)": touching,
                  "docs_with_multiple_open_ended": [d for d, revs in docs.items() if sum(not x.get("effective_to") for x in revs) > 1],
                  "revision_number_not_in_date_order": rev_order,
                  "tenants_without_TEM_document": sorted({e.tenant_code for e in ev} - tem_tenants),
                  "formats": dict(Counter(r.get("format") for r in sop)), "languages": dict(Counter(r.get("language") for r in sop)),
                  "applies_to_values": dict(Counter(r.get("applies_to_facilities_text") for r in sop))}

    # ---- stability ----
    idx = {s.record_key: s for s in stb}
    refs = [(r.source_ref, r.tenant_code, r.get("stability_study_ref"), r.get("brand_as_labelled")) for r in pm]
    st = Counter()
    mism = []
    for src, tenant, ref, brand in refs:
        if not ref:
            st["master_ref_blank"] += 1
        elif ref not in idx:
            st["master_ref_not_indexed"] += 1
        elif idx[ref].tenant_code != tenant:
            st["master_ref_owned_by_other_tenant"] += 1
        else:
            st["master_ref_indexed_same_tenant"] += 1
            pp, sp = presentations(brand), study_presentations(idx[ref].get("product_text_as_written"))
            if pp and sp and not (pp & sp):
                mism.append({"product_row": src, "tenant": tenant, "study": ref, "product": brand, "study_text": idx[ref].get("product_text_as_written")})
    rep["stability"] = {"index_rows": len(stb), "master_refs": dict(st), "presentation_mismatches_master_to_study": mism,
                        "path_folder_differs_from_owner": [(s.record_key, s.tenant_code, s.get("file_path_text")) for s in stb
                                                           if s.get("file_path_text").split("/")[2] not in (s.tenant_code, "Shared")],
                        "shared_folder": [s.record_key for s in stb if "/Shared/" in s.get("file_path_text")],
                        "readable": dict(Counter(s.get("readable") for s in stb)),
                        "unreadable_with_permitted_text": [s.record_key for s in stb if str(s.get("readable")).startswith("N") and s.get("permitted_excursion_text")],
                        "no_excursion_limit_by_design": sum(1 for s in stb if not s.get("permitted_excursion_text")),
                        "indexed_by": dict(Counter(s.get("indexed_by") for s in stb))}

    # ---- spec text vs master ----
    rep["spec"] = {"spec_text_variants_in_01": len({e.get("spec_text_as_received") for e in ev}),
                   "unparseable_without_assumption": sorted({e.get("spec_text_as_received") for e in ev if parse_spec_range(e.get("spec_text_as_received")) is None})}
    rep["reviewer_questions"] = {q: {"answerable_from_pack": a, "why": w} for q, (a, w) in QUESTIONS_ANSWERABILITY.items()}
    rep["notification_rows"] = dict(Counter(f"{e.tenant_code}|{e.get('reg_window_hours')}h|within={e.get('reported_within_window')}" for e in ev if e.get("regulator_reportable") == "Y"))
    rep["semantics_warnings"] = [
        "01.rules_engine_recommendation holds the recommendation assistant's draft since 2024 (00_README!R45), not a rule output.",
        "Rows with case_opened=N were closed by the rules engine without review and were never audited (00_README!R36): not ground truth.",
        "alert_ts_utc is receipt time; excursion_start_utc is when product left range; the regulatory clock runs from the alert (00_README!R43).",
        "min/max/mean/duration are aggregates, not a series; raw series is retained only 30 days by SYS-01 (11!R2).",
        "07 aliases are unverified, platform-wide and untenanted (00_README!R18).",
    ]
    return rep


def write_report(rep: dict[str, Any], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    L = [f"# Workbook inspection and data-quality report", "",
         f"Generated by `kccs-evidence inspect` from `{rep['workbook']['file']}` (sha256 `{rep['workbook']['sha256'][:16]}…`, extract {rep['workbook']['extract_date']}).",
         "Machine-readable version: `report.json`. **The 420 alerts are a stratified evidence pack; no ratio below is a population estimate.**", "",
         "## Sheets", "", "| sheet | data rows | columns |", "|---|---|---|"]
    L += [f"| {s['sheet']} | {s['data_rows']} | {s['columns']} |" for s in rep["sheets"]]
    L += ["", "## Columns with missing values", "", "| sheet | column | missing / rows | distinct | types |", "|---|---|---|---|---|"]
    for sheet, cols in rep["columns"].items():
        for c in cols:
            if c["missing"]:
                L.append(f"| {sheet} | {c['column']} | {c['missing']} / {c['rows']} | {c['distinct']} | {c['types']} |")
    L += ["", "## Strata check (00_README!R28)", "", "```json", json.dumps(rep["strata"], indent=1, ensure_ascii=False), "```",
          "", "## Identifiers and timestamps", "", "```json", json.dumps({"identifiers": rep["identifiers"], "timestamps": rep["timestamps"],
                                                                        "queue_log_reconciliation": rep["queue_log_reconciliation"]}, indent=1, ensure_ascii=False, default=str), "```"]
    for key, title in (("product_joins", "Product joins (tenant-scoped exact match)"), ("facility_joins", "Facility joins"),
                       ("carrier_joins", "Carrier joins"), ("stability", "Stability index"), ("spec", "Specification text")):
        L += ["", f"## {title}", "", "```json", json.dumps(rep[key], indent=1, ensure_ascii=False, default=str), "```"]
    s = rep["sop"]
    L += ["", "## SOP index", "", f"- {s['documents']} controlled documents, {s['revisions']} revisions; {len(s['overlapping_pairs'])} overlapping revision pairs across {len(s['docs_with_overlap'])} documents.",
          f"- {s['adjacent_handover_pairs_(to==next_from)']} hand-overs where effective_to equals the next effective_from → evidence for half-open [from, to) intervals.",
          f"- Documents with more than one open-ended revision: {s['docs_with_multiple_open_ended']}.",
          f"- Revision numbers not in effective-date order: {s['revision_number_not_in_date_order']}.",
          f"- Tenants with events but no 'Temperature Excursion Management' document: {s['tenants_without_TEM_document']}.", "",
          "| doc | tenant | title | revision A | revision B | rows |", "|---|---|---|---|---|---|"]
    L += [f"| {o['doc_id']} | {o['tenant']} | {o['title']} | {o['a']} | {o['b']} | {', '.join(o['refs'])} |" for o in s["overlapping_pairs"]]
    L += ["", "## Reviewer questions (10_Reviewer_Questions) answerable from the pack", "", "| Q | answerable | why |", "|---|---|---|"]
    L += [f"| {q} | {v['answerable_from_pack']} | {v['why']} |" for q, v in rep["reviewer_questions"].items()]
    L += ["", "## Notification rows flagged reportable in 01 (tenant | window | within)", "", "```json", json.dumps(rep["notification_rows"], indent=1), "```",
          "", "## Semantics warnings", ""] + [f"- {w}" for w in rep["semantics_warnings"]]
    path = out / "report.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path
