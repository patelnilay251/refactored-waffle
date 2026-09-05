"""Overpass client.

The canonical endpoints (overpass-api.de, overpass.kumi.systems) are not
reachable from this environment, so we carry a mirror list and fall through
it. Responses are cached on disk keyed by query hash: Overpass is a shared
free service and re-running the pipeline should not re-hammer it.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

# Ordered by observed reliability from this sandbox. The first two entries of
# the "official" list are omitted deliberately: they time out here.
MIRRORS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

_USER_AGENT = "refactored-waffle/0.1 (procedural city render; OSM data via Overpass)"


class OverpassError(RuntimeError):
    pass


def _cache_path(query: str) -> Path:
    digest = hashlib.sha256(query.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.json"


def query(overpass_ql: str, *, timeout: int = 120, use_cache: bool = True) -> dict:
    """Run an Overpass QL query, falling through mirrors until one answers."""
    cache = _cache_path(overpass_ql)
    if use_cache and cache.exists():
        return json.loads(cache.read_text())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    errors = []

    for mirror in MIRRORS:
        try:
            request = urllib.request.Request(
                mirror,
                data=overpass_ql.encode(),
                headers={"User-Agent": _USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            errors.append(f"{mirror.split('/')[2]}: {type(exc).__name__}")
            time.sleep(1)
            continue

        if "elements" not in payload:
            errors.append(f"{mirror.split('/')[2]}: no elements key")
            continue

        cache.write_text(json.dumps(payload))
        return payload

    raise OverpassError("all mirrors failed -> " + "; ".join(errors))


def buildings(bbox) -> list[dict]:
    """Building ways with full geometry inside the bbox."""
    ql = (
        f'[out:json][timeout:90];'
        f'(way["building"]({bbox.overpass()}););'
        f'out geom;'
    )
    return query(ql)["elements"]


def roads(bbox) -> list[dict]:
    """Highway ways with full geometry. Includes footways: London sidewalks
    are mapped individually and we want them for the street surface pass."""
    ql = (
        f'[out:json][timeout:90];'
        f'(way["highway"]({bbox.overpass()}););'
        f'out geom;'
    )
    return query(ql)["elements"]
