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
from .resolution import PRODUCT_FIELDS, contract_names, site_groups
from .signals import parse_spec_range
from .sources import KEY_VALUE_SHEETS, SourceRecord, SourceSnapshot, load_workbook_snapshot
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
}  # fmt: skip
SEMANTICS_WARNINGS = (
    "01.rules_engine_recommendation holds the recommendation assistant's draft since 2024 (00_README!R45), not a rule output.",
    "Rows with case_opened=N were closed by the rules engine without review and were never audited (00_README!R36): not ground truth.",
    "alert_ts_utc is receipt time; excursion_start_utc is when product left range; the regulatory clock runs from the alert (00_README!R43).",
    "min/max/mean/duration are aggregates, not a series; raw series is retained only 30 days by SYS-01 (11!R2).",
    "07 aliases are unverified, platform-wide and untenanted (00_README!R18).",
)
# days_to_disposition has 2-decimal precision (~14 min), so queue-log times are reconciled within 15 minutes.
RECONCILIATION_TOLERANCE_MIN = 15
OPEN_ENDED = "9999-12-31"
CONTRACT_EXPIRY_REFERENCE_DATE = "2026-11-08"

Records = list[SourceRecord]


def _rows(snap: SourceSnapshot, sheet: str) -> Records:
    return [r for r in snap.records if r.sheet == sheet]


def _column_profile(snap: SourceSnapshot, sheet: str) -> list[dict[str, Any]]:
    recs = _rows(snap, sheet)
    out = []
    for col in snap.sheet_columns[sheet]:
        vals = [r.payload.get(col) for r in recs]
        present = [v for v in vals if v not in (None, "")]
        types = Counter(type(v).__name__ for v in present)
        out.append({"column": col, "rows": len(vals), "missing": len(vals) - len(present), "distinct": len({str(v) for v in present}), "types": dict(types)})
    return out


def inspect(workbook: str | Path) -> dict[str, Any]:
    """Profile the workbook and return the data-quality report (nothing is cleaned)."""
    snap = load_workbook_snapshot(workbook)
    events, products = _rows(snap, "01_Excursion_Events"), _rows(snap, "02_Product_Master")
    aliases, sop = _rows(snap, "07_Alias_Observations"), _rows(snap, "05_SOP_Index")
    report: dict[str, Any] = {
        "workbook": {"file": snap.file_name, "sha256": snap.file_sha256, "extract_date": snap.extract_date, "snapshot_id": snap.snapshot_id},
        "sheets": [{"sheet": s, "data_rows": len(_rows(snap, s)), "columns": len(snap.sheet_columns[s])} for s in snap.sheet_columns],
        "columns": {s: _column_profile(snap, s) for s in snap.sheet_columns if s not in KEY_VALUE_SHEETS},
        "strata": _strata(events, _rows(snap, "09_Override_Reasons")),
        "identifiers": _identifiers(products, events),
        "timestamps": _timestamps(events),
        "queue_log_reconciliation": _queue_log_reconciliation(_rows(snap, "08_Reviewer_Queue_Log"), events),
        "product_joins": _product_joins(products, events, aliases),
        "facility_joins": _facility_joins(_rows(snap, "03_Facility_Registry"), events, aliases),
        "carrier_joins": _carrier_joins(_rows(snap, "04_Carrier_Contracts"), events),
        "sop": _sop_index(sop, events),
        "stability": _stability_index(_rows(snap, "06_Stability_Index"), products),
        "spec": _spec_text(events),
        "reviewer_questions": {q: {"answerable_from_pack": a, "why": w} for q, (a, w) in QUESTIONS_ANSWERABILITY.items()},
        "notification_rows": dict(
            Counter(f"{e.tenant_code}|{e.get('reg_window_hours')}h|within={e.get('reported_within_window')}" for e in events if e.get("regulator_reportable") == "Y")
        ),
        "semantics_warnings": list(SEMANTICS_WARNINGS),
    }
    return report


# ---------------- strata (00_README!R28), identifiers and timestamps ----------------
def _strata(events: Records, overrides: Records) -> dict[str, Any]:
    event_ids = {e.record_key for e in events}
    reopened = {e.record_key for e in events if e.get("reopened_later") == "Y"}
    override_ids = {o.record_key for o in overrides}
    late = {e.record_key for e in events if e.get("reported_within_window") == "N"}
    storm = {e.record_key for e in events if "chiller controller failure" in str(e.get("notes") or "")}
    return {
        "reopened_later_Y": len(reopened),
        "bulletin_note": sum("TT-CB-114" in str(e.get("notes") or "") for e in events),
        "override_reasons_rows": len(override_ids),
        "override_ids_present_in_01": len(override_ids & event_ids),
        "late_notifications": len(late),
        "late_and_override": len(late & override_ids),
        "storm_INC2502_rows": len(storm),
        "storm_and_override": len(storm & override_ids),
        "reopened_fw": dict(Counter(e.get("logger_fw") for e in events if e.record_key in reopened)),
        "note": "Stratified evidence pack (00_README!R28): ratios inside 01 are NOT population ratios.",
    }


def _identifiers(products: Records, events: Records) -> dict[str, Any]:
    gtins = [r.get("gtin") for r in products if r.get("gtin") is not None]
    return {
        "gtin_values": len(gtins),
        "gtin_all_strings": all(isinstance(g, str) for g in gtins),
        "gtin_leading_zero": sum(str(g).startswith("0") for g in gtins),
        "event_product_refs_numeric_type": sum(isinstance(e.get("product_ref_as_received"), (int, float)) for e in events),
    }


def _timestamps(events: Records) -> dict[str, Any]:
    latency_by_source = defaultdict(list)
    unparseable = []
    for e in events:
        try:
            alert, start = parse_pack_utc(e.get("alert_ts_utc")), parse_pack_utc(e.get("excursion_start_utc"))
            latency_by_source[e.get("source_system")].append((alert - start).total_seconds() / 60)
        except ValueError:
            unparseable.append(e.record_key)
    return {
        "format": "YYYY-MM-DD HH:MM, no zone designator; UTC per 00_README!R31",
        "unparseable": unparseable,
        "detection_latency_min_by_source": {
            k: {"n": len(v), "min": min(v), "median": sorted(v)[len(v) // 2], "max": max(v)} for k, v in sorted(latency_by_source.items())
        },
    }


def _utc_offset(text: Any) -> timedelta:
    sign = -1 if str(text).startswith("-") else 1
    hours, minutes = str(text)[1:].split(":")
    return sign * timedelta(hours=int(hours), minutes=int(minutes))


def _queue_log_reconciliation(queue_log: Records, events: Records) -> dict[str, Any]:
    """README!R41: local_end - offset == alert + days_to_disposition."""
    by_id = {e.record_key: e for e in events}
    counts = Counter()
    differences = []
    for q in queue_log:
        e = by_id.get(q.get("case_ref"))
        if not e:
            counts["case_not_in_01"] += 1
            continue
        end_utc = parse_pack_utc(q.get("local_end")) - _utc_offset(q.get("reviewer_utc_offset"))
        expected = parse_pack_utc(e.get("alert_ts_utc")) + timedelta(days=float(e.get("days_to_disposition") or 0))
        diff = abs((end_utc - expected).total_seconds()) / 60
        counts["within_15_min" if diff <= RECONCILIATION_TOLERANCE_MIN else "outside_15_min"] += 1
        differences.append((diff, q.record_key, q.get("case_ref")))
    differences.sort(reverse=True)
    return {
        "counts": dict(counts),
        "largest_differences_min": [(round(d, 1), log_id, case) for d, log_id, case in differences[:5]],
        "note": "days_to_disposition has 2-decimal precision (~14 min), so a 15-minute tolerance is used.",
    }


# ---------------- joins ----------------
def _product_ref_matches(rows: Records, ref: Any) -> set[str]:
    return {r.source_ref for r in rows for f in PRODUCT_FIELDS if norm(r.get(f)) == norm(ref)}


def _event_product_ref_counts(events: Records, by_tenant: dict[str, Records]) -> tuple[Counter, list]:
    counts = Counter()
    other_tenant_only = []
    for e in events:
        ref = e.get("product_ref_as_received")
        if ref in (None, ""):
            counts["missing"] += 1
            continue
        own = _product_ref_matches(by_tenant[e.tenant_code], ref)
        other = set().union(*(_product_ref_matches(rows, ref) for t, rows in by_tenant.items() if t != e.tenant_code))
        if len(own) == 1:
            counts["exact_single_own_tenant"] += 1
        elif len(own) > 1:
            counts["ambiguous_own_tenant"] += 1
        elif other:
            counts["matches_other_tenants_only"] += 1
            other_tenant_only.append((e.record_key, e.tenant_code, ref))
        else:
            counts["no_master_match"] += 1
    return counts, other_tenant_only


def _product_joins(products: Records, events: Records, aliases: Records) -> dict[str, Any]:
    by_tenant: dict[str, Records] = defaultdict(list)
    for r in products:
        by_tenant[r.tenant_code].append(r)
    counts, other_tenant_only = _event_product_ref_counts(events, by_tenant)
    gtin_tenants = defaultdict(set)
    for r in products:
        if r.get("gtin"):
            gtin_tenants[r.get("gtin")].add(r.tenant_code)
    dup_sku = Counter((r.tenant_code, r.get("internal_sku")) for r in products if r.get("internal_sku"))
    return {
        "event_product_ref": dict(counts),
        "examples_other_tenant_only": other_tenant_only[:8],
        "gtins_shared_across_tenants": {g: sorted(t) for g, t in gtin_tenants.items() if len(t) > 1},
        "duplicate_sku_within_tenant": {f"{k[0]}|{k[1]}": n for k, n in dup_sku.items() if n > 1},
        "product_alias_rows_without_tenant": sum(a.get("entity_kind") == "PRODUCT" for a in aliases),
    }


def _facility_joins(facilities: Records, events: Records, aliases: Records) -> dict[str, Any]:
    groups = site_groups(facilities)
    code_by_name = {norm(r.get("name_in_source")): r.get("code_in_source") for r in facilities}
    code_by_name |= {norm(r.get("code_in_source")): r.get("code_in_source") for r in facilities}
    counts = Counter()
    for e in events:
        for role in ("origin_ref_as_received", "dest_ref_as_received"):
            code = code_by_name.get(norm(e.get(role)))
            counts["registry_site_code" if code in groups else "registry_unlinked_code" if code else "not_in_registry"] += 1
    return {
        "site_groups": sorted(groups),
        "records": len(facilities),
        "event_refs": dict(counts),
        "timezones_by_site": {g: sorted({r.get("timezone_in_source") for r in facilities if r.get("code_in_source") == g}) for g in sorted(groups)},
        "alias_negative_assertions": [
            (a.source_ref, a.get("string_a"), a.get("string_b"), a.get("comment")) for a in aliases if a.get("same_real_world_thing") == "N"
        ],
        "alias_comments": dict(Counter(a.get("comment") for a in aliases if a.get("comment"))),
    }


def _carrier_joins(contracts: Records, events: Records) -> dict[str, Any]:
    counts = Counter()
    for e in events:
        hits = [c.record_key for c in contracts if norm(e.get("carrier_ref_as_received")) in contract_names(c)]
        counts["single_contract" if len(hits) == 1 else "multiple_contracts" if hits else "no_contract_name_match"] += 1
    return {
        "event_refs": dict(counts),
        "contracts_without_cold_chain_clause": [c.record_key for c in contracts if "none" in str(c.get("cold_chain_clause")).lower()],
        "amendments_filed_separately": [c.record_key for c in contracts if "separately" in str(c.get("amendment_docs") or "")],
        "contracts_expired_before_2026-11-08": [
            c.record_key for c in contracts if str(c.get("effective_to")) < CONTRACT_EXPIRY_REFERENCE_DATE and c.get("effective_to") != "evergreen"
        ],
    }


# ---------------- SOP index ----------------
def _revision_window(rev: SourceRecord) -> str:
    return f"{rev.get('revision')} [{rev.get('effective_from')}, {rev.get('effective_to') or 'open'})"


def _overlapping_revisions(docs: dict[str, Records]) -> list[dict[str, Any]]:
    overlaps = []
    for doc_id, revs in docs.items():
        for a in revs:
            for b in revs:
                if a.record_key >= b.record_key:
                    continue
                a_to, b_to = a.get("effective_to") or OPEN_ENDED, b.get("effective_to") or OPEN_ENDED
                if a.get("effective_from") < b_to and b.get("effective_from") < a_to:
                    overlaps.append(
                        {"doc_id": doc_id, "tenant": a.tenant_code, "title": a.get("title"), "a": _revision_window(a), "b": _revision_window(b), "refs": [a.source_ref, b.source_ref]}
                    )
    return overlaps


def _revision_number(rev: SourceRecord) -> int:
    return int(re.sub(r"\D", "", rev.get("revision")))


def _sop_index(sop: Records, events: Records) -> dict[str, Any]:
    docs: dict[str, Records] = defaultdict(list)
    for r in sop:
        docs[r.get("doc_id")].append(r)
    overlaps = _overlapping_revisions(docs)
    handovers = sum(1 for revs in docs.values() for a in revs for b in revs if a.get("effective_to") and a.get("effective_to") == b.get("effective_from"))
    tem_tenants = {r.tenant_code for r in sop if r.get("title") == "Temperature Excursion Management"}
    rev_order = [
        d for d, revs in docs.items() if [_revision_number(x) for x in sorted(revs, key=lambda x: x.get("effective_from"))] != sorted(_revision_number(x) for x in revs)
    ]
    return {
        "documents": len(docs),
        "revisions": len(sop),
        "overlapping_pairs": overlaps,
        "docs_with_overlap": sorted({o["doc_id"] for o in overlaps}),
        "adjacent_handover_pairs_(to==next_from)": handovers,
        "docs_with_multiple_open_ended": [d for d, revs in docs.items() if sum(not x.get("effective_to") for x in revs) > 1],
        "revision_number_not_in_date_order": rev_order,
        "tenants_without_TEM_document": sorted({e.tenant_code for e in events} - tem_tenants),
        "formats": dict(Counter(r.get("format") for r in sop)),
        "languages": dict(Counter(r.get("language") for r in sop)),
        "applies_to_values": dict(Counter(r.get("applies_to_facilities_text") for r in sop)),
    }


# ---------------- stability index and spec text ----------------
def _master_study_refs(studies: Records, products: Records) -> tuple[Counter, list[dict[str, Any]]]:
    index = {s.record_key: s for s in studies}
    counts = Counter()
    mismatches = []
    for r in products:
        ref = r.get("stability_study_ref")
        if not ref:
            counts["master_ref_blank"] += 1
        elif ref not in index:
            counts["master_ref_not_indexed"] += 1
        elif index[ref].tenant_code != r.tenant_code:
            counts["master_ref_owned_by_other_tenant"] += 1
        else:
            counts["master_ref_indexed_same_tenant"] += 1
            study_text = index[ref].get("product_text_as_written")
            product_pres, study_pres = presentations(r.get("brand_as_labelled")), study_presentations(study_text)
            if product_pres and study_pres and not (product_pres & study_pres):
                mismatches.append({"product_row": r.source_ref, "tenant": r.tenant_code, "study": ref, "product": r.get("brand_as_labelled"), "study_text": study_text})
    return counts, mismatches


def _stability_index(studies: Records, products: Records) -> dict[str, Any]:
    counts, mismatches = _master_study_refs(studies, products)
    return {
        "index_rows": len(studies),
        "master_refs": dict(counts),
        "presentation_mismatches_master_to_study": mismatches,
        "path_folder_differs_from_owner": [
            (s.record_key, s.tenant_code, s.get("file_path_text")) for s in studies if s.get("file_path_text").split("/")[2] not in (s.tenant_code, "Shared")
        ],
        "shared_folder": [s.record_key for s in studies if "/Shared/" in s.get("file_path_text")],
        "readable": dict(Counter(s.get("readable") for s in studies)),
        "unreadable_with_permitted_text": [s.record_key for s in studies if str(s.get("readable")).startswith("N") and s.get("permitted_excursion_text")],
        "no_excursion_limit_by_design": sum(1 for s in studies if not s.get("permitted_excursion_text")),
        "indexed_by": dict(Counter(s.get("indexed_by") for s in studies)),
    }


def _spec_text(events: Records) -> dict[str, Any]:
    specs = {e.get("spec_text_as_received") for e in events}
    return {"spec_text_variants_in_01": len(specs), "unparseable_without_assumption": sorted(s for s in specs if parse_spec_range(s) is None)}


# ---------------- report writing ----------------
def _json_block(obj: Any) -> list[str]:
    return ["```json", json.dumps(obj, indent=1, ensure_ascii=False, default=str), "```"]


def _overview_markdown(report: dict[str, Any]) -> list[str]:
    wb = report["workbook"]
    lines = [
        "# Workbook inspection and data-quality report",
        "",
        f"Generated by `kccs-evidence inspect` from `{wb['file']}` (sha256 `{wb['sha256'][:16]}…`, extract {wb['extract_date']}).",
        "Machine-readable version: `report.json`. **The 420 alerts are a stratified evidence pack; no ratio below is a population estimate.**",
        "",
        "## Sheets",
        "",
        "| sheet | data rows | columns |",
        "|---|---|---|",
    ]
    lines += [f"| {s['sheet']} | {s['data_rows']} | {s['columns']} |" for s in report["sheets"]]
    lines += ["", "## Columns with missing values", "", "| sheet | column | missing / rows | distinct | types |", "|---|---|---|---|---|"]
    for sheet, cols in report["columns"].items():
        lines += [f"| {sheet} | {c['column']} | {c['missing']} / {c['rows']} | {c['distinct']} | {c['types']} |" for c in cols if c["missing"]]
    return lines


def _sop_markdown(sop: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## SOP index",
        "",
        f"- {sop['documents']} controlled documents, {sop['revisions']} revisions; {len(sop['overlapping_pairs'])} overlapping revision pairs across {len(sop['docs_with_overlap'])} documents.",
        f"- {sop['adjacent_handover_pairs_(to==next_from)']} hand-overs where effective_to equals the next effective_from → evidence for half-open [from, to) intervals.",
        f"- Documents with more than one open-ended revision: {sop['docs_with_multiple_open_ended']}.",
        f"- Revision numbers not in effective-date order: {sop['revision_number_not_in_date_order']}.",
        f"- Tenants with events but no 'Temperature Excursion Management' document: {sop['tenants_without_TEM_document']}.",
        "",
        "| doc | tenant | title | revision A | revision B | rows |",
        "|---|---|---|---|---|---|",
    ]
    return lines + [f"| {o['doc_id']} | {o['tenant']} | {o['title']} | {o['a']} | {o['b']} | {', '.join(o['refs'])} |" for o in sop["overlapping_pairs"]]


def _report_markdown(report: dict[str, Any]) -> list[str]:
    lines = _overview_markdown(report)
    lines += ["", "## Strata check (00_README!R28)", ""] + _json_block(report["strata"])
    timing = {k: report[k] for k in ("identifiers", "timestamps", "queue_log_reconciliation")}
    lines += ["", "## Identifiers and timestamps", ""] + _json_block(timing)
    for key, title in (
        ("product_joins", "Product joins (tenant-scoped exact match)"),
        ("facility_joins", "Facility joins"),
        ("carrier_joins", "Carrier joins"),
        ("stability", "Stability index"),
        ("spec", "Specification text"),
    ):
        lines += ["", f"## {title}", ""] + _json_block(report[key])
    lines += _sop_markdown(report["sop"])
    lines += ["", "## Reviewer questions (10_Reviewer_Questions) answerable from the pack", "", "| Q | answerable | why |", "|---|---|---|"]
    lines += [f"| {q} | {v['answerable_from_pack']} | {v['why']} |" for q, v in report["reviewer_questions"].items()]
    lines += ["", "## Notification rows flagged reportable in 01 (tenant | window | within)", ""] + _json_block(report["notification_rows"])
    return lines + ["", "## Semantics warnings", ""] + [f"- {w}" for w in report["semantics_warnings"]]


def write_report(rep: dict[str, Any], out_dir: str | Path) -> Path:
    """Write report.json and report.md into out_dir; returns the markdown path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    path = out / "report.md"
    path.write_text("\n".join(_report_markdown(rep)) + "\n", encoding="utf-8")
    return path
