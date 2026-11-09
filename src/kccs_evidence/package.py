"""Evidence package export and verification.

A package is a directory containing the stored assessment, the exact source
record versions it cites (event row restricted to allowed input fields), the
audit trail for the event, and MANIFEST.json listing every file's SHA-256 plus
a package digest. `verify_package` recomputes all hashes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .access import Principal, TenantAccessDenied
from .assessment import ALLOWED_EVENT_FIELDS
from .sources import canonical_json, sha256_text
from .store import Store


def _write(path: Path, obj: Any) -> str:
    # Write bytes, not text: text mode on Windows turns "\n" into "\r\n", so the file
    # would no longer match the hash of the text it was written from.
    data = (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n").encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def export_package(store: Store, principal: Principal, assessment_id: str, out_dir: str | Path, exported_at: str) -> Path:
    row = store.get_assessment_row(assessment_id)
    if row is None:
        raise KeyError(assessment_id)
    if row["tenant_code"] not in principal.tenants:
        store.audit(at=exported_at, actor=principal.actor_id, tenant=row["tenant_code"], action="PACKAGE_EXPORT",
                    target=assessment_id, outcome="DENIED")
        raise TenantAccessDenied(f"{principal.actor_id} may not export {assessment_id}")
    if sha256_text(row["payload_json"]) != row["payload_sha256"]:
        raise ValueError(f"stored assessment {assessment_id} fails its integrity hash")
    payload = json.loads(row["payload_json"])
    tenant = row["tenant_code"]
    out = Path(out_dir) / assessment_id
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {"assessment.json": _write(out / "assessment.json", payload)}
    cited = []
    for item in payload["manifest"]["cited_source_versions"]:
        ident, _ = item.split(":", 1)
        sheet_key, ver = ident.rsplit("@v", 1)
        sheet, key = sheet_key.split("/", 1)
        for v in store.record_history(sheet, key):
            if v.version == int(ver):
                if v.tenant_code not in (None, tenant):
                    raise TenantAccessDenied("package would include another tenant's record")
                cited.append({"sheet": sheet, "record_key": key, "version": v.version, "excel_row": v.excel_row,
                              "recorded_at": v.recorded_at, "change_kind": v.change_kind, "row_hash": v.row_hash, "payload": v.payload})
    event_hist = store.record_history("01_Excursion_Events", payload["event"]["event_id"])
    event_versions = [{"version": v.version, "excel_row": v.excel_row, "recorded_at": v.recorded_at,
                       "allowed_fields": {k: v.payload.get(k) for k in ALLOWED_EVENT_FIELDS}} for v in event_hist if v.tenant_code == tenant]
    files["source_records.json"] = _write(out / "source_records.json", {"event": event_versions, "cited": cited})
    audit = [a for a in store.audit_events() if a["tenant_code"] == tenant and payload["event"]["event_id"] in (a["detail_json"] or "") + (a["target"] or "")]
    files["audit_trail.json"] = _write(out / "audit_trail.json", audit)
    files["README.txt"] = _write(out / "README.txt", {
        "what": "Evidence package for one assessment. This is a reviewer aid / abstention record, not a disposition.",
        "verify": "python -m kccs_evidence.cli verify-package <this directory>"})
    digest = sha256_text(canonical_json(files))
    _write(out / "MANIFEST.json", {"assessment_id": assessment_id, "tenant_code": tenant, "exported_at": exported_at,
                                   "exported_by": principal.actor_id, "files_sha256": files, "package_digest": digest})
    store.audit(at=exported_at, actor=principal.actor_id, tenant=tenant, action="PACKAGE_EXPORT", target=assessment_id,
                outcome="EXPORTED", detail={"package_digest": digest})
    return out


def verify_package(pkg_dir: str | Path) -> dict[str, Any]:
    pkg = Path(pkg_dir)
    manifest = json.loads((pkg / "MANIFEST.json").read_text(encoding="utf-8"))
    problems = []
    for name, expected in manifest["files_sha256"].items():
        p = pkg / name
        if not p.exists():
            problems.append(f"missing {name}")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"hash mismatch {name}")
    if sha256_text(canonical_json(manifest["files_sha256"])) != manifest["package_digest"]:
        problems.append("package digest mismatch")
    return {"package": str(pkg), "ok": not problems, "problems": problems, "package_digest": manifest["package_digest"]}
