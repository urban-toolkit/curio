"""Place search for the area field: a name in, boxes and OSM area names out.

Every source that takes an ``area`` shares this one search, so a place is
found the same way whichever source asks. It is Nominatim, OpenStreetMap's
geocoder, reached through the Discovery Catalog's transport and so through the
egress policy, with the usage policy Nominatim asks of every client: a named
User-Agent, at most one request a second from this server, and answers kept
rather than asked for again.

Each answer gives what both forms of an area need:

- ``box``: ``[west, south, east, north]`` in WGS84, for a box;
- ``name`` and ``boundary``: the place's own OSM name, in the local language
  (Köln, where the English ``label`` says Cologne), and whether it is an
  administrative boundary, which is what a named area must be.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.parse import quote

from utk_curio.backend.app.discovery.domain.errors import ProviderError

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "Curio Discovery Catalog (https://curio.urbantk.org)"

MAX_QUERY_LENGTH = 200
MAX_RESULTS = 8
#: Nominatim's own rule: no more than one request a second from one client.
MIN_INTERVAL_S = 1.0
CACHE_TTL_S = 24 * 60 * 60
CACHE_ENTRIES = 256

#: Guards the cache and the next free slot. Held for neither the wait nor the
#: request, so a cached place is answered while another search waits.
_lock = threading.Lock()
#: When the next request may leave.
_next_slot = 0.0
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def search_url(query: str) -> str:
    """The search, with each place's own OSM names (``namedetails``), since
    ``name`` follows the request's language."""
    return f"{NOMINATIM}/search?format=jsonv2&limit={MAX_RESULTS}&namedetails=1&q={quote(query, safe='')}"


def search_places(transport, query: str) -> list[dict[str, Any]]:
    """Places matching *query*, best first. Raises ``ProviderError`` when
    Nominatim cannot be read."""
    text = " ".join(str(query or "").split())[:MAX_QUERY_LENGTH]
    if not text:
        return []
    key = text.lower()
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < CACHE_TTL_S:
            return hit[1]
        slot = _take_slot()
    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    payload = transport.json_get(
        search_url(text),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
    )
    places = _rows(payload)
    with _lock:
        if len(_cache) >= CACHE_ENTRIES:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), places)
    return places


def reset() -> None:
    """Forget the cache and the next slot: for tests."""
    global _next_slot
    with _lock:
        _cache.clear()
        _next_slot = 0.0


def _take_slot() -> float:
    """When this search's request may leave: a second after the one before.

    Called with ``_lock`` held, so two searches never take the same second;
    the caller waits for its slot after letting go of the lock.
    """
    global _next_slot
    slot = max(time.monotonic(), _next_slot)
    _next_slot = slot + MIN_INTERVAL_S
    return slot


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise ProviderError("the place search did not answer with JSON") from exc
    if not isinstance(payload, list):
        raise ProviderError("the place search did not answer with a list")
    out = []
    for entry in payload[:MAX_RESULTS]:
        if not isinstance(entry, dict):
            continue
        box = _box(entry.get("boundingbox"))
        if box is None:
            continue
        label = str(entry.get("display_name") or "")[:300]
        # OpenStreetMap's ``name`` tag, which a named area is matched against.
        details = entry.get("namedetails") if isinstance(entry.get("namedetails"), dict) else {}
        name = str(details.get("name") or entry.get("name") or label.split(",")[0]).strip()[:120]
        if not name:
            continue
        out.append({
            "name": name,
            "label": label or name,
            "box": box,
            "kind": f"{entry.get('category') or ''}/{entry.get('type') or ''}".strip("/"),
            # A named area in OSM is an administrative boundary relation.
            "boundary": entry.get("category") == "boundary" and entry.get("osm_type") == "relation",
        })
    return out


def _box(raw: Any) -> list[float] | None:
    """Nominatim's ``[south, north, west, east]`` as ``[west, south, east, north]``."""
    try:
        south, north, west, east = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        return None
    return [round(west, 6), round(south, 6), round(east, 6), round(north, 6)]
