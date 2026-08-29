"""
app/services/place_cache.py
---------------------------
Reading and expiring the bounded coordinate cache on `PlaceRef`.

Google Maps Platform terms permit storing `place_id` indefinitely but allow
latitude/longitude to be cached for a bounded period only, and forbid retaining
display fields at all (`INV-CACHE-1`, report §8.4). `PlaceRef` already has no
display columns; what this module adds is the other half of that invariant --
the expiry actually happening -- and the read path `INV-CACHE-2` requires,
where a stale coordinate is treated as absent rather than served.

`coord_retention` is a required argument on every function here, for the reason
given under `INV-CACHE-2`: the window is set by Google's then-current policy and
changes. A module constant would be a number nobody re-verifies.
"""

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

from app.domain.models import PlaceRef

logger = logging.getLogger(__name__)


def coordinates(
    place: PlaceRef, now: datetime, coord_retention: timedelta
) -> tuple[float, float] | None:
    """Cached coordinates, or None if they are absent or past retention.

    Returning None is the signal to refetch from Places. There is deliberately
    no "return the stale value and refresh in the background" path: that serves
    expired data, which is what INV-CACHE-2 forbids.
    """
    if place.needs_refresh(now, coord_retention):
        return None
    if place.cached_lat is None or place.cached_lng is None:
        return None
    return (place.cached_lat, place.cached_lng)


def expire_coordinates(place: PlaceRef) -> None:
    """Drop a single cache entry's coordinates, in place.

    Clears `coords_cached_at` alongside the values so that the row cannot be
    mistaken for "cached, at the origin".
    """
    place.cached_lat = None
    place.cached_lng = None
    place.coords_cached_at = None


def purge_expired_coordinates(
    places: Iterable[PlaceRef], now: datetime, coord_retention: timedelta
) -> int:
    """Expire every cache entry past its retention window.

    Returns the number of entries cleared. `place_id` and `last_refreshed_at`
    are untouched: the pointer into Google's catalogue may be kept
    indefinitely, only the coordinates are time-bounded.

    Reading through the gate in `coordinates` already refuses to serve a stale
    value, so this is defence in depth rather than the only enforcement -- but
    INV-CACHE-1 asks that expired entries are *purged*, not merely unread, and
    an unread row is still a retained row.
    """
    cleared = 0
    for place in places:
        if place.coords_cached_at is None:
            continue
        if place.needs_refresh(now, coord_retention):
            expire_coordinates(place)
            cleared += 1
    if cleared:
        logger.info("Expired coordinates for %d cached place references.", cleared)
    return cleared
