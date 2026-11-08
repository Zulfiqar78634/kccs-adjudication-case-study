"""Workbook ingestion: every row becomes an immutable, hashed source record.

Original cell values are preserved exactly (strings stay strings, so GTIN
leading zeros survive). Nothing is cleaned here; interpretation happens later
and always cites the source reference (sheet + Excel row).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

# Sheet -> (record-key column or None for row-number keys, tenant column or None, attribution class)
# SHARED_REFERENCE = Kestrel-owned reference data (facilities, carrier contracts...).
# UNATTRIBUTED = platform data with no tenant provenance (alias observations).
SHEETS: dict[str, tuple[str | None, str | None, str]] = {
    "00_README": (None, None, "DOCUMENTATION"),
    "01_Excursion_Events": ("event_id", "tenant_code", "TENANT"),
    "02_Product_Master": (None, "tenant_code", "TENANT"),
    "03_Facility_Registry": ("record_id", None, "SHARED_REFERENCE"),
    "04_Carrier_Contracts": ("contract_id", None, "SHARED_REFERENCE"),
    "05_SOP_Index": (None, "tenant_code", "TENANT"),
    "06_Stability_Index": ("study_ref", "tenant_code", "TENANT"),
    "07_Alias_Observations": (None, None, "UNATTRIBUTED"),
    "08_Reviewer_Queue_Log": ("log_id", None, "EVALUATION_ONLY"),
    "09_Override_Reasons": ("case_ref", None, "EVALUATION_ONLY"),
    "10_Reviewer_Questions": ("#", None, "DOCUMENTATION"),
    "11_Systems_Inventory": ("system_id", None, "SHARED_REFERENCE"),
    "12_Tenant_Constraints": ("tenant_code", "tenant_code", "TENANT_POLICY"),
    "13_Volume_And_Cost": (None, None, "DOCUMENTATION"),
    "14_Incident_Log": ("ref", None, "SHARED_REFERENCE"),
}
KEY_VALUE_SHEETS = {"00_README", "13_Volume_And_Cost"}


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _cell(v: Any) -> Any:
    # Keep ints/floats/strings as-is; datetimes (none expected) become ISO text, flagged by type.
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return {"__type__": type(v).__name__, "value": str(v)}


@dataclass(frozen=True)
class SourceRecord:
    sheet: str
    record_key: str
    excel_row: int
    tenant_code: str | None
    attribution: str
    payload: dict[str, Any]
    row_hash: str

    @property
    def source_ref(self) -> str:
        return f"{self.sheet}!R{self.excel_row}"

    def get(self, col: str) -> Any:
        return self.payload.get(col)


@dataclass
class SourceSnapshot:
    snapshot_id: str
    file_name: str
    file_sha256: str
    extract_date: str | None
    records: list[SourceRecord] = field(default_factory=list)
    sheet_columns: dict[str, list[str]] = field(default_factory=dict)


def load_workbook_snapshot(path: str | Path) -> SourceSnapshot:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")
    file_sha = sha256_file(path)
    wb = openpyxl.load_workbook(path, data_only=False, read_only=True)
    missing = [s for s in SHEETS if s not in wb.sheetnames]
    if missing:
        raise ValueError(f"Workbook is missing expected sheets: {missing}")
    snap = SourceSnapshot(snapshot_id=f"SNAP-{file_sha[:16]}", file_name=path.name,
                          file_sha256=file_sha, extract_date=None)
    for sheet, (key_col, tenant_col, attribution) in SHEETS.items():
        rows = list(wb[sheet].iter_rows(values_only=True))
        if sheet in KEY_VALUE_SHEETS:
            header = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"][: max(len(r) for r in rows)]
            start = 1
        else:
            header = [str(h) for h in rows[0]]
            start = 2
        snap.sheet_columns[sheet] = header
        body = rows if sheet in KEY_VALUE_SHEETS else rows[1:]
        for offset, row in enumerate(body):
            if not any(v is not None for v in row):
                continue
            excel_row = start + offset
            payload = {header[i]: _cell(row[i]) for i in range(min(len(header), len(row)))}
            if sheet == "05_SOP_Index":
                key = f"{payload.get('doc_id')} {payload.get('revision')}"
            elif key_col and payload.get(key_col) is not None:
                key = str(payload[key_col])
            else:
                key = f"R{excel_row}"
            tenant = payload.get(tenant_col) if tenant_col else None
            rec = SourceRecord(sheet=sheet, record_key=key, excel_row=excel_row,
                               tenant_code=tenant if isinstance(tenant, str) else None,
                               attribution=attribution, payload=payload,
                               row_hash=sha256_text(canonical_json({"sheet": sheet, "payload": payload})))
            snap.records.append(rec)
            if sheet == "00_README" and payload.get("c1") == "Extract date":
                snap.extract_date = str(payload.get("c2"))
    wb.close()
    return snap
