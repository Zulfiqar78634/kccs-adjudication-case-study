"""Assessment builder: turns one alert into a reproducible evidence assessment.

Leakage control
---------------
Only ALLOWED_EVENT_FIELDS of the alert are read (they exist at alert receipt).
OUTCOME_FIELDS are never passed to the evidence logic; they are used only by
evaluation.py. Prior cases on the same lane may show their disposition only if
it was signed before the knowledge cutoff and the case was never reopened
(the pack keeps only the latest value, so an original value cannot be recovered).

Output is a reviewer aid or an explicit abstention, never a disposition.
"""
from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib import metadata, resources
from typing import Any

from . import ASSESSMENT_SCHEMA_VERSION, RULESET_VERSION, STORE_SCHEMA_VERSION, __version__
from .access import Principal, TenantView, system_clock
from .config_loader import config_manifest, load_config
from .model import BLOCKING, INFO, REVIEW, Finding, norm
from .obligations import PolicyIncomplete, Regime, compute_due_at
from .policy_sop import select_sop
from .resolution import resolve_carrier, resolve_facility, resolve_product
from .signals import excursion_direction, firmware_uncertainty, parse_spec_range, telemetry_findings
from .sources import canonical_json, sha256_text
from .stability import assess_stability
from .store import Store
from .temporal import iso, parse_date, parse_effective_to, parse_iso_utc, parse_pack_utc

ALLOWED_EVENT_FIELDS = (
    "event_id", "alert_ts_utc", "tenant_code", "shipment_ref", "leg_no", "source_system", "logger_id",
    "logger_vendor", "logger_fw", "product_ref_as_received", "origin_ref_as_received", "dest_ref_as_received",
    "lane_text", "carrier_ref_as_received", "mode", "excursion_start_utc", "excursion_end_utc", "duration_min",
    "min_temp_c", "max_temp_c", "mean_temp_c", "spec_text_as_received", "readings_in_window", "gateway_gap_min",
    "interpolated", "dock_door_open_flag", "prior_excursions_lane_90d", "consignment_value_usd")
OUTCOME_FIELDS = (
    "case_opened", "triage_outcome", "rules_engine_recommendation", "final_disposition", "reviewer_id",
    "review_minutes", "systems_opened", "reviewer_overrode", "days_to_disposition", "regulator_reportable",
    "reg_window_hours", "hours_to_notification", "reported_within_window", "reopened_later", "notes")
TENANT_PREFIX = {"T-AURA": "AUR", "T-VIRENT": "VIR", "T-NORDIA": "NOR", "T-PINNACLE": "PIN", "T-MERIDIAN": "MER",
                 "T-SAHYADRI": "SAH", "T-CAMPOS": "CAM", "T-KAVERI": "KAV"}
DISPOSITION_DIMENSIONS = {"identity", "policy", "stability", "telemetry", "firmware", "attribution", "knowledge"}


@dataclass(frozen=True)
class AlertInput:
    fields: dict[str, Any]
    source_ref: str

    @classmethod
    def from_record(cls, rec) -> "AlertInput":
        return cls({k: rec.get(k) for k in ALLOWED_EVENT_FIELDS}, rec.source_ref)

    def __getitem__(self, k: str) -> Any:
        return self.fields[k]

    @property
    def fields_sha256(self) -> str:
        return sha256_text(canonical_json(self.fields))


def code_fingerprint() -> str:
    h = hashlib.sha256()
    pkg = resources.files("kccs_evidence")
    for name in sorted(p.name for p in pkg.iterdir() if p.name.endswith(".py")):
        h.update(name.encode())
        h.update(pkg.joinpath(name).read_bytes())
    return h.hexdigest()


def _lane_history(view: TenantView, alert: AlertInput, alert_ts: datetime, cutoff: datetime) -> tuple[list[dict], list[Finding]]:
    out = []
    for e in view.tenant_records("01_Excursion_Events"):
        if e.record_key == alert["event_id"]:
            continue
        ts = parse_pack_utc(e.get("alert_ts_utc"))
        if ts >= alert_ts or ts > cutoff or alert_ts - ts > timedelta(days=90):
            continue
        same_lane = norm(e.get("lane_text")) == norm(alert["lane_text"]) or (
            norm(e.get("origin_ref_as_received")) == norm(alert["origin_ref_as_received"])
            and norm(e.get("dest_ref_as_received")) == norm(alert["dest_ref_as_received"]))
        same_carrier_origin = (norm(e.get("carrier_ref_as_received")) == norm(alert["carrier_ref_as_received"])
                               and norm(e.get("origin_ref_as_received")) == norm(alert["origin_ref_as_received"]))
        if not (same_lane or same_carrier_origin):
            continue
        # Precedent gate: a prior disposition is visible only if signed before the cutoff and never reopened.
        disp, days = e.get("final_disposition"), e.get("days_to_disposition")
        if disp is None:
            shown = "NO_HUMAN_DISPOSITION_RECORDED"
        elif e.get("reopened_later") == "Y":
            shown = "UNKNOWABLE_AT_CUTOFF (case later reopened; pack keeps only the latest value)"
        elif days is not None and ts + timedelta(days=float(days)) <= cutoff:
            shown = disp
        else:
            shown = "NOT_YET_SIGNED_AT_CUTOFF"
        out.append({"event_id": e.record_key, "ref": e.source_ref, "alert_ts_utc": e.get("alert_ts_utc"),
                    "match": "lane" if same_lane else "carrier+origin", "disposition_at_cutoff": shown})
    f = []
    if out:
        f.append(Finding("LANE_HISTORY_PRESENT", REVIEW, "history",
                         f"{len(out)} earlier alert(s) for this tenant on the same lane or carrier+origin within 90 days (pack sample only; not exhaustive).",
                         tuple(o["ref"] for o in out), "Review prior events for a pattern (equipment, carrier, batch)"))
    f.append(Finding("BATCH_EXPOSURE_HISTORY_UNAVAILABLE", REVIEW, "history",
                     "No batch identity or lifetime exposure history in the pack; cumulative and once-only conditions cannot be verified.",
                     (), "Obtain batch excursion history before relying on a cumulative/once-only allowance"))
    return out, f


def _liability(carrier, alert_ts: datetime) -> tuple[dict, list[Finding]]:
    out: dict[str, Any] = {"carrier": carrier.to_dict(), "note": "Liability/claims track only; never affects product disposition."}
    f: list[Finding] = []
    if carrier.usable:
        a = carrier.attributes
        d = alert_ts.date()
        start, end = parse_date(a.get("effective_from")), parse_effective_to(a.get("effective_to"))
        out["contract_in_force_on_event_date_utc"] = start <= d < end
        if not out["contract_in_force_on_event_date_utc"]:
            f.append(Finding("CONTRACT_NOT_IN_FORCE_ON_EVENT_DATE", REVIEW, "liability",
                             f"{carrier.resolved_id} window [{a.get('effective_from')}, {a.get('effective_to')}) does not cover {d}.", tuple(carrier.source_refs)))
        if "none" in str(a.get("cold_chain_clause") or "").lower():
            f.append(Finding("CONTRACT_NO_COLD_CHAIN_CLAUSE", REVIEW, "liability",
                             f"{carrier.resolved_id} has no cold-chain schedule; affects who pays, not what happens to product.", tuple(carrier.source_refs)))
        if "separately" in str(a.get("amendment_docs") or ""):
            f.append(Finding("CONTRACT_AMENDMENTS_FILED_SEPARATELY", INFO, "liability",
                             f"{carrier.resolved_id}: amendments filed separately and not in the pack.", tuple(carrier.source_refs)))
        out["claim_window_days"] = a.get("claim_window_days")
        out["claim_window_trigger"] = "NOT_STATED_IN_PACK"
    return out, f


def _notification_track(tenant: str, alert_ts: datetime) -> tuple[dict, list[Finding]]:
    cfg = load_config("reference_facts.json")["notification_regimes"].get(tenant)
    track: dict[str, Any] = {"clock_start_utc": iso(alert_ts), "clock_basis": "alert_ts_utc: when the reading reached Sentinel (00_README!R43)",
                             "independent_of_disposition": True, "paused_by_evidence_waits": False,
                             "notifiability": "UNDETERMINED: a human determination is required; the kernel does not decide it",
                             "submission_status": "NOT_VISIBLE_TO_KERNEL"}
    if cfg is None:
        track.update(status="REGIME_UNKNOWN", due_at_utc=None)
        return track, [Finding("NOTIFICATION_REGIME_UNKNOWN", REVIEW, "notification", "No notification regime configured for this tenant.", (),
                               "Regulatory Affairs to configure the regime")]
    track["regime"] = cfg
    try:
        due = compute_due_at(alert_ts, Regime.from_config(cfg))
        track.update(status="DEADLINE_COMPUTED", due_at_utc=iso(due))
        return track, [Finding("NOTIFICATION_DETERMINATION_DUE", REVIEW, "notification",
                               f"If notifiable, notification is due by {iso(due)} ({cfg['kind']} {cfg.get('hours')} h from alert receipt). Evidence waits do not pause this clock.",
                               (cfg["source"],), f"Determine notifiability before {iso(due)}")]
    except PolicyIncomplete as exc:
        track.update(status="POLICY_INCOMPLETE_ESCALATE", due_at_utc=None, error=str(exc))
        return track, [Finding("NOTIFICATION_DEADLINE_NOT_COMPUTABLE", REVIEW, "notification",
                               f"Deadline cannot be computed: {exc}. Escalate immediately; do not assume 24 h.",
                               (cfg["source"],), "Regulatory Affairs to determine the deadline now")]


def resolve_cutoff(spec: str, alert_ts: datetime, clock) -> datetime:
    if spec == "alert":
        return alert_ts
    if spec == "now":
        return clock()
    cutoff = parse_iso_utc(spec)
    if cutoff < alert_ts:
        raise ValueError("knowledge cutoff precedes alert receipt; the alert itself was not yet known")
    return cutoff


def build_assessment(store: Store, principal: Principal, tenant: str, event_id: str, *,
                     knowledge_cutoff: str = "alert", mode: str = "RECONSTRUCTED", clock=system_clock) -> dict[str, Any]:
    probe = TenantView(store, principal, tenant, None, clock)       # access check before anything else
    alert_ts = parse_pack_utc(probe.event(event_id).get("alert_ts_utc"))
    cutoff = resolve_cutoff(knowledge_cutoff, alert_ts, clock)
    cutoff_date = cutoff.date()
    if mode == "RECONSTRUCTED":
        # The initial snapshot is backfilled as if known at the cutoff (its true history is not in the pack);
        # anything recorded after that baseline (corrections, later snapshots) is visible only if recorded <= cutoff.
        baseline = min((s["recorded_at"] for s in store.snapshots()), default=iso(cutoff))
        store_cutoff = max(iso(cutoff), baseline)
    else:
        store_cutoff = iso(cutoff)
    view = TenantView(store, principal, tenant, store_cutoff, clock, knowledge_cutoff=iso(cutoff))
    # The alert is the subject of the assessment; in strict mode it may itself post-date the cutoff in this
    # store (the pack was recorded at extract), in which case the evidence check below abstains.
    rec = next((r for r in view.tenant_records("01_Excursion_Events") if r.record_key == event_id), None) or probe.event(event_id)
    alert = AlertInput.from_record(rec)
    exc_start = parse_pack_utc(alert["excursion_start_utc"])
    findings: list[Finding] = []

    knowledge = {"mode": mode, "cutoff_utc": iso(cutoff), "cutoff_spec": knowledge_cutoff, "store_cutoff_utc": store_cutoff}
    if mode == "RECONSTRUCTED":
        knowledge["basis"] = ("Evidence is the ingested snapshot, restricted by every knowledge date the pack provides "
                              "(alias confirmed_on, bulletin dates, human mapping recorded_at, precedent signature times). "
                              "The pack carries no recorded-time history for SOP/stability/master rows, so this is a "
                              "retrospective reconstruction ('what do we conclude now about then'), not proof of what was known then.")
        findings.append(Finding("KNOWLEDGE_TIME_RECONSTRUCTED", INFO, "knowledge", knowledge["basis"], ()))
    elif not view.tenant_records("05_SOP_Index"):
        findings.append(Finding("KNOWLEDGE_HISTORY_UNAVAILABLE", BLOCKING, "knowledge",
                                f"Strict replay: no evidence was recorded in this system at or before {iso(cutoff)}.", (),
                                "Use a reconstructed replay and label it as such"))

    prefix = str(alert["shipment_ref"] or "").split("-")
    attribution_ok = len(prefix) > 1 and TENANT_PREFIX.get(tenant) == prefix[1]
    if not attribution_ok:
        findings.append(Finding("TENANT_ATTRIBUTION_CONFLICT", BLOCKING, "attribution",
                                f"shipment_ref {alert['shipment_ref']!r} does not carry the prefix expected for {tenant}.",
                                (alert.source_ref,), "Quarantine for attribution; do not use tenant-scoped evidence"))

    product, f = resolve_product(view, alert["product_ref_as_received"]); findings += f
    origin, f = resolve_facility(view, alert["origin_ref_as_received"], "origin", cutoff_date); findings += f
    dest, f = resolve_facility(view, alert["dest_ref_as_received"], "destination", cutoff_date); findings += f
    carrier, f = resolve_carrier(view, alert["carrier_ref_as_received"], cutoff_date); findings += f

    spec = parse_spec_range(alert["spec_text_as_received"])
    if spec is None:
        findings.append(Finding("SPEC_UNPARSED", REVIEW, "stability",
                                f"Specification {alert['spec_text_as_received']!r} could not be parsed without assumption.", (alert.source_ref,)))
    if product.usable:
        mspec = parse_spec_range(product.attributes.get("storage_spec_text"))
        if spec and mspec and spec != mspec:
            findings.append(Finding("SPEC_DISAGREES_WITH_CURRENT_MASTER", REVIEW, "stability",
                                    f"Spec at alert {alert['spec_text_as_received']!r} vs current master {product.attributes.get('storage_spec_text')!r}.",
                                    (alert.source_ref, product.resolved_id), "Confirm which specification governed at alert time"))
        lu = parse_date(product.attributes.get("last_updated"))
        if lu and lu > alert_ts.date():
            findings.append(Finding("PRODUCT_MASTER_UPDATED_AFTER_ALERT", REVIEW, "knowledge",
                                    f"Product-master row last updated {lu}, after the alert; the version in force at alert time is not in the pack.",
                                    (product.resolved_id,), "Retrieve the product-master version effective at alert time"))

    ev = {k: alert[k] for k in ("max_temp_c", "min_temp_c", "duration_min", "gateway_gap_min", "interpolated",
                                "readings_in_window", "dock_door_open_flag", "source_system")}
    fw = firmware_uncertainty(alert["logger_fw"], alert["logger_vendor"], cutoff)
    direction = excursion_direction(ev, spec, fw)
    if fw:
        findings.append(Finding("FIRMWARE_BULLETIN_APPLIES", REVIEW, "firmware",
                                f"Logger firmware {alert['logger_fw']} is subject to {fw['bulletin_id']}: under-reports by up to {fw['magnitude_c_max']} °C. "
                                f"Treated as an uncertainty interval [+0, +{fw['magnitude_c_max']}] °C, not a fixed correction.",
                                (fw["source"],), "Re-evaluate temperatures under the uncertainty band"))
        if direction.startswith("WITHIN_REPORTED_BUT_POSSIBLY_ABOVE"):
            findings.append(Finding("POSSIBLE_UNDETECTED_EXCURSION", BLOCKING, "firmware",
                                    "Reported values are within spec but may exceed it after the firmware correction band.", (fw["source"],)))
    if direction == "BELOW" or direction == "ABOVE_AND_BELOW":
        findings.append(Finding("COLD_EXCURSION", REVIEW, "stability",
                                "Excursion below the labelled range; freeze damage is not assessed by warm-excursion allowances (cf. EXC-110483).",
                                (alert.source_ref,), "Assess freeze sensitivity for this product"))

    sops, f = select_sop(view, load_config("sop_scope_rules.json")["excursion_titles"], origin, "origin", exc_start); findings += f
    dest_sops, f = select_sop(view, load_config("sop_scope_rules.json")["excursion_titles"], dest, "destination", exc_start)
    findings += [Finding(x.code, REVIEW if x.severity == BLOCKING else x.severity, x.dimension, "[destination] " + x.message, x.source_refs, x.human_action) for x in f]
    notif_sops, _ = select_sop(view, load_config("sop_scope_rules.json")["notification_titles"], origin, "origin", exc_start)

    stability, f = assess_stability(view, product, ev, spec, fw); findings += f
    findings += telemetry_findings(ev, alert.source_ref)
    liability, f = _liability(carrier, exc_start); findings += f
    history, f = _lane_history(view, alert, alert_ts, cutoff); findings += f
    notification, f = _notification_track(tenant, alert_ts); findings += f

    constraints = next((r.payload for r in view.tenant_records("12_Tenant_Constraints")), {})
    signer = constraints.get("who_signs_a_disposition")
    authority = {"who_signs": signer, "dual_signature_required": "dual" in str(signer).lower(),
                 "output_language": constraints.get("output_language"),
                 "data_residency": constraints.get("data_residency_position"),
                 "third_party_model_apis": constraints.get("third_party_model_apis"),
                 "source": "12_Tenant_Constraints"}

    blocking = [x for x in findings if x.severity == BLOCKING and x.dimension in DISPOSITION_DIMENSIONS]
    if not attribution_ok:
        status = "QUARANTINED_FOR_ATTRIBUTION"
    elif any(x.code == "KNOWLEDGE_HISTORY_UNAVAILABLE" for x in blocking):
        status = "ABSTAIN_KNOWLEDGE_HISTORY_UNAVAILABLE"
    elif blocking:
        status = "ABSTAIN_BLOCKING_EVIDENCE_GAPS"
    else:
        status = "READY_FOR_QA_REVIEW"
    actions, seen = [], set()
    for x in findings:
        if x.human_action and (x.code, x.human_action) not in seen:
            seen.add((x.code, x.human_action))
            actions.append({"action": x.human_action, "because": x.code, "severity": x.severity})
    actions.append({"action": f"Sign or decline the disposition: {signer}" + (" (two signatures)" if authority["dual_signature_required"] else ""),
                    "because": "DISPOSITION_IS_A_HUMAN_DECISION", "severity": "REQUIRED"})

    aid = []
    for chk in stability["limit_checks"]:
        if chk["status"] not in ("NOT_EVALUATED",):
            aid.append({"statement": f"Against {chk['source']} limit {chk['limit'].get('text')!r}: {chk['status']}",
                        "reported": chk["reported"], "firmware_band_c": chk["firmware_band_c"],
                        "unverifiable_conditions": chk["unverifiable_conditions"]})
    payload: dict[str, Any] = {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "event": {"event_id": event_id, "tenant_code": tenant, "source_ref": alert.source_ref,
                  "allowed_input_fields": alert.fields, "allowed_fields_sha256": alert.fields_sha256,
                  "excluded_outcome_fields": list(OUTCOME_FIELDS)},
        "time_semantics": {"valid_at": iso(exc_start), "alert_received_at": iso(alert_ts), "knowledge_cutoff": iso(cutoff),
                           "knowledge": knowledge,
                           "policy_date_convention": "date-only effective dates as half-open [from, to) local calendar dates at the governed site"},
        "disposition_evidence_status": status,
        "is_disposition": False,
        "blocking_reasons": sorted({x.code for x in blocking}),
        "entities": {"product": product.to_dict(), "origin": origin.to_dict(), "destination": dest.to_dict(), "carrier": carrier.to_dict()},
        "excursion": {"direction_vs_spec_as_received": direction, "spec_as_received": alert["spec_text_as_received"],
                      "spec_range_c": list(spec) if spec else None,
                      "aggregates_only": True, "firmware_bulletin": fw["bulletin_id"] if fw else None},
        "evidence": {"sop_origin": sops, "sop_destination": dest_sops, "sop_notification": notif_sops,
                     "stability": stability, "lane_history": history},
        "liability_track": liability,
        "notification_track": notification,
        "disposition_authority": authority,
        "findings": [x.to_dict() for x in findings],
        "missing_inputs": sorted({x.code for x in findings if x.code.endswith(("UNAVAILABLE", "MISSING", "NOT_IN_TENANT_INDEX", "UNRESOLVED"))}),
        "required_human_actions": actions,
        "reviewer_aid": {"note": "Arithmetic and evidence pointers for the reviewer. Not a recommendation and not a disposition.",
                         "items": aid},
        "manifest": {"kernel_version": __version__, "ruleset_version": RULESET_VERSION, "store_schema_version": STORE_SCHEMA_VERSION,
                     "code_sha256": code_fingerprint(), "config": config_manifest(),
                     "workbook_snapshots": [{k: s[k] for k in ("snapshot_id", "file_sha256", "extract_date")} for s in store.snapshots()],
                     "cited_source_versions": sorted({f"{r.sheet}/{r.record_key}@v{getattr(r, 'version', 1)}:{r.row_hash[:16]}"
                                                      for sheet in ("02_Product_Master", "05_SOP_Index", "06_Stability_Index")
                                                      for r in view.tenant_records(sheet)
                                                      if r.source_ref in canonical_json([product.to_dict(), sops, dest_sops, stability])}),
                     "model": {"route": "NONE", "reason": "deterministic kernel; no language model or embedding invoked"},
                     "stubs": {"telemetry_archive": "NOT_AVAILABLE", "document_content_store": "NOT_AVAILABLE",
                               "batch_exposure_history": "NOT_AVAILABLE", "regulator_gateway": "NOT_INVOKED"}},
    }
    payload["assessment_id"] = "ASM-" + sha256_text(canonical_json(payload))[:24]
    payload["runtime"] = {"python": platform.python_version(),
                          "openpyxl": metadata.version("openpyxl"), "requested_by": principal.actor_id}
    return payload


def assess_and_store(store: Store, principal: Principal, tenant: str, event_id: str, *, knowledge_cutoff: str = "alert",
                     mode: str = "RECONSTRUCTED", clock=system_clock) -> tuple[dict[str, Any], bool]:
    """Build, link to the previous assessment of the same event, and store (idempotent)."""
    payload = build_assessment(store, principal, tenant, event_id, knowledge_cutoff=knowledge_cutoff, mode=mode, clock=clock)
    prior = [a for a in store.assessments_for_event(tenant, event_id) if a["assessment_id"] != payload["assessment_id"]]
    if prior:
        import json
        last = json.loads(prior[-1]["payload_json"])
        payload["supersedes"] = last["assessment_id"]
        old, new = {f["code"] for f in last["findings"]}, {f["code"] for f in payload["findings"]}
        payload["change_from_superseded"] = {"added_findings": sorted(new - old), "removed_findings": sorted(old - new),
                                             "status": [last["disposition_evidence_status"], payload["disposition_evidence_status"]],
                                             "knowledge_cutoff": [last["time_semantics"]["knowledge_cutoff"], payload["time_semantics"]["knowledge_cutoff"]],
                                             "reopen_review_recommended": bool((new - old) & {"FIRMWARE_BULLETIN_APPLIES", "POSSIBLE_UNDETECTED_EXCURSION", "LIMIT_CHECK_FLIPS_WITHIN_FIRMWARE_BAND"})
                                             or (last["disposition_evidence_status"] == "READY_FOR_QA_REVIEW" and payload["disposition_evidence_status"] != "READY_FOR_QA_REVIEW")}
    aid, inserted = store.put_assessment(payload, iso(clock()))
    store.audit(at=iso(clock()), actor=principal.actor_id, tenant=tenant, action="ASSESSMENT_BUILD", target=aid,
                outcome="STORED" if inserted else "IDEMPOTENT_EXISTING", detail={"event_id": event_id})
    return payload, inserted
