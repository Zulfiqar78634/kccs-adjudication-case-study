"""Tenant access control: every evidence read goes through a TenantView.

Isolation is enforced *before* retrieval: tenant-scoped sheets are filtered in
SQL by tenant_code, caches live on the view (so they are tenant-keyed by
construction), and evaluation-only data (reviewer logs, override reasons,
historical outcomes) is not reachable from this interface at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .config_loader import load_config
from .store import Store, VersionedRecord
from .temporal import UTC, iso

SHARED_SHEETS = {"03_Facility_Registry", "04_Carrier_Contracts", "11_Systems_Inventory", "14_Incident_Log"}
TENANT_SHEETS = {"01_Excursion_Events", "02_Product_Master", "05_SOP_Index", "06_Stability_Index", "12_Tenant_Constraints"}
KESTREL_OWNED_ALIAS_KINDS = {"FACILITY", "CARRIER"}


class TenantAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    actor_id: str
    tenants: frozenset[str]
    roles: frozenset[str] = frozenset({"QA_REVIEWER"})


def system_clock() -> datetime:
    return datetime.now(UTC)


@dataclass
class TenantView:
    store: Store
    principal: Principal
    tenant: str
    as_known_at: str | None = None  # store cutoff (recorded_at) as ISO UTC; None = now
    clock: Callable[[], datetime] = system_clock
    knowledge_cutoff: str | None = None  # true knowledge cutoff for human assertions; defaults to as_known_at
    _cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.tenant not in self.principal.tenants:
            self.store.audit(
                at=iso(self.clock()),
                actor=self.principal.actor_id,
                tenant=self.tenant,
                action="TENANT_VIEW_OPEN",
                target=self.tenant,
                outcome="DENIED",
                detail={"principal_tenants": sorted(self.principal.tenants)},
            )
            raise TenantAccessDenied(f"{self.principal.actor_id} is not authorised for {self.tenant}")

    def tenant_records(self, sheet: str) -> list[VersionedRecord]:
        if sheet not in TENANT_SHEETS:
            raise TenantAccessDenied(f"{sheet} is not a tenant-scoped evidence sheet")
        key = ("t", sheet)
        if key not in self._cache:
            self._cache[key] = self.store.records(sheet, tenant=self.tenant, as_known_at=self.as_known_at)
        return self._cache[key]

    def shared_records(self, sheet: str) -> list[VersionedRecord]:
        if sheet not in SHARED_SHEETS:
            raise TenantAccessDenied(f"{sheet} is not shared reference data")
        key = ("s", sheet)
        if key not in self._cache:
            self._cache[key] = self.store.records(sheet, shared=True, as_known_at=self.as_known_at)
        return self._cache[key]

    def alias_observations(self, kind: str) -> list[VersionedRecord]:
        """Unattributed platform alias observations, only for Kestrel-owned entity kinds."""
        if kind not in KESTREL_OWNED_ALIAS_KINDS:
            policy = load_config("reference_facts.json")["product_alias_policy"]["value"]
            raise TenantAccessDenied(f"alias observations of kind {kind} are blocked by policy {policy}")
        key = ("a", kind)
        if key not in self._cache:
            rows = self.store.records("07_Alias_Observations", shared=True, as_known_at=self.as_known_at)
            self._cache[key] = [r for r in rows if r.get("entity_kind") == kind]
        return self._cache[key]

    def mappings(self, kind: str) -> list[dict]:
        return self.store.mappings(kind, self.tenant, self.knowledge_cutoff or self.as_known_at)

    def event(self, event_id: str) -> VersionedRecord:
        for r in self.tenant_records("01_Excursion_Events"):
            if r.record_key == event_id:
                return r
        # Do not reveal whether the event exists under another tenant.
        self.store.audit(
            at=iso(self.clock()), actor=self.principal.actor_id, tenant=self.tenant, action="EVENT_READ", target=event_id, outcome="NOT_FOUND_IN_TENANT"
        )
        raise KeyError(f"{event_id} not found for tenant {self.tenant}")
