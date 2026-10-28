"""Time windows on a replayed turbine's own clock, and downsampling buckets.

Every turbine replays on its own (anonymised) data clock, and the replay loops: rows later
than the turbine's cursor are left over from the previous cycle, not the future. Windows
are therefore anchored on the cursor and never extend beyond it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

ROW = timedelta(minutes=10)
DEFAULT_SPAN = timedelta(days=7)
MAX_SPAN = timedelta(days=400)
MAX_POINTS = 2000


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    bucket: timedelta

    @property
    def bucket_seconds(self) -> int:
        return int(self.bucket.total_seconds())


def _utc(value: datetime | None) -> datetime | None:
    # A timestamp without an offset is read as UTC (the dataset's clock has no zone).
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def bucket_for(span: timedelta, points: int) -> timedelta:
    """Smallest whole number of 10-minute rows giving at most `points` buckets."""
    rows = math.ceil(span / ROW / max(points, 1))
    return ROW * max(rows, 1)


def resolve(
    cursor: datetime | None,
    start: datetime | None,
    end: datetime | None,
    points: int,
    default_span: timedelta = DEFAULT_SPAN,
    max_span: timedelta = MAX_SPAN,
) -> Window:
    if cursor is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The replay has not reached this turbine yet")
    start, end = _utc(start), _utc(end)
    end = min(end, cursor) if end else cursor
    start = start or end - default_span
    if start >= end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "`from` must be before `to` (and the cursor)"
        )
    if end - start > max_span:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Window longer than {max_span.days} days")
    return Window(start, end, bucket_for(end - start, min(points, MAX_POINTS)))
