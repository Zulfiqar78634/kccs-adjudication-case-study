"""Append-only SQLite persistence with bitemporal source versions.

* source_record_version: one row per (sheet, record_key, version). A correction
  or a changed re-ingest adds a version; nothing is updated or deleted.
  `recorded_at` is knowledge time (when this system learned the version).
* mapping_assertion: human-approved entity mappings (versioned, append-only).
* assessment: content-addressed, immutable assessment payloads.
* audit_event: append-only audit log, including access denials.

UPDATE/DELETE on these tables are rejected by triggers, so immutability does not
depend on application discipline.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import STORE_SCHEMA_VERSION
from .sources import SourceRecord, SourceSnapshot, canonical_json, sha256_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_snapshot (
  snapshot_id TEXT PRIMARY KEY, file_name TEXT NOT NULL, file_sha256 TEXT NOT NULL,
  extract_date TEXT, recorded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_record_version (
  sheet TEXT NOT NULL, record_key TEXT NOT NULL, version INTEGER NOT NULL,
  excel_row INTEGER NOT NULL, tenant_code TEXT, attribution TEXT NOT NULL,
  payload_json TEXT NOT NULL, row_hash TEXT NOT NULL, snapshot_id TEXT,
  recorded_at TEXT NOT NULL, change_kind TEXT NOT NULL,        -- INGEST | CORRECTION
  change_reason TEXT, actor TEXT,
  PRIMARY KEY (sheet, record_key, version));
CREATE INDEX IF NOT EXISTS ix_srv_tenant ON source_record_version(sheet, tenant_code, recorded_at);
CREATE TABLE IF NOT EXISTS mapping_assertion (
  assertion_id TEXT PRIMARY KEY, tenant_code TEXT, entity_kind TEXT NOT NULL,
  source_string TEXT NOT NULL, canonical_id TEXT NOT NULL, decision TEXT NOT NULL, -- APPROVED | REJECTED
  actor TEXT NOT NULL, recorded_at TEXT NOT NULL, evidence_ref TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS assessment (
  assessment_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, tenant_code TEXT NOT NULL,
  valid_at TEXT NOT NULL, knowledge_cutoff TEXT NOT NULL, supersedes TEXT,
  payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL, first_stored_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_assessment_event ON assessment(tenant_code, event_id);
CREATE TABLE IF NOT EXISTS audit_event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
  tenant_code TEXT, action TEXT NOT NULL, target TEXT, outcome TEXT NOT NULL, detail_json TEXT);
"""
IMMUTABLE_TABLES = ("source_snapshot", "source_record_version", "mapping_assertion", "assessment", "audit_event")


class ImmutableRecordError(RuntimeError):
    pass


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        for t in IMMUTABLE_TABLES:
            for op in ("UPDATE", "DELETE"):
                self.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS trg_{t}_no_{op.lower()} BEFORE {op} ON {t} "
                    f"BEGIN SELECT RAISE(ABORT, 'append-only table {t}: {op} rejected'); END")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(STORE_SCHEMA_VERSION),))
        self.db.commit()

    # ---------------- source records ----------------
    def ingest_snapshot(self, snap: SourceSnapshot, recorded_at: str) -> dict[str, int]:
        stats = {"new_records": 0, "new_versions": 0, "unchanged": 0}
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO source_snapshot VALUES (?,?,?,?,?)",
                            (snap.snapshot_id, snap.file_name, snap.file_sha256, snap.extract_date, recorded_at))
            for rec in snap.records:
                latest = self._latest_version_row(rec.sheet, rec.record_key)
                if latest is None:
                    self._insert_version(rec, 1, snap.snapshot_id, recorded_at, "INGEST", None, "ingest")
                    stats["new_records"] += 1
                elif latest["row_hash"] == rec.row_hash:
                    stats["unchanged"] += 1
                else:
                    self._insert_version(rec, latest["version"] + 1, snap.snapshot_id, recorded_at,
                                         "INGEST", "changed in later snapshot", "ingest")
                    stats["new_versions"] += 1
        return stats

    def apply_correction(self, sheet: str, record_key: str, changes: dict[str, Any], recorded_at: str,
                         actor: str, reason: str) -> int:
        latest = self._latest_version_row(sheet, record_key)
        if latest is None:
            raise KeyError(f"No source record {sheet}/{record_key}")
        payload = json.loads(latest["payload_json"])
        unknown = [c for c in changes if c not in payload]
        if unknown:
            raise ValueError(f"Correction names columns not in source record: {unknown}")
        payload.update(changes)
        rec = SourceRecord(sheet=sheet, record_key=record_key, excel_row=latest["excel_row"],
                           tenant_code=latest["tenant_code"], attribution=latest["attribution"], payload=payload,
                           row_hash=sha256_text(canonical_json({"sheet": sheet, "payload": payload})))
        version = latest["version"] + 1
        with self.db:
            self._insert_version(rec, version, None, recorded_at, "CORRECTION", reason, actor)
        return version

    def _insert_version(self, rec: SourceRecord, version: int, snapshot_id: str | None, recorded_at: str,
                        kind: str, reason: str | None, actor: str) -> None:
        self.db.execute(
            "INSERT INTO source_record_version VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec.sheet, rec.record_key, version, rec.excel_row, rec.tenant_code, rec.attribution,
             canonical_json(rec.payload), rec.row_hash, snapshot_id, recorded_at, kind, reason, actor))

    def _latest_version_row(self, sheet: str, key: str):
        return self.db.execute(
            "SELECT * FROM source_record_version WHERE sheet=? AND record_key=? ORDER BY version DESC LIMIT 1",
            (sheet, key)).fetchone()

    def records(self, sheet: str, *, tenant: str | None = None, shared: bool = False,
                as_known_at: str | None = None) -> list["VersionedRecord"]:
        """Latest version per key known at `as_known_at` (ISO UTC; None = now).

        Exactly one of tenant / shared must be given: tenant-scoped sheets are
        filtered in SQL, never after retrieval.
        """
        if (tenant is None) == (not shared):
            raise ValueError("records() requires exactly one of tenant=... or shared=True")
        cutoff = as_known_at or "9999-12-31T23:59:59Z"
        q = ("SELECT v.* FROM source_record_version v WHERE v.sheet=? AND v.recorded_at<=? "
             "AND v.version = (SELECT MAX(version) FROM source_record_version w WHERE w.sheet=v.sheet "
             "AND w.record_key=v.record_key AND w.recorded_at<=?)")
        args: list[Any] = [sheet, cutoff, cutoff]
        if tenant is not None:
            q += " AND v.tenant_code=?"
            args.append(tenant)
        else:
            q += " AND v.tenant_code IS NULL"
        q += " ORDER BY v.excel_row"
        return [VersionedRecord.from_row(r) for r in self.db.execute(q, args)]

    def record_history(self, sheet: str, key: str) -> list["VersionedRecord"]:
        return [VersionedRecord.from_row(r) for r in self.db.execute(
            "SELECT * FROM source_record_version WHERE sheet=? AND record_key=? ORDER BY version", (sheet, key))]

    def snapshots(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM source_snapshot ORDER BY recorded_at")]

    # ---------------- mapping assertions ----------------
    def add_mapping(self, *, assertion_id: str, tenant: str | None, kind: str, source_string: str,
                    canonical_id: str, decision: str, actor: str, recorded_at: str,
                    evidence_ref: str | None = None, note: str | None = None) -> None:
        if decision not in ("APPROVED", "REJECTED"):
            raise ValueError("decision must be APPROVED or REJECTED")
        with self.db:
            self.db.execute("INSERT INTO mapping_assertion VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (assertion_id, tenant, kind, source_string, canonical_id, decision, actor,
                             recorded_at, evidence_ref, note))

    def mappings(self, kind: str, tenant: str | None, as_known_at: str | None) -> list[dict[str, Any]]:
        cutoff = as_known_at or "9999-12-31T23:59:59Z"
        q = "SELECT * FROM mapping_assertion WHERE entity_kind=? AND recorded_at<=? AND "
        q += "(tenant_code IS NULL OR tenant_code=?)" if tenant else "tenant_code IS NULL"
        args = [kind, cutoff] + ([tenant] if tenant else [])
        return [dict(r) for r in self.db.execute(q + " ORDER BY recorded_at", args)]

    # ---------------- assessments ----------------
    def put_assessment(self, payload: dict[str, Any], stored_at: str) -> tuple[str, bool]:
        aid = payload["assessment_id"]
        body = canonical_json(payload)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO assessment VALUES (?,?,?,?,?,?,?,?,?)",
            (aid, payload["event"]["event_id"], payload["event"]["tenant_code"], payload["time_semantics"]["valid_at"],
             payload["time_semantics"]["knowledge_cutoff"], payload.get("supersedes"), body, sha256_text(body), stored_at))
        self.db.commit()
        return aid, cur.rowcount == 1

    def get_assessment_row(self, assessment_id: str):
        return self.db.execute("SELECT * FROM assessment WHERE assessment_id=?", (assessment_id,)).fetchone()

    def assessments_for_event(self, tenant: str, event_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM assessment WHERE tenant_code=? AND event_id=? ORDER BY first_stored_at, assessment_id",
            (tenant, event_id))]

    # ---------------- audit ----------------
    def audit(self, *, at: str, actor: str, tenant: str | None, action: str, target: str | None,
              outcome: str, detail: dict[str, Any] | None = None) -> None:
        with self.db:
            self.db.execute("INSERT INTO audit_event (at, actor, tenant_code, action, target, outcome, detail_json) "
                            "VALUES (?,?,?,?,?,?,?)", (at, actor, tenant, action, target, outcome,
                                                       canonical_json(detail or {})))

    def audit_events(self, action: str | None = None) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM audit_event", []
        if action:
            q, args = q + " WHERE action=?", [action]
        return [dict(r) for r in self.db.execute(q + " ORDER BY seq", args)]

    def raw_execute(self, sql: str, args: Iterable[Any] = ()):  # used by tests to prove triggers
        cur = self.db.execute(sql, tuple(args))
        self.db.commit()
        return cur


@dataclass(frozen=True)
class VersionedRecord(SourceRecord):
    version: int = 1
    recorded_at: str = ""
    change_kind: str = "INGEST"

    @classmethod
    def from_row(cls, r) -> "VersionedRecord":
        return cls(sheet=r["sheet"], record_key=r["record_key"], excel_row=r["excel_row"],
                   tenant_code=r["tenant_code"], attribution=r["attribution"],
                   payload=json.loads(r["payload_json"]), row_hash=r["row_hash"],
                   version=r["version"], recorded_at=r["recorded_at"], change_kind=r["change_kind"])
