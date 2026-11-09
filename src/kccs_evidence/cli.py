"""Command-line interface (primary executable surface of the prototype)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .access import Principal, TenantAccessDenied
from .assessment import assess_and_store, build_assessment
from .evaluation import evaluate
from .inspection import inspect, write_report
from .package import export_package, verify_package
from .sources import load_workbook_snapshot
from .store import Store
from .temporal import UTC, iso, parse_iso_utc

DEFAULT_DB = "artifacts/kernel.sqlite"
EXTRACT_CUTOFF = "2026-09-14T23:59:00Z"   # latest knowledge the pack can represent


def _fixed_clock(ts: str | None):
    if ts:
        t = parse_iso_utc(ts)
        return lambda: t
    return lambda: datetime.now(UTC)


def _principal(args) -> Principal:
    tenants = frozenset(t.strip() for t in (args.tenant_scope or args.tenant or "").split(",") if t.strip())
    return Principal(args.actor, tenants)


def _dump(obj, path: Path | None):
    text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def cmd_ingest(args):
    snap = load_workbook_snapshot(args.workbook)
    recorded = args.recorded_at or f"{snap.extract_date}T00:00:00Z"
    stats = Store(args.db).ingest_snapshot(snap, recorded)
    print(json.dumps({"snapshot_id": snap.snapshot_id, "file_sha256": snap.file_sha256, "recorded_at": recorded, **stats}))


def cmd_inspect(args):
    path = write_report(inspect(args.workbook), args.out_dir)
    print(f"wrote {path} and {Path(args.out_dir) / 'report.json'}")


def cmd_assess(args):
    store = Store(args.db)
    payload, inserted = assess_and_store(store, _principal(args), args.tenant, args.event,
                                         knowledge_cutoff=args.knowledge_cutoff, mode=args.mode, clock=_fixed_clock(args.now))
    _dump(payload, Path(args.out) if args.out else None)
    print(f"{payload['assessment_id']} status={payload['disposition_evidence_status']} stored={'new' if inserted else 'existing'}", file=sys.stderr)


def cmd_export(args):
    out = export_package(Store(args.db), _principal(args), args.assessment_id, args.out_dir, iso(_fixed_clock(args.now)()))
    print(json.dumps(verify_package(out)))


def cmd_verify(args):
    res = verify_package(args.package)
    print(json.dumps(res))
    sys.exit(0 if res["ok"] else 2)


def cmd_correct(args):
    changes = dict(kv.split("=", 1) for kv in args.set)
    v = Store(args.db).apply_correction(args.sheet, args.key, changes, args.recorded_at, args.actor, args.reason)
    print(json.dumps({"sheet": args.sheet, "record_key": args.key, "new_version": v}))


def _summary_md(ev: dict, path: Path):
    L = ["# Assessment summary across the workbook", "", f"> {ev['warning']}", ""]
    for label in ("at_alert_reconstructed", "at_extract_2026-09-14"):
        s = ev[label]
        L += [f"## View: {label}", "", f"- Status: `{s['status']}`",
              f"- Abstaining only on pack-wide gaps (no series, no SOP content): **{s['abstain_only_on_pack_wide_gaps']}** of 420",
              "", "| case-specific blocking reason | events |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in s["case_specific_blockers"].items()]
        L += ["", "| dimension | status counts |", "|---|---|"] + [f"| {k} | {v} |" for k, v in s["dimension_status"].items()] + [""]
    h = ev["historical_vs_kernel"]
    L += ["## Historical engine/assistant output vs kernel (review candidates only)", "", "| historical rules_engine_recommendation / kernel | n |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in h["counts"].items()]
    L += ["", f"Auto-closed by the engine although the kernel finds case-specific evidence gaps: **{h['auto_closed_despite_case_specific_gaps']['n']}**. {h['note']}", ""]
    f = ev["firmware_TT-2.14.3"]
    L += ["## Firmware TT-2.14.3 (bulletin TT-CB-114)", "", f"- events {f['events']}, flagged at alert {f['flagged_at_alert']}, flagged at extract {f['flagged_at_extract']}, historically reopened {f['historically_reopened']}",
          f"- {f['note']}", ""]
    o = ev["override_reasons"]
    L += ["## The 24 written override reasons: would the kernel have surfaced the concern?", "", f"Summary: `{o['summary']}`", "",
          "| event | engine said | reviewer decided | concern | verdict | matching codes | kernel blocking reasons |", "|---|---|---|---|---|---|---|"]
    L += [f"| {r['event_id']} | {r['engine_said']} | {r['reviewer_decided']} | {r['concern']} | {r['verdict']} | {', '.join(r['kernel_codes_matching'])} | {', '.join(r['kernel_blocking'])} |" for r in o["rows"]]
    n = ev["notification_check"]
    L += ["", "## Notification clock check (rows flagged reportable in the pack)", "",
          f"- late in pack: {n['late_in_pack']}; inconsistent with kernel clock: {n['inconsistent_with_kernel_clock']}; not computable (next business day, policy incomplete): {n['not_computable_next_business_day']}", "",
          "| event | tenant | window (pack) | kernel due | hours to notify | pack within? | kernel late? | disposition days |", "|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['event_id']} | {r['tenant']} | {r['window_h_in_pack']} | {r.get('kernel_due_utc')} | {r.get('hours_to_notification', '')} | {r['pack_says_within']} | {r.get('kernel_says_late', 'n/a')} | {r.get('disposition_days', '')} |" for r in n["rows"]]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def run_all(store: Store, events, cutoff: str, clock) -> dict[str, dict]:
    p = Principal("batch-evaluator", frozenset({e.tenant_code for e in events}))
    out = {}
    for e in events:
        out[e.record_key], _ = assess_and_store(store, p, e.tenant_code, e.record_key, knowledge_cutoff=cutoff, clock=clock)
    return out


def cmd_demo(args):
    out = Path(args.out_dir)
    db = out / "kernel.sqlite"
    if db.exists():
        db.unlink()
    for sub in ("cases", "packages", "evaluation", "data_quality"):
        if (out / sub).is_dir():
            shutil.rmtree(out / sub)
    clock = _fixed_clock(args.now)
    snap = load_workbook_snapshot(args.workbook)
    store = Store(db)
    log = {"ingest": store.ingest_snapshot(snap, f"{snap.extract_date}T00:00:00Z")}
    log["ingest_again_idempotent"] = store.ingest_snapshot(snap, f"{snap.extract_date}T00:00:00Z")
    write_report(inspect(args.workbook), out / "data_quality")
    events = [r for r in snap.records if r.sheet == "01_Excursion_Events"]
    at_alert = run_all(store, events, "alert", clock)
    at_extract = run_all(store, events, EXTRACT_CUTOFF, clock)
    overrides = {r.record_key: r.payload for r in snap.records if r.sheet == "09_Override_Reasons"}
    ev = evaluate(events, at_alert, at_extract, overrides)
    _dump(ev, out / "evaluation" / "summary.json")
    _summary_md(ev, out / "evaluation" / "summary.md")

    # Selected real cases, chosen by rule from the assessments (not hard-coded outcomes).
    def first(pred):
        return next((e for e in events if pred(at_alert[e.record_key], at_extract[e.record_key])), None)
    picks = {
        "brief_case_EXC-107133": next(e for e in events if e.record_key == "EXC-107133"),
        "sop_overlap": first(lambda a, b: "SOP_REVISION_OVERLAP" in a["blocking_reasons"]),
        "unreferenced_stability_candidate": first(lambda a, b: any(f["code"] == "STABILITY_UNREFERENCED_CANDIDATE" for f in a["findings"])),
        "wrong_presentation_referenced": first(lambda a, b: any("presentation mismatch" in r for r in ((a["evidence"]["stability"]["referenced"] or {}).get("rejection_reasons") or []))),
        "firmware_learned_after_alert": first(lambda a, b: "FIRMWARE_BULLETIN_APPLIES" not in {f["code"] for f in a["findings"]} and "FIRMWARE_BULLETIN_APPLIES" in {f["code"] for f in b["findings"]}),
        "product_ref_missing": first(lambda a, b: "PRODUCT_REF_MISSING" in a["blocking_reasons"]),
        "product_ambiguous": first(lambda a, b: "PRODUCT_AMBIGUOUS" in a["blocking_reasons"]),
        "next_business_day_policy_incomplete": first(lambda a, b: a["notification_track"]["status"] == "POLICY_INCOMPLETE_ESCALATE"),
    }
    cases = {}
    for label, e in picks.items():
        if e is None:
            cases[label] = None
            continue
        a, b = at_alert[e.record_key], at_extract[e.record_key]
        cases[label] = {"event_id": e.record_key, "tenant": e.tenant_code, "at_alert": a["assessment_id"], "at_extract": b["assessment_id"],
                        "status_at_alert": a["disposition_evidence_status"], "blocking_at_alert": a["blocking_reasons"],
                        "supersession": b.get("change_from_superseded")}
        _dump(a, out / "cases" / f"{e.record_key}_at_alert.json")
        _dump(b, out / "cases" / f"{e.record_key}_at_extract.json")
        export_package(store, Principal("demo-qa", frozenset({e.tenant_code})), a["assessment_id"], out / "packages", iso(clock()))
    log["selected_cases"] = cases

    # Correction demo: a SIMULATED source correction (labelled), never presented as real.
    target = picks["brief_case_EXC-107133"]
    orig = store.get_assessment_row(at_alert[target.record_key]["assessment_id"])
    pm_row = next(r for r in store.records("02_Product_Master", tenant="T-KAVERI") if r.get("stability_study_ref") == "STB-3584")
    v = store.apply_correction("02_Product_Master", pm_row.record_key, {"stability_study_ref": "STB-2738"},
                               "2026-09-20T10:00:00Z", "SIMULATED-QA-DEMO",
                               "SIMULATED correction for demonstration: point the pen product at the pen excursion study")
    corrected, _ = assess_and_store(store, Principal("demo-qa", frozenset({"T-KAVERI"})), "T-KAVERI", target.record_key,
                                    knowledge_cutoff="2026-09-21T00:00:00Z", clock=clock)
    orig_after = store.get_assessment_row(orig["assessment_id"])
    log["correction_demo"] = {"label": "SIMULATED correction (not a real Kestrel change)", "record": f"02_Product_Master/{pm_row.record_key}",
                              "new_source_version": v, "original_assessment": orig["assessment_id"],
                              "original_payload_sha256_before": orig["payload_sha256"], "original_payload_sha256_after": orig_after["payload_sha256"],
                              "original_unchanged": orig["payload_json"] == orig_after["payload_json"],
                              "new_assessment": corrected["assessment_id"], "supersedes": corrected.get("supersedes"),
                              "change": corrected.get("change_from_superseded")}
    _dump(corrected, out / "cases" / f"{target.record_key}_after_simulated_correction.json")
    # Replay of the original assessment after the correction reproduces the same id (knowledge cutoff excludes the correction).
    replay = build_assessment(store, Principal("demo-qa", frozenset({"T-KAVERI"})), "T-KAVERI", target.record_key,
                              knowledge_cutoff="alert", mode="RECONSTRUCTED", clock=clock)
    log["correction_demo"]["replay_at_alert_after_correction_same_id"] = replay["assessment_id"] == orig["assessment_id"]
    # Tenant isolation demo
    try:
        build_assessment(store, Principal("pinnacle-reviewer", frozenset({"T-PINNACLE"})), "T-MERIDIAN",
                         next(e.record_key for e in events if e.tenant_code == "T-MERIDIAN"))
        log["isolation_demo"] = "FAILED: cross-tenant read allowed"
    except TenantAccessDenied as exc:
        log["isolation_demo"] = f"DENIED as expected: {exc}"
    log["audit_denials"] = len([a for a in store.audit_events() if a["outcome"] == "DENIED"])
    log["packages_verified"] = [verify_package(p) for p in sorted((out / "packages").iterdir())]
    _dump(log, out / "demo_run.json")
    print(json.dumps({k: log[k] for k in ("ingest", "ingest_again_idempotent", "isolation_demo", "audit_denials")}, indent=1))
    print(json.dumps(log["correction_demo"], indent=1, default=str))
    print(f"assessments stored: {store.db.execute('select count(*) from assessment').fetchone()[0]}; outputs in {out}")


def main(argv=None):
    # Windows consoles and redirected output default to a legacy code page; results contain "°" and "—".
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="kccs-evidence")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("--workbook", required=True); s.add_argument("--db", default=DEFAULT_DB); s.add_argument("--recorded-at"); s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("inspect"); s.add_argument("--workbook", required=True); s.add_argument("--out-dir", default="artifacts/data_quality"); s.set_defaults(fn=cmd_inspect)
    s = sub.add_parser("assess"); s.add_argument("--db", default=DEFAULT_DB); s.add_argument("--tenant", required=True); s.add_argument("--event", required=True)
    s.add_argument("--actor", default="cli-reviewer"); s.add_argument("--tenant-scope", help="comma list of tenants the actor may access (default: --tenant)")
    s.add_argument("--knowledge-cutoff", default="alert", help="alert | now | ISO-8601 UTC"); s.add_argument("--mode", default="RECONSTRUCTED", choices=["RECONSTRUCTED", "STRICT"])
    s.add_argument("--now"); s.add_argument("--out"); s.set_defaults(fn=cmd_assess)
    s = sub.add_parser("export-package"); s.add_argument("--db", default=DEFAULT_DB); s.add_argument("--assessment-id", required=True); s.add_argument("--out-dir", default="artifacts/packages")
    s.add_argument("--actor", default="cli-reviewer"); s.add_argument("--tenant-scope", required=True); s.add_argument("--tenant"); s.add_argument("--now"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("verify-package"); s.add_argument("package"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("correct"); s.add_argument("--db", default=DEFAULT_DB); s.add_argument("--sheet", required=True); s.add_argument("--key", required=True)
    s.add_argument("--set", nargs="+", required=True, metavar="COL=VALUE"); s.add_argument("--reason", required=True); s.add_argument("--actor", required=True); s.add_argument("--recorded-at", required=True); s.set_defaults(fn=cmd_correct)
    s = sub.add_parser("demo"); s.add_argument("--workbook", required=True); s.add_argument("--out-dir", default="artifacts"); s.add_argument("--now", default="2026-11-08T12:00:00Z"); s.set_defaults(fn=cmd_demo)
    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except TenantAccessDenied as exc:
        print(f"ACCESS DENIED: {exc}", file=sys.stderr)
        sys.exit(3)
    except KeyError as exc:
        msg = exc.args[0] if exc.args else exc
        hint = ""
        if getattr(args, "db", None):
            hint = (f" (database: {args.db}. Load the workbook into it first with "
                    f"`kccs-evidence ingest --workbook <file> --db {args.db}`.)")
        print(f"NOT FOUND: {msg}{hint}", file=sys.stderr)
        sys.exit(4)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
