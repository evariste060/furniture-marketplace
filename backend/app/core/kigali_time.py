"""Africa/Kigali local time (module 13; plan §5 and §7 Q25; RE-026 B3).

Promotion start and end dates are entered in Kigali time and stored in UTC. A date-time without
an offset is read as Kigali local time; one with an offset is taken as the exact instant it names.
The zone database comes from the tzdata package, because Windows has none.

Kigali has used a fixed UTC+02:00 offset with no daylight saving since 1935, so no local time is
ambiguous or missing there. The checks below are generic all the same: a local time that a zone
transition makes ambiguous (it occurs twice) or nonexistent (it is skipped) is refused, never
guessed.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

KIGALI = ZoneInfo("Africa/Kigali")


class AmbiguousLocalTime(ValueError):
    pass


class NonexistentLocalTime(ValueError):
    pass


def local_to_utc(value: datetime, zone: ZoneInfo = KIGALI) -> datetime:
    """The UTC instant of a date-time; one without an offset is local time in `zone`."""
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(UTC)
    first = value.replace(tzinfo=zone, fold=0)
    instant = first.astimezone(UTC)
    # A skipped local time does not survive the round trip (both folds differ there too, so this
    # check comes first); a repeated one does, but its two folds have different offsets.
    if instant.astimezone(zone).replace(tzinfo=None) != value:
        raise NonexistentLocalTime(f"{value.isoformat()} does not exist in {zone.key}.")
    if first.utcoffset() != value.replace(tzinfo=zone, fold=1).utcoffset():
        raise AmbiguousLocalTime(
            f"{value.isoformat()} occurs twice in {zone.key}; send it with its UTC offset."
        )
    return instant


def to_kigali(value: datetime | None) -> datetime | None:
    """A stored UTC instant shown in Kigali time (the same instant, with a +02:00 offset)."""
    return value.astimezone(KIGALI) if value is not None else None
