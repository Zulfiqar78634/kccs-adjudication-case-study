"""Temporal, site-scoped SOP revision selection.

Rules (see temporal.py for interval conventions):
* A revision is in force on local date d iff effective_from <= d < effective_to.
* More than one in-force revision of the same controlled document is a
  BLOCKING conflict. We never pick the highest revision number or latest row:
  supersedes_text is free text (11_Systems_Inventory!R8) and revision numbers
  are not reliably ordered by date (e.g. SOP-MER-5228 Rev 05 precedes Rev 04).
* If the site timezone is unknown/untrusted, every plausible local date is
  evaluated; a selection that differs across dates is BOUNDARY_AMBIGUOUS.
* The pack holds the document index only, never the acceptance-limit content,
  so a selected revision always needs a human to read the limit.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .access import TenantView
from .config_loader import load_config
from .model import BLOCKING, INFO, REVIEW, Finding, Resolution
from .temporal import parse_date, parse_effective_to, plausible_local_dates


def _rev_no(rev: str) -> int:
    m = re.search(r"(\d+)", rev or "")
    return int(m.group(1)) if m else -1


def scope_applies(applies_text: str, site: Resolution | None) -> tuple[bool | None, str]:
    rule = load_config("sop_scope_rules.json")["rules"].get(applies_text)
    if rule is None:
        return None, f"scope text {applies_text!r} has no approved interpretation"
    kind = rule["kind"]
    if kind == "ALL":
        return True, "applies to all sites"
    if kind == "ANNEXURE":
        return True, f"tenant-wide; site limits in {rule['annexure']}"
    if site is None or not site.usable:
        return None, f"scope {applies_text!r} needs the site, which is not resolved"
    if kind == "COUNTRY":
        country = site.attributes.get("country")
        if country is None:
            return None, "site country conflicting/unknown in registry"
        return country in rule["countries"], f"site country {country} vs {rule['countries']}"
    if kind == "SITES":
        return site.resolved_id in rule["sites"], f"site {site.resolved_id} vs {rule['sites']}"
    if kind == "ALL_EXCEPT":
        return site.resolved_id not in rule["sites"], f"site {site.resolved_id} vs excluded {rule['sites']}"
    return None, f"unknown rule kind {kind}"


def select_sop(
    view: TenantView, titles: list[str], site: Resolution | None, site_role: str, event_time: datetime
) -> tuple[list[dict[str, Any]], list[Finding]]:
    rows = [r for r in view.tenant_records("05_SOP_Index") if r.get("title") in titles]
    findings: list[Finding] = []
    if not rows:
        others = sorted({r.get("title") for r in view.tenant_records("05_SOP_Index")})
        return [], [
            Finding(
                "NO_SOP_INDEXED",
                BLOCKING,
                "policy",
                f"No {titles} document indexed for this tenant. Other indexed titles (not assumed to govern): {others}.",
                (),
                "Document control to identify the governing excursion procedure",
            )
        ]
    tz = site.attributes.get("timezone") if site and site.usable else None
    trusted = bool(site and site.usable and site.attributes.get("timezone_trusted"))
    dates, date_basis = plausible_local_dates(event_time, tz, trusted)
    docs: dict[str, list] = {}
    for r in rows:
        docs.setdefault(r.get("doc_id"), []).append(r)
    results = []
    for doc_id, revs in sorted(docs.items()):
        per_date: dict[str, tuple[str, ...]] = {}
        unknown_scope: set[str] = set()
        rejected: dict[str, str] = {}
        for d in sorted(dates):
            in_force = []
            for r in revs:
                start, end = parse_date(r.get("effective_from")), parse_effective_to(r.get("effective_to"))
                if not (start <= d < end):
                    rejected.setdefault(r.source_ref, f"{r.get('revision')} not in force on {d} ([{start}, {r.get('effective_to') or 'open'}))")
                    continue
                applies, why = scope_applies(r.get("applies_to_facilities_text"), site)
                if applies is False:
                    rejected[r.source_ref] = f"{r.get('revision')} out of site scope: {why}"
                    continue
                if applies is None:
                    unknown_scope.add(r.source_ref)
                in_force.append(r.source_ref)
            per_date[d.isoformat()] = tuple(sorted(in_force))
        distinct = set(per_date.values())
        by_ref = {r.source_ref: r for r in revs}
        entry: dict[str, Any] = {
            "doc_id": doc_id,
            "title": revs[0].get("title"),
            "site_role": site_role,
            "site": site.resolved_id if site else None,
            "dates_evaluated": sorted(per_date),
            "date_basis": date_basis,
            "revisions_indexed": [
                {
                    "ref": r.source_ref,
                    "revision": r.get("revision"),
                    "effective_from": r.get("effective_from"),
                    "effective_to": r.get("effective_to"),
                    "supersedes_text": r.get("supersedes_text"),
                    "applies_to": r.get("applies_to_facilities_text"),
                }
                for r in revs
            ],
        }
        for ref in per_date.get(min(per_date), ()):
            rejected.pop(ref, None)
        if len(distinct) > 1:
            entry["status"] = "BOUNDARY_AMBIGUOUS"
            entry["in_force_by_date"] = {d: [by_ref[x].get("revision") for x in v] for d, v in per_date.items()}
            findings.append(
                Finding(
                    "SOP_BOUNDARY_AMBIGUOUS",
                    BLOCKING,
                    "policy",
                    f"{doc_id}: the revision in force depends on the {site_role} site's local date ({date_basis}).",
                    tuple(sorted(by_ref)),
                    "Confirm site timezone and the revision in force",
                )
            )
        else:
            in_force = next(iter(distinct))
            entry["in_force"] = [by_ref[x].get("revision") for x in in_force]
            if not in_force:
                if all("out of site scope" in v for v in rejected.values() if v):
                    entry["status"] = "NOT_APPLICABLE_TO_SITE"
                else:
                    entry["status"] = "NONE_IN_FORCE"
                    findings.append(
                        Finding(
                            "SOP_NONE_IN_FORCE",
                            BLOCKING,
                            "policy",
                            f"{doc_id}: no revision in force at the {site_role} site on {sorted(per_date)}.",
                            tuple(sorted(by_ref)),
                            "Locate the revision in force",
                        )
                    )
            elif len(in_force) > 1:
                entry["status"] = "CONFLICT_OVERLAPPING_REVISIONS"
                revs_txt = [f"{by_ref[x].get('revision')} [{by_ref[x].get('effective_from')}, {by_ref[x].get('effective_to') or 'open'})" for x in in_force]
                findings.append(
                    Finding(
                        "SOP_REVISION_OVERLAP",
                        BLOCKING,
                        "policy",
                        f"{doc_id} ({revs[0].get('title')}): {len(in_force)} revisions in force at the {site_role} site on {sorted(per_date)[0]}"
                        f"{'' if len(per_date) == 1 else ' (all plausible dates)'}: {revs_txt}. Not resolved by revision number or row order.",
                        in_force,
                        "Document control to confirm which revision governed on the excursion date",
                    )
                )
            else:
                ref = in_force[0]
                r = by_ref[ref]
                entry["status"] = "SELECTED_PROVISIONAL" if ref in unknown_scope else "SELECTED"
                entry["selected"] = {
                    "ref": ref,
                    "revision": r.get("revision"),
                    "format": r.get("format"),
                    "language": r.get("language"),
                    "acceptance_limits_location": r.get("acceptance_limits_location"),
                }
                if ref in unknown_scope:
                    findings.append(
                        Finding(
                            "SOP_SITE_SCOPE_UNKNOWN",
                            REVIEW,
                            "policy",
                            f"{doc_id} {r.get('revision')}: site scope {r.get('applies_to_facilities_text')!r} cannot be checked because the {site_role} site is not resolved.",
                            (ref,),
                            "Confirm the site, then confirm scope",
                        )
                    )
                loc = r.get("acceptance_limits_location") or ""
                fmt = r.get("format") or ""
                detail = f"limits located at '{loc}', format '{fmt}'"
                if "Not stated" in loc:
                    detail += "; the SOP defers to the product master"
                if "Annexure" in loc or str(r.get("applies_to_facilities_text") or "").startswith("Site-specific"):
                    detail += "; annexures are separate documents not present in the index"
                findings.append(
                    Finding(
                        "SOP_ACCEPTANCE_LIMIT_CONTENT_UNAVAILABLE",
                        BLOCKING,
                        "policy",
                        f"{doc_id} {r.get('revision')} identified, but the pack has no document content: {detail}.",
                        (ref,),
                        "QA to read and record the acceptance limit from the controlled copy",
                    )
                )
                if "handwritten" in fmt.lower() or "margin note" in loc.lower():
                    findings.append(
                        Finding(
                            "SOP_HANDWRITTEN_ANNOTATION",
                            REVIEW,
                            "policy",
                            f"{doc_id} {r.get('revision')}: handwritten annotation / margin note may change the acceptance limit; its authority must be verified.",
                            (ref,),
                            "Verify who initialled the annotation and whether it is controlled",
                        )
                    )
                ordered_by_date = sorted(revs, key=lambda x: x.get("effective_from"))
                if [_rev_no(x.get("revision")) for x in ordered_by_date] != sorted(_rev_no(x.get("revision")) for x in revs):
                    findings.append(
                        Finding(
                            "SOP_REVISION_ORDER_ANOMALY", INFO, "policy", f"{doc_id}: revision numbers are not in effective-date order.", tuple(sorted(by_ref))
                        )
                    )
        entry["rejected"] = [{"ref": k, "reason": v} for k, v in sorted(rejected.items())]
        results.append(entry)
    return results, findings
