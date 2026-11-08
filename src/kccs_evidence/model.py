"""Result types shared by the evidence modules."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

BLOCKING, REVIEW, INFO = "BLOCKING", "REVIEW", "INFO"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str                  # BLOCKING prevents READY_FOR_QA_REVIEW; REVIEW needs a human look; INFO context
    dimension: str                 # identity | policy | stability | telemetry | firmware | liability | notification | history | attribution | knowledge
    message: str
    source_refs: tuple[str, ...] = ()
    human_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_refs"] = list(self.source_refs)
        return d


@dataclass
class Resolution:
    kind: str                      # PRODUCT | FACILITY | CARRIER
    role: str                      # e.g. product, origin, destination, carrier
    input_value: Any               # original string exactly as received
    status: str                    # RESOLVED | RESOLVED_PROVISIONAL | AMBIGUOUS | UNRESOLVED | MISSING_INPUT
    resolved_id: str | None = None
    basis: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status in ("RESOLVED", "RESOLVED_PROVISIONAL")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def norm(text: Any) -> str:
    """Comparison key only; the original value is always retained separately."""
    if text is None:
        return ""
    return " ".join(str(text).casefold().split())
