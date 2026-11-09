"""Time semantics.

* Pack timestamps ("YYYY-MM-DD HH:MM") in 01_Excursion_Events are UTC per
  00_README!R31. They are parsed as aware UTC; the original string is kept.
* Policy effective dates are date-only. They are interpreted as half-open
  intervals of *local calendar dates at the governed site*: [effective_from,
  effective_to). Evidence: in 05_SOP_Index a revision's effective_to equals the
  next revision's effective_from, so a closed interval would make every
  hand-over a one-day overlap. A blank effective_to is open-ended.
* Knowledge time (recorded_at) is when this system learned a fact. It is never
  inferred from valid time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

UTC = UTC
OPEN_END = date.max


def parse_pack_utc(text: str) -> datetime:
    if not isinstance(text, str):
        raise ValueError(f"Expected pack timestamp string, got {text!r}")
    return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def parse_iso_utc(text: str) -> datetime:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timestamp must carry a timezone: {text}")
    return dt.astimezone(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(text: str | None) -> date | None:
    if text in (None, ""):
        return None
    return date.fromisoformat(str(text).strip())


def parse_effective_to(text: str | None) -> date:
    if text in (None, "", "evergreen"):
        return OPEN_END
    return date.fromisoformat(str(text).strip())


def in_half_open(d: date, start: date, end: date) -> bool:
    return start <= d < end


def local_date(dt: datetime, tz_name: str) -> date:
    return dt.astimezone(ZoneInfo(tz_name)).date()


def plausible_local_dates(dt: datetime, tz_name: str | None, tz_trusted: bool) -> tuple[set[date], str]:
    """Dates on which `dt` may fall at the site.

    With a trusted site timezone there is one date. Otherwise every date the
    instant falls on anywhere between UTC-12 and UTC+14 is plausible, and the
    caller must treat a selection that differs across them as ambiguous.
    """
    if tz_name and tz_trusted:
        return {local_date(dt, tz_name)}, f"site timezone {tz_name}"
    dates = {(dt + timedelta(hours=h)).date() for h in range(-12, 15)}
    why = f"site timezone {tz_name} not trusted" if tz_name else "site timezone unknown"
    return dates, why + "; evaluated all dates between UTC-12 and UTC+14"
