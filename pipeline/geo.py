"""Geodetic helpers.

Everything downstream works in local metres, not degrees. At block scale a
local tangent plane centred on the site is accurate to well under a metre,
which is far below the noise floor of OSM footprints, so there is no reason
to pull in a full projection library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# WGS84 semi-major axis.
_R = 6378137.0


@dataclass(frozen=True)
class BBox:
    """A lat/lon bounding box, south/west/north/east."""

    south: float
    west: float
    north: float
    east: float

    @property
    def centre(self) -> tuple[float, float]:
        return (self.south + self.north) / 2.0, (self.west + self.east) / 2.0

    def overpass(self) -> str:
        return f"{self.south},{self.west},{self.north},{self.east}"

    def size_m(self) -> tuple[float, float]:
        """Ground size as (width, height) in metres."""
        proj = Projection.for_bbox(self)
        x0, y0 = proj.to_local(self.south, self.west)
        x1, y1 = proj.to_local(self.north, self.east)
        return abs(x1 - x0), abs(y1 - y0)

    @classmethod
    def centred_on(cls, lat: float, lon: float, size_m: float) -> "BBox":
        """Square box of `size_m` metres a side, centred on a point."""
        half = size_m / 2.0
        dlat = math.degrees(half / _R)
        dlon = math.degrees(half / (_R * math.cos(math.radians(lat))))
        return cls(lat - dlat, lon - dlon, lat + dlat, lon + dlon)


class Projection:
    """Local tangent-plane projection: lat/lon <-> metres east/north of origin."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self._cos_lat0 = math.cos(math.radians(lat0))

    @classmethod
    def for_bbox(cls, bbox: BBox) -> "Projection":
        lat, lon = bbox.centre
        return cls(lat, lon)

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        x = _R * math.radians(lon - self.lon0) * self._cos_lat0
        y = _R * math.radians(lat - self.lat0)
        return x, y

    def to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        lat = self.lat0 + math.degrees(y / _R)
        lon = self.lon0 + math.degrees(x / (_R * self._cos_lat0))
        return lat, lon

    def ring_to_local(self, geometry: list[dict]) -> list[tuple[float, float]]:
        """Convert an Overpass `geometry` array into a local-metre ring."""
        return [self.to_local(p["lat"], p["lon"]) for p in geometry]
